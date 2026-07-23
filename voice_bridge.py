#!/usr/bin/env python3
"""Voice Bridge — connect a voice provider to Coding Vibe's AudioChannel.

The bridge runs alongside OpenOPC and bridges:
  Voice Provider (StepAudio/Seeduplex) → transcript → AudioChannel inbound queue
  AudioChannel.send() → TTS → speaker

Supports three modes:
  halfduplex  — stdin text input, macOS `say` output (always works, no API key)
  stepaudio   — StepFun Realtime API (WebSocket, needs API key)
  seeduplex   — ByteDance Seeduplex (WebRTC, needs npm @bytedance/seed-sdk)

Usage:
  uv run python3 voice_bridge.py --mode halfduplex
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
    """StepAudio mode: WebSocket → transcripts → AudioChannel."""
    from opc.channels.audio import push_transcript

    print("[bridge] StepAudio mode — not yet implemented")
    print("[bridge] Requires: WebSocket connection to wss://api.stepfun.com/v1/realtime")
    print("[bridge] API key:", api_key[:10] + "..." if api_key else "(not set)")
    print()
    print("[bridge] Falling back to halfduplex mode...")
    await run_halfduplex()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Coding Vibe Voice Bridge")
    parser.add_argument(
        "--mode", choices=["halfduplex", "stepaudio", "seeduplex"],
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
    else:
        await run_halfduplex()


if __name__ == "__main__":
    asyncio.run(main())
