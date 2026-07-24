#!/usr/bin/env python3
"""Voice Bridge — connect a voice provider to Coding Vibe's AudioChannel.

The bridge runs alongside OpenOPC and bridges:
  Voice Provider (StepAudio/Seeduplex) → transcript → AudioChannel inbound queue
  AudioChannel.send() → TTS → speaker

Supports four modes:
  halfduplex  — stdin text input, macOS `say` output (always works, no API key)
  livekit     — LiveKit agents: Deepgram STT -> DeepSeek LLM -> Deepgram TTS
  stepaudio   — StepFun Realtime API (WebSocket, needs API key)
  seeduplex   — ByteDance Seeduplex (WebRTC, needs npm @bytedance/seed-sdk)

Usage:
  uv run python3 voice_bridge.py --mode halfduplex
  uv run python3 voice_bridge.py --mode livekit
  uv run python3 voice_bridge.py --mode seeduplex --api-key sk-...
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

# Add OpenOPC to path so we can import its channels
OPC_PATH = Path.home() / "Projects" / "OpenOPC"
sys.path.insert(0, str(OPC_PATH))


async def _ensure_audio_channel_running() -> None:
    """Verify AudioChannel is importable."""
    try:
        from opc.channels.audio import AudioChannel, push_transcript, _inbound_queue
        print("[bridge] AudioChannel module loaded")
        return
    except ImportError as e:
        print(f"[bridge] ERROR: Cannot import AudioChannel: {e}")
        print("[bridge] Make sure OpenOPC is installed: cd ~/Projects/OpenOPC && uv pip install -e .")
        sys.exit(1)


async def run_livekit() -> None:
    """LiveKit mode: Deepgram STT → LLM (configurable provider) → Deepgram TTS.

    The LLM in the LiveKit AgentSession IS the Boss (CS receptionist).
    Provider is controlled by CV_CS_PROVIDER env var:
      - deepseek  (default) — DeepSeek Chat via OpenAI-compatible endpoint
      - stepfun   — StepFun step-router-v1 via OpenAI-compatible endpoint
    """
    from dotenv import load_dotenv
    load_dotenv()

    livekit_url = os.getenv("LIVEKIT_URL")
    if not livekit_url:
        print("[bridge] LiveKit not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")
        print("[bridge] Falling back to halfduplex mode...")
        await run_halfduplex()
        return

    try:
        from livekit.agents import AgentSession, AutoSubscribe, cli, inference
        from livekit.agents.voice import TurnHandlingOptions
        from agent import CodingVibeAgent
    except ImportError as e:
        print(f"[bridge] LiveKit agents not installed: {e}")
        print("[bridge] Run: uv pip install livekit-agents python-dotenv")
        print("[bridge] Falling back to halfduplex mode...")
        await run_halfduplex()
        return

    cs_provider = os.getenv("CV_CS_PROVIDER", "deepseek").lower()
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_key:
        print("[bridge] Missing DEEPGRAM_API_KEY — falling back to halfduplex mode...")
        await run_halfduplex()
        return

    if cs_provider == "stepfun":
        stepfun_key = os.getenv("STEPFUN_API_KEY")
        stepfun_base = os.getenv("STEPFUN_BASE_URL", "https://api.stepfun.com/v1")
        stepfun_model = os.getenv("STEPFUN_MODEL", "step-router-v1")
        if not stepfun_key:
            print("[bridge] CV_CS_PROVIDER=stepfun but STEPFUN_API_KEY is not set — falling back to halfduplex...")
            await run_halfduplex()
            return
        llm_kwargs = dict(
            base_url=stepfun_base,
            model=stepfun_model,
            api_key=stepfun_key,
        )
        print(f"[bridge] STT: deepgram/nova-3 | LLM: {stepfun_model} (StepFun) | TTS: deepgram/aura-asteria-en")
    else:
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if not deepseek_key:
            print("[bridge] CV_CS_PROVIDER=deepseek but DEEPSEEK_API_KEY is not set — falling back to halfduplex...")
            await run_halfduplex()
            return
        llm_kwargs = dict(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key=deepseek_key,
        )
        print(f"[bridge] STT: deepgram/nova-3 | LLM: deepseek-chat (DeepSeek) | TTS: deepgram/aura-asteria-en")

    agent = CodingVibeAgent(project=os.getenv("CV_PROJECT", "demo"))

    session = AgentSession(
        stt=inference.STT(
            model="deepgram/nova-3",
            api_key=deepgram_key,
            language="multi",
        ),
        llm=inference.LLM.with_openai(**llm_kwargs),
        tts=inference.TTS(
            model="deepgram/aura-asteria-en",
            api_key=deepgram_key,
        ),
        agent=agent,
        turn_handling=TurnHandlingOptions(
            interruption={"enabled": True},
            preemptive_generation={"enabled": True, "max_retries": 3},
        ),
        auto_subscribe=AutoSubscribe.AUDIO_ONLY,
    )

    print(f"[bridge] LiveKit mode — connecting to {livekit_url}")
    print(f"[bridge] CS provider: {cs_provider}")
    print("[bridge] Ctrl+C to exit")
    print()

    cli.run.app(livekit_url, session)


async def run_halfduplex() -> None:
    """Half-duplex mode: stdin text → AudioChannel, macOS say ← TTS output."""
    from opc.channels.audio import push_transcript

    print("[bridge] Half-duplex mode — type messages, press Enter to send")
    print("[bridge] Ctrl+C to exit")
    print()

    loop = asyncio.get_running_loop()
    running = True

    def _stop() -> None:
        nonlocal running
        running = False
        print("\n[bridge] Stopping...")

    loop.add_signal_handler(signal.SIGINT, _stop)
    loop.add_signal_handler(signal.SIGTERM, _stop)

    # Read stdin in a thread to avoid blocking the event loop
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    while running:
        try:
            line = await loop.run_in_executor(executor, sys.stdin.readline)
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            break

        text = line.strip()
        if not text:
            continue

        if text.lower() in ("/exit", "/quit", "/q"):
            break

        push_transcript(text, "voice-user")
        print(f"[bridge] → Boss: {text[:80]}{'...' if len(text) > 80 else ''}")

    print("[bridge] Half-duplex bridge stopped")


async def run_seeduplex(api_key: str) -> None:
    """Seeduplex mode: WebRTC voice → transcripts → AudioChannel."""
    from opc.channels.audio import push_transcript

    print("[bridge] Seeduplex mode — not yet implemented")
    print("[bridge] Requires: npm install @bytedance/seed-sdk")
    print("[bridge] API key:", api_key[:10] + "..." if api_key else "(not set)")
    print()
    print("[bridge] Falling back to halfduplex mode...")
    await run_halfduplex()


async def run_stepaudio(api_key: str) -> None:
    """StepAudio mode: WebSocket realtime voice → transcripts → AudioChannel.

    Uses StepFun's Realtime API (wss://api.stepfun.com/v1/realtime) with the
    stepaudio-2.5-realtime model.  Server-side VAD handles speech detection
    and the API returns both text and audio in the same stream.

    API reference: https://platform.stepfun.com/docs/zh/api-reference/realtime/chat
    """
    from opc.channels.audio import push_transcript

    if not api_key:
        print("[bridge] STEPFUN_API_KEY not set — cannot start stepaudio mode")
        print("[bridge] Add STEPFUN_API_KEY to your .env file and try again.")
        print("[bridge] Falling back to halfduplex mode...")
        await run_halfduplex()
        return

    try:
        import websockets
    except ImportError:
        print("[bridge] websockets package not installed")
        print("[bridge] Run: uv pip install websockets")
        print("[bridge] Falling back to halfduplex mode...")
        await run_halfduplex()
        return

    base_url = os.getenv("STEPFUN_BASE_URL", "https://api.stepfun.com/v1")
    model = os.getenv("STEPFUN_REALTIME_MODEL", "stepaudio-2.5-realtime")
    ws_url = f"{base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/realtime?model={model}"
    default_instructions = (
        "你是有耐心的陪伴搭子，回答自然、温暖、有人情味。"
        "保持简洁，适合语音对话。"
    )

    print(f"[bridge] StepAudio realtime mode")
    print(f"[bridge] Endpoint : {ws_url}")
    print(f"[bridge] Model    : {model}")
    print(f"[bridge] API key  : {api_key[:10]}...")
    print()

    loop = asyncio.get_running_loop()
    running = True

    def _stop() -> None:
        nonlocal running
        running = False
        print("\n[bridge] Stopping...")

    loop.add_signal_handler(signal.SIGINT, _stop)
    loop.add_signal_handler(signal.SIGTERM, _stop)

    response_active = False   # guards push_transcript calls (one response = one user turn)

    async def handle_message(msg: str) -> None:
        """Parse a single server event JSON line."""
        nonlocal response_active
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            return

        evt_type = data.get("type", "")

        # --- Transcript text deltas (streaming) ---
        if evt_type == "response.text.delta":
            delta = data.get("delta", "")
            if delta and response_active:
                push_transcript(delta, "voice-user")
                print(f"[stepaudio] transcript: {delta!r}")

        # --- Text response finished ---
        elif evt_type == "response.text.done":
            print("[stepaudio] response complete")

        # --- Full item created (includes final text) ---
        elif evt_type in ("response.content_part.done", "response.output_item.done"):
            part = data.get("part") or data.get("item") or {}
            content = part.get("content") or part.get("text") or ""
            if isinstance(content, list):
                content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
            if content and response_active:
                push_transcript(content, "voice-user")
                print(f"[stepaudio] push_transcript: {content[:120]!r}")

        # --- Response started / finished bookkeeping ---
        elif evt_type == "response.created":
            response_active = True

        elif evt_type in ("response.done", "response.error"):
            response_active = False
            if evt_type == "response.error":
                err = data.get("error", {})
                print(f"[stepaudio] response error: {err}")

        # --- Session lifecycle ---
        elif evt_type == "session.created":
            print("[stepaudio] session created — sending session.update ...")
            instructions = os.getenv("STEPFUN_SYSTEM_INSTRUCTIONS", default_instructions)
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": instructions,
                    # voice can be overridden via STEPFUN_VOICE env var
                    **({"voice": os.getenv("STEPFUN_VOICE", "")}
                       if os.getenv("STEPFUN_VOICE") else {}),
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                },
            }
            await ws.send(json.dumps(session_update))

        elif evt_type == "session.updated":
            print("[stepaudio] session updated — ready for audio input")
            # After session is configured, the server starts streaming mic audio;
            # we don't need to send text prompts manually — VAD handles the turn.
            # We simply listen and forward transcripts.

        elif evt_type == "error":
            print(f"[stepaudio] server error: {data}")

    async with websockets.connect(
        ws_url,
        additional_headers={"Authorization": f"Bearer {api_key}"},
        ping_interval=20,
        ping_timeout=10,
    ) as ws:
        print("[bridge] WebSocket connected — waiting for session.created...")
        print("[bridge] Speak into your mic — StepFun VAD will detect speech and generate responses.")
        print("[bridge] Ctrl+C to exit")
        print()

        recv_task = asyncio.create_task(_recv_loop(ws, handle_message))

        # Keep the connection alive until stopped
        try:
            while running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            running = False
            recv_task.cancel()
            try:
                await ws.close()
            except Exception:
                pass

    print("[bridge] StepAudio bridge stopped")


async def _recv_loop(ws, handler):
    """Drain WebSocket messages and dispatch to handler."""
    try:
        async for raw in ws:
            await handler(raw if isinstance(raw, str) else raw.decode())
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[stepaudio] recv error: {exc}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Coding Vibe Voice Bridge")
    parser.add_argument(
        "--mode", choices=["halfduplex", "livekit", "stepaudio", "seeduplex"],
        default="halfduplex", help="Voice provider mode"
    )
    parser.add_argument("--api-key", default=os.getenv("STEPAUDIO_API_KEY", ""),
                        help="API key for voice provider")
    parser.add_argument("--seeduplex-key", default=os.getenv("SEEDUPLEX_API_KEY", ""),
                        help="Seeduplex API key")
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════╗")
    print("║   Coding Vibe — Voice Bridge            ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  Mode: {args.mode}")
    print()

    await _ensure_audio_channel_running()

    if args.mode == "seeduplex":
        await run_seeduplex(args.seeduplex_key or args.api_key)
    elif args.mode == "stepaudio":
        await run_stepaudio(args.api_key)
    elif args.mode == "livekit":
        await run_livekit()
    else:
        await run_halfduplex()


if __name__ == "__main__":
    asyncio.run(main())
