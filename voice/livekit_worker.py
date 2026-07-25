"""voice/livekit_worker.py — LiveKit voice agent for Coding Vibe (BACKUP).

This is a LiveKit-based alternative to the StepFun WebSocket approach.
Unlike the Pipecat SmallWebRTC approach, LiveKit uses a mature SFU server
for WebRTC signaling — no P2P WebRTC headaches.

Architecture
    Browser (WebRTC, livekit-client)  →  LiveKit SFU (port 7880)
        →  This worker (Python, livekit-agents)
            ├── livekit.plugins.openai.STT  → StepFun /v1/audio/transcriptions (step-asr)
            ├── livekit.plugins.openai.LLM  → StepFun /v1/chat/completions (step-3.7-flash)
            └── livekit.plugins.openai.TTS  → StepFun /v1/audio/speech (step-tts-2)

Plugins route directly to StepFun via base_url — NO LiveKit Cloud dependency.

System instructions are seeded via the Agent class (AgentSession.start(agent=...)).

Usage
-----
    python3 voice/livekit_worker.py start    # production
    python3 voice/livekit_worker.py dev      # dev / testing
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Project root for web.engineer_dispatch ────────────────────────────────
_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT / ".env")

from web.engineer_dispatch import (  # noqa: E402
    CS_VOICE_PERSONA,
    DISPATCH_TOOL_DESCRIPTION,
)

# ── LiveKit imports ───────────────────────────────────────────────────────
from livekit.agents import (  # noqa: E402
    Agent,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    AgentSession,
    cli,
)
from livekit.agents.llm import function_tool  # noqa: E402

# ── LiveKit plugins (OpenAI-compatible, StepFun-backed) ──────────────────
from livekit.plugins.openai import (  # noqa: E402
    STT,
    TTS,
    LLM,
)


# ── Persona ───────────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTIONS = CS_VOICE_PERSONA


# ── Tool ──────────────────────────────────────────────────────────────────


@function_tool(
    name="dispatch_to_engineer",
    description=DISPATCH_TOOL_DESCRIPTION,
)
async def dispatch_to_engineer(task: str) -> str:
    """Dispatch *task* to the engineering team via shared dispatch module."""
    from web.engineer_dispatch import dispatch_to_engineer as _dispatch

    try:
        result = await _dispatch(task)
    except Exception as exc:
        return f"抱歉，安排工程师时出错了：{exc}"

    if result.get("status") == "error":
        return f"抱歉，安排工程师时出错了：{result.get('error', '未知错误')}"
    return (
        f"已将这项工作交给工程团队（任务号 {result.get('task_id', '?')}）。"
        "你可以继续补充细节；有确定进展时我会告诉你。"
    )


# ── CS Agent (with instructions) ──────────────────────────────────────────


class CSAgent(Agent):
    """Coding Vibe receptionist agent with system instructions."""

    def __init__(self) -> None:
        super().__init__(
            instructions=_SYSTEM_INSTRUCTIONS,
            tools=[dispatch_to_engineer],
        )


# ── Entrypoint ────────────────────────────────────────────────────────────


async def entrypoint(ctx: JobContext) -> None:
    """Called by LiveKit when a room job is assigned to this worker.

    Creates an AgentSession with StepFun-backed STT/LLM/TTS plugins
    and a CSAgent with our system instructions + tools.
    """
    stepfun_key = os.environ.get("STEPFUN_API_KEY", "")
    stepfun_base = os.environ.get(
        "STEPFUN_BASE_URL", "https://api.stepfun.com/v1"
    )

    if not stepfun_key:
        print("[livekit_worker] FATAL: STEPFUN_API_KEY not set")
        return

    # Build the session with plugin instances routing to StepFun
    session = AgentSession(
        stt=STT(
            model="step-asr",
            base_url=stepfun_base,
            api_key=stepfun_key,
            use_realtime=False,  # REST mode: per-utterance transcriptions
        ),
        llm=LLM(
            model="step-3.7-flash",
            base_url=stepfun_base,
            api_key=stepfun_key,
        ),
        tts=TTS(
            model="step-tts-2",
            base_url=stepfun_base,
            api_key=stepfun_key,
        ),
        auto_subscribe=AutoSubscribe.AUDIO_ONLY,
    )

    # Start with our agent (carries instructions + tools)
    agent = CSAgent()
    print(
        f"[livekit_worker] Room: {ctx.room.name} | "
        f"LLM: step-3.7-flash | STT: step-asr | TTS: step-tts-2"
    )
    await session.start(agent=agent, room=ctx.room)
    print("[livekit_worker] Session started — agent is live")


def main() -> None:
    """Start the LiveKit worker."""
    livekit_url = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
    ws_url = (
        livekit_url
        if livekit_url.startswith("ws")
        else livekit_url.replace("http", "ws")
    )

    opts = WorkerOptions(
        entrypoint_fnc=entrypoint,
        ws_url=ws_url,
        api_key=os.environ.get("LIVEKIT_API_KEY", ""),
        api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
    )
    print(f"[livekit_worker] Listening on {ws_url}")
    print(
        "[livekit_worker] LLM: step-3.7-flash | STT: step-asr | TTS: step-tts-2"
    )
    print("[livekit_worker] Ctrl+C to exit\n")
    cli.run_app(opts)


if __name__ == "__main__":
    main()
