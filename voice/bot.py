"""voice/bot.py — Pipecat voice pipeline for Coding Vibe (Pipecat 1.6.0 API).

Pipeline
--------
SmallWebRTCTransport (P2P, no server — class lives in
    pipecat.transports.smallwebrtc.transport)
  → Deepgram STT (nova-3, multilingual zh+en)
  → LLM context / turn aggregation (Silero VAD)
  → LLM (step-3.7-flash via OpenAILLMService + StepFun base_url)
      • ``dispatch_to_engineer`` registered as a Pipecat function tool
        (wired to ``web.engineer_dispatch.dispatch_to_engineer``)
  → StepFun TTS (step-tts-2 via custom ``StepFunTTSService``)

Run
---
    /Users/onezion12344/miniforge3/bin/python3 voice/bot.py

The bot opens a browser page for SmallWebRTC audio I/O.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# ── Optional dotenv ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args: object, **kwargs: object) -> None:
        pass

load_dotenv()

# ── Project path ─────────────────────────────────────────────────────────────────
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_WORKTREE_ROOT))

# ── Pipecat 1.6.0 imports ────────────────────────────────────────────────────────
try:
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    # SmallWebRTCTransport is in the submodule, not the package __init__
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.services.deepgram.stt import DeepgramSTTService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    # LLM context / turn aggregation — Pipecat 1.6.0 uses LLMFullResponseAggregator
    from pipecat.processors.aggregators.llm_response import LLMFullResponseAggregator
    # Context frames and VAD params live in frames
    from pipecat.frames.frames import (
        EndFrame,
        LLMContextFrame,
        TextFrame,
        VADParams,
    )
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    _PIPECAT_OK = True
except ImportError as exc:
    print(f"[pipecat] IMPORT ERROR: {exc}", flush=True)
    print(
        "[pipecat] Fix: /Users/onezion12344/miniforge3/bin/pip3 install "
        "'pipecat-ai[deepgram,openai,silero,webrtc]'",
        flush=True,
    )
    _PIPECAT_OK = False

# Local imports (wrapped to allow module import without full deps)
try:
    from voice.stepfun_tts import StepFunTTSService
    from web.engineer_dispatch import dispatch_to_engineer, TOOLS
except ImportError as exc:
    print(f"[bot] local import error: {exc}", flush=True)
    dispatch_to_engineer = None  # type: ignore[assignment]
    TOOLS = []  # type: ignore[assignment]
    StepFunTTSService = None  # type: ignore[assignment]


# ── Config ────────────────────────────────────────────────────────────────────────

DEEPGRAM_API_KEY: str = os.environ.get("DEEPGRAM_API_KEY", "")
STEPFUN_API_KEY: str = os.environ.get("STEPFUN_API_KEY", "")
STEPFUN_BASE_URL: str = os.environ.get(
    "STEPFUN_BASE_URL", "https://api.stepfun.com/v1"
)
CS_BRAIN_MODEL: str = os.environ.get("CV_CS_BRAIN_MODEL", "step-3.7-flash")

# ── CS persona ───────────────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTIONS = (
    "你是 Coding Vibe 工作室的电话接线员（CS）。说话简短、自然、口语化，像在打电话。"
    "如果来电者想做/写/改某个代码或功能，就热情、简短地回应：『好的，我马上安排工程师处理，"
    "忙完打给你哈。』然后就好——不要自己写代码、不要解释实现细节。"
    "如果只是闲聊或问进度，就自然地聊。始终友好。"
)


# ── Function-tool handler ────────────────────────────────────────────────────────


async def _dispatch_handler(task: str) -> str:
    """Pipecat function-tool handler for ``dispatch_to_engineer``.

    Args:
        task: The task description the LLM extracted from the user's turn.

    Returns:
        A natural-language confirmation string for the LLM to voice.
    """
    if dispatch_to_engineer is None:
        return "Dispatch service is temporarily unavailable."

    try:
        result = await dispatch_to_engineer(task)
    except Exception as exc:
        return f"Dispatch failed: {exc}"

    task_id = result.get("task_id", "?")
    return (
        f"Task dispatched (id={task_id}). "
        "Give the user a short, warm Chinese confirmation, then stop — "
        "do not keep talking about the task details."
    )


def _build_tools_schema() -> ToolsSchema:
    """Build the Pipecat ``ToolsSchema`` using the shared TOOLS from
    ``web.engineer_dispatch`` so both backends share an identical tool schema."""
    schemas = []
    for t in TOOLS:
        fn = t["function"]
        schemas.append(
            FunctionSchema(
                name=fn["name"],
                description=fn["description"],
                properties=fn["parameters"]["properties"],
                required=fn["parameters"].get("required", []),
            )
        )
    return ToolsSchema(standard_tools=schemas)


# ── Pipeline factory ─────────────────────────────────────────────────────────────


def build_pipeline(transport: SmallWebRTCTransport) -> Pipeline:
    """Build a Pipecat ``Pipeline`` wired for the Coding Vibe CS agent.

    Args:
        transport: An open ``SmallWebRTCTransport`` instance (P2P, no server).

    Returns:
        A :class:`Pipeline` ready for :class:`PipelineRunner`.
    """
    if not _PIPECAT_OK:
        raise RuntimeError(
            "pipecat failed to import.  "
            "Run: /Users/onezion12344/miniforge3/bin/pip3 install "
            "'pipecat-ai[deepgram,openai,silero,webrtc]'"
        )

    # ── STT ────────────────────────────────────────────────────────────────────
    stt = DeepgramSTTService(
        api_key=DEEPGRAM_API_KEY,
        model="nova-3",
        language="zh",
    )

    # ── VAD + turn detection ────────────────────────────────────────────────────
    vad_analyzer = SileroVADAnalyzer()

    # LLMFullResponseAggregator is the single aggregator in Pipecat 1.6.0;
    # it manages user/assistant turn boundaries internally.
    response_aggregator = LLMFullResponseAggregator()

    # ── LLM ─────────────────────────────────────────────────────────────────────
    tools_schema = _build_tools_schema()

    llm = OpenAILLMService(
        api_key=STEPFUN_API_KEY,
        base_url=STEPFUN_BASE_URL,
        model=CS_BRAIN_MODEL,
        tools=tools_schema,
    )

    # Seed system prompt via an LLMContextFrame
    context_frame = LLMContextFrame(
        context=[
            {
                "role": "system",
                "content": _SYSTEM_INSTRUCTIONS,
            }
        ]
    )

    # Register the function-tool handler.
    llm.register_function("dispatch_to_engineer", _dispatch_handler)

    # ── TTS ─────────────────────────────────────────────────────────────────────
    if StepFunTTSService is None:
        raise RuntimeError("StepFunTTSService could not be imported")

    tts = StepFunTTSService(
        api_key=STEPFUN_API_KEY,
        base_url=STEPFUN_BASE_URL,
        voice_id="step-tts-2",
    )

    # ── Pipeline ────────────────────────────────────────────────────────────────
    pipeline = Pipeline(
        [
            transport.input(),       # receive audio from browser via WebRTC
            stt,                      # speech → text
            response_aggregator,      # aggregate turns (VAD-gated)
            llm,                      # text LLM + function-calling
            tts,                      # text → audio
            transport.output(),       # send audio back to browser
        ]
    )

    # Pre-seed the system message by pushing a context frame before starting.
    # The pipeline task runs this as the first frame.
    return pipeline


# ── Main ─────────────────────────────────────────────────────────────────────────


async def main(transport: SmallWebRTCTransport) -> None:
    """Wire up the pipeline and start the runner.

    This is the callback Pipecat's ``SmallWebRTCTransport`` calls once a
    browser peer connects::

        transport = SmallWebRTCTransport()
        asyncio.run(main(transport))
    """
    pipeline = build_pipeline(transport)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            # allow_interruptions=True enables barge-in: the user can speak
            # over the CS mid-turn and the pipeline will respond immediately.
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    runner = PipelineRunner()
    await runner.run(task)


# ── Standalone / dev entry ───────────────────────────────────────────────────────


def _check_env() -> dict[str, str]:
    """Return a dict of missing env vars and why they are needed."""
    missing = {}
    if not DEEPGRAM_API_KEY:
        missing["DEEPGRAM_API_KEY"] = "Required for Deepgram STT (nova-3)"
    if not STEPFUN_API_KEY:
        missing["STEPFUN_API_KEY"] = "Required for StepFun LLM + TTS"
    return missing


if __name__ == "__main__":
    if not _PIPECAT_OK:
        print(
            "\n[FATAL] pipecat failed to import.  "
            "Install with: /Users/onezion12344/miniforge3/bin/pip3 install "
            "'pipecat-ai[deepgram,openai,silero,webrtc]'\n",
            flush=True,
        )
        sys.exit(1)

    missing = _check_env()
    if missing:
        print("\n[FATAL] Missing required environment variables:")
        for k, v in missing.items():
            print(f"  {k}: {v}")
        print(
            "\nCopy .env.example to .env and fill in the keys, or export them.\n",
            flush=True,
        )
        sys.exit(1)

    print("[bot] Starting SmallWebRTCTransport …", flush=True)
    transport = SmallWebRTCTransport()
    asyncio.run(main(transport))
