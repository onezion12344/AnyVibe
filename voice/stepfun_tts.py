"""voice/stepfun_tts.py — Custom StepFun TTS service for Pipecat 1.6.0.

Subclasses Pipecat's ``TTSService`` and calls StepFun's
``POST /v1/audio/speech`` (model ``step-tts-2``) for TTS synthesis.

``run_tts`` is an **async generator** that yields
``TTSAudioRawFrame`` instances — the Pipecat 1.6.0 contract.

Usage in a Pipecat pipeline::

    from voice.stepfun_tts import StepFunTTSService

    tts = StepFunTTSService(
        api_key=os.getenv("STEPFUN_API_KEY"),
        base_url=os.getenv("STEPFUN_BASE_URL", "https://api.stepfun.com/v1"),
        voice_id="step-tts-2",
    )
"""

from __future__ import annotations

import json
import os
from typing import AsyncGenerator, Optional

import httpx

# Pipecat imports — guarded so the module imports cleanly even before install.
try:
    from pipecat.services.tts_service import TTSService, TTSAudioRawFrame, TTSSettings
    from pipecat.frames.frames import ErrorFrame, Frame, StartFrame, EndFrame
    _PIPECAT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIPECAT_AVAILABLE = False
    TTSService = object  # type: ignore[assignment]
    TTSAudioRawFrame = None  # type: ignore[assignment,misc]
    TTSSettings = object  # type: ignore[assignment]

__all__ = ["StepFunTTSService"]


class StepFunTTSService(TTSService):
    """StepFun TTS — ``POST /v1/audio/speech`` (model ``step-tts-2``).

    The response is ``audio/wav``; the service decodes it to raw PCM16 and
    yields ``TTSAudioRawFrame`` instances for each chunk so the rest of the
    Pipecat pipeline sees it as streaming audio.

    Parameters
    ----------
    api_key:
        StepFun API key.  Falls back to ``STEPFUN_API_KEY`` env var.
    base_url:
        StepFun API base URL.  Defaults to ``https://api.stepfun.com/v1``.
    voice_id:
        Voice identifier sent to StepFun as ``voice`` in the request body.
        Default ``step-tts-2``.
    sample_rate:
        Desired output sample rate (Hz).  Default ``24000``.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        voice_id: str = "step-tts-2",
        sample_rate: int = 24_000,
        **kwargs: object,
    ) -> None:
        if not _PIPECAT_AVAILABLE:
            raise ImportError(
                "pipecat is not installed.  "
                "Run: /Users/onezion12344/miniforge3/bin/pip3 install "
                "'pipecat-ai[deepgram,openai,silero,webrtc]'"
            )

        self._api_key: str = api_key or os.environ.get("STEPFUN_API_KEY", "")
        self._base_url: str = (
            base_url
            or os.environ.get("STEPFUN_BASE_URL", "https://api.stepfun.com/v1")
        ).rstrip("/")
        self._voice_id: str = voice_id
        self._sample_rate: int = sample_rate

        if not self._api_key:
            raise ValueError("STEPFUN_API_KEY is required for StepFunTTSService")

        # Pipecat TTSService accepts keyword args for sample_rate / settings.
        super().__init__(sample_rate=sample_rate, **kwargs)  # type: ignore[arg-type]

    # ── Internal ────────────────────────────────────────────────────────────────

    def _tts_url(self) -> str:
        return f"{self._base_url}/audio/speech"

    async def _synthesize(self, text: str) -> bytes:
        """Call StepFun TTS and return raw ``audio/wav`` bytes."""
        payload: dict[str, Any] = {
            "model": self._voice_id,
            "input": text,
            "voice": self._voice_id,
            "response_format": "wav",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self._tts_url(),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.content

    # ── Pipecat TTSService interface ────────────────────────────────────────────

    async def run_tts(  # type: ignore[override]
        self, text: str, context_id: str
    ) -> AsyncGenerator[Frame | None, None]:
        """Synthesise *text* and yield ``TTSAudioRawFrame`` chunks.

        Pipecat 1.6.0 requires ``run_tts`` to be an async generator
        (``yield`` frames, not return a single frame).
        """
        if not _PIPECAT_AVAILABLE or TTSAudioRawFrame is None:
            raise RuntimeError("pipecat not available")

        try:
            wav_bytes = await self._synthesize(text)
        except Exception as exc:
            yield ErrorFrame(error=str(exc))  # type: ignore[misc]
            return

        # Parse the WAV header to find the PCM data offset and format.
        pcm_data = self._extract_pcm(wav_bytes)

        # Yield raw PCM in ~960-byte (20 ms) chunks so the pipeline
        # sees steady, bounded frames.
        chunk_size = self._sample_rate * 2 // 50  # 960 bytes at 24 kHz
        for i in range(0, len(pcm_data), chunk_size):
            chunk = pcm_data[i : i + chunk_size]
            yield TTSAudioRawFrame(
                audio=chunk,
                sample_rate=self._sample_rate,
                num_channels=1,
            )

    @staticmethod
    def _extract_pcm(wav_bytes: bytes) -> bytes:
        """Strip the WAV header and return the raw PCM data."""
        # RIFF header: bytes 0-3 = "RIFF", 4-7 = file_size-8,
        # 8-11 = "WAVE", 12-15 = "fmt ", 16-19 = chunk size
        if len(wav_bytes) < 44 or wav_bytes[0:4] != b"RIFF":
            # Not a valid WAV — return as-is and let downstream handle it.
            return wav_bytes

        # Standard PCM WAV: data chunk starts at byte 44
        if wav_bytes[36:40] == b"data":
            return wav_bytes[44:]
        # Fallback: scan for the data chunk
        pos = 12
        while pos < len(wav_bytes) - 8:
            chunk_id = wav_bytes[pos : pos + 4]
            chunk_size = int.from_bytes(wav_bytes[pos + 4 : pos + 8], "little")
            if chunk_id == b"data":
                return wav_bytes[pos + 8 : pos + 8 + chunk_size]
            pos += 8 + chunk_size
        return wav_bytes

    async def start(self, frame: StartFrame) -> None:
        """No-op — StepFun TTS is stateless per-request."""
        pass

    async def stop(self, frame: EndFrame) -> None:
        """No-op — StepFun TTS is stateless per-request."""
        pass
