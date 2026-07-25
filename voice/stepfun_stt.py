"""voice/stepfun_stt.py — StepFun `step-asr` as a Pipecat SegmentedSTTService.

We already have a valid StepFun key, so Pipecat runs StepFun end-to-end
(step-asr → step-3.7-flash → step-tts-2) with NO Deepgram dependency.

SegmentedSTTService buffers each VAD-detected utterance and hands us a WAV blob
(``wants_wav_segments`` defaults True — exactly what step-asr's upload API wants).
We POST it to ``/v1/audio/transcriptions`` and emit a TranscriptionFrame per turn.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.utils.time import time_now_iso8601


class StepFunSTTService(SegmentedSTTService):
    """Per-utterance STT via StepFun step-asr (OpenAI-compatible transcriptions)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.stepfun.com/v1",
        model: str = "step-asr",
        language: str = "zh",
        sample_rate: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._language = language

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """`audio` is a WAV container (wants_wav_segments=True). Transcribe it."""
        url = f"{self._base_url}/audio/transcriptions"
        files = {
            "file": ("audio.wav", audio, "audio/wav"),
            "model": (None, self._model),
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files=files,
                )
            if r.status_code != 200:
                logger.warning(f"StepFun ASR {r.status_code}: {r.text[:160]}")
                yield ErrorFrame(f"StepFun ASR {r.status_code}")
                return
            data = r.json()
            text = (data.get("text") or data.get("transcript") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"StepFun ASR error: {exc}")
            yield ErrorFrame(f"StepFun ASR error: {exc}")
            return

        if text:
            logger.debug(f"StepFun transcript: [{text}]")
            yield TranscriptionFrame(
                text, getattr(self, "_user_id", ""), time_now_iso8601(), self._language
            )
