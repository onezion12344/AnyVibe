"""web/call_bridge.py — StepFun Realtime voice bridge.

Refactored: core dispatch logic (dispatch_to_engineer, classify_and_dispatch,
TOOLS, config) lives in ``web/engineer_dispatch.py`` (backend-agnostic, shared
with the Pipecat bot).  This file only handles the StepFun WebSocket transport
layer — forwarding audio PCM frames, handling StepFun-specific event types, and
calling the shared classify + dispatch helpers.

server.py must mount this router:
    from web.call_bridge import router as call_bridge_router
    app.include_router(call_bridge_router)

Protocol: StepFun stepaudio-2.5-realtime WebSocket
  wss://api.stepfun.com/v1/realtime?model=stepaudio-2.5-realtime

Audio format:
  24 kHz / mono / PCM 16-bit LE / 480 frames per chunk (20 ms = 960 bytes raw)

WebSocket message flow:
  browser → /api/call WS → StepFun WS (input_audio_buffer.append, base64 PCM)
  StepFun WS → /api/call WS → browser (response.audio.delta, base64 PCM)

Shared dispatch logic: web/engineer_dispatch.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from web.auth import is_valid_token

# ── Config ────────────────────────────────────────────────────────────────────────

router = APIRouter()

# ── Shared dispatch config (imported from engineer_dispatch) ─────────────────────
# All backend-agnostic logic lives in web/engineer_dispatch.py.
from web.engineer_dispatch import (  # noqa: E402
    CS_VOICE_PERSONA,
    STEPFUN_BASE_URL,
    CV_API_TOKEN,
    DEFAULT_CALLER_NAME,
    STEPFUN_API_KEY,      # re-exported for StepFun WS auth
    normalize_caller_name,
    plan_call_opening,
    plan_call_turn,
    dispatch_to_engineer,
)

# Audio constants (PCM16 / 24 kHz / mono) — StepFun transport-specific
_SAMPLE_RATE = 24_000
_FRAMES_PER_CHUNK = 480  # 20 ms
_RAW_CHUNK_BYTES = _FRAMES_PER_CHUNK * 2  # 960 bytes per 20 ms chunk
_TRANSCRIPTION_MODEL = os.environ.get("STEPFUN_REALTIME_TRANSCRIPTION_MODEL", "step-asr")
_TTS_MODEL = os.environ.get("CV_CS_TTS_MODEL", "step-tts-2")
_TTS_VOICE = os.environ.get("CV_CS_TTS_VOICE", "livelybreezy-female")

# StepFun WebSocket URL — transport constant
STEPFUN_WS_URL = "wss://api.stepfun.com/v1/realtime?model=stepaudio-2.5-realtime"

# The realtime session acts only as low-latency ASR.  Tool decisions and every
# spoken answer use the text reasoning model + TTS below.  This removes the
# probabilistic tool calling of speech-to-speech models from the control path.
_SYSTEM_INSTRUCTIONS = CS_VOICE_PERSONA

# Maximum incoming message size (bytes) — defend against memory bombs
_MAX_WS_MESSAGE_BYTES = 1 << 20  # 1 MiB


# ── Helper: log to stdout with structured prefix ─────────────────────────────────


def _log(prefix: str, msg: str) -> None:
    print(f"[{prefix}] {msg}", flush=True)


# ── Helper: build StepFun client events ─────────────────────────────────────────


def _client_session_update(event_id: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": _SYSTEM_INSTRUCTIONS,
            "voice": "linjiajiejie",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            # The realtime model can respond in audio without emitting the
            # caller's words.  Dispatch is driven by that transcript, so this
            # opt-in is required for the CS → CEO handoff to run at all.
            "input_audio_transcription": {"model": _TRANSCRIPTION_MODEL},
            "turn_detection": {
                "type": "server_vad",
                # Keep enough leading speech when a caller starts talking
                # immediately after the channel opens.  The 300 ms default
                # clipped the opening words of a zero-pre-roll synthetic
                # utterance in an end-to-end VAD test; 600 ms still confines
                # ASR to the detected turn while preserving that onset.
                "prefix_padding_ms": 600,
                "silence_duration_ms": 500,
                # ASR only.  A completed transcript is routed through the text
                # planner, whose result is voiced by the TTS layer below.
                "create_response": False,
            },
        },
    }


def _client_audio_append(event_id: str, b64_audio: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "type": "input_audio_buffer.append",
        "audio": b64_audio,
    }


async def _speak_text(browser_ws: Any, text: str) -> float:
    """Synthesize *text* as 24 kHz PCM and stream it to the browser.

    Returns the duration of audio sent in seconds.  A TTS failure is surfaced
    as a structured browser event instead of leaving a caller with silence.
    """
    words = (text or "").strip()
    if not words or not STEPFUN_API_KEY:
        return 0.0
    payload = {
        "model": _TTS_MODEL,
        "input": words[:1000],
        "voice": _TTS_VOICE,
        "response_format": "pcm",
        "sample_rate": _SAMPLE_RATE,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{STEPFUN_BASE_URL}/audio/speech",
                headers={"Authorization": f"Bearer {STEPFUN_API_KEY}"},
                json=payload,
            )
        if response.status_code != 200:
            _log("TTS", f"non-200: {response.status_code} {response.text[:120]}")
            await browser_ws.send_json({"type": "assistant-text", "text": words})
            return 0.0
        pcm = response.content
        if not pcm:
            return 0.0
        for offset in range(0, len(pcm), _RAW_CHUNK_BYTES):
            await browser_ws.send_bytes(pcm[offset : offset + _RAW_CHUNK_BYTES])
        await browser_ws.send_json({"type": "assistant-text", "text": words})
        return len(pcm) / (_SAMPLE_RATE * 2)
    except Exception as exc:
        _log("TTS", f"error: {exc}")
        try:
            await browser_ws.send_json({"type": "assistant-text", "text": words})
        except Exception:
            pass
        return 0.0


async def _open_call_conversation(
    browser_ws: Any, *, caller_name: str = DEFAULT_CALLER_NAME
) -> None:
    """Ask the model to initiate a newly connected call in its own words."""
    opening = await plan_call_opening(caller_name=caller_name)
    if opening:
        await _speak_text(browser_ws, opening)


async def _route_and_respond(
    transcript: str, browser_ws: Any, *, caller_name: str = DEFAULT_CALLER_NAME
) -> None:
    """Run the call control plane and voice its result.

    Only model-authored replies are spoken.  There is deliberately no canned
    “thinking” clip, so the caller never hears a script overlap a real answer.
    """
    try:
        decision = await plan_call_turn(transcript, caller_name=caller_name)
    except Exception as exc:
        _log("PLAN", f"planner task failed: {exc}")
        decision = None

    if decision is None:
        await _speak_text(browser_ws, "我刚刚没有接稳这句话，可以再说一遍吗？")
        return

    reply = decision.reply
    if decision.action == "dispatch":
        try:
            await browser_ws.send_json(
                {"type": "assistant-state", "state": "dispatching", "text": "Connecting the CEO team…"}
            )
            result = await dispatch_to_engineer(decision.task)
            await browser_ws.send_json(
                {"type": "dispatched", "task": decision.task, **result}
            )
            if result.get("status") == "dispatched":
                reply = reply or (
                    "明白，我已经把这件事交给 CEO 团队。"
                    "你可以继续补充细节或验收标准。"
                )
            else:
                reply = "我刚才没能把任务交出去，我们可以再试一次。"
        except Exception as exc:
            _log("DISPATCH", f"call handoff failed: {exc}")
            reply = "我刚才没能把任务交出去，我们可以再试一次。"
    elif decision.action == "end_call":
        reply = reply or "好，那我先挂了。下次见。"

    duration = await _speak_text(browser_ws, reply)
    try:
        if decision.action == "end_call":
            await browser_ws.send_json(
                {
                    "type": "end-call",
                    "delay_ms": max(700, int(duration * 1000) + 180),
                    "reason": "caller-goodbye",
                }
            )
        else:
            await browser_ws.send_json(
                {
                    "type": "assistant-state",
                    "state": "listening",
                    "text": "Yellow Sheep is listening",
                }
            )
    except Exception:
        pass


# ── WebSocket route ──────────────────────────────────────────────────────────────


@router.websocket("/api/call")
async def voice_call(
    websocket: WebSocket,
    token: str | None = Query(None),
    caller_name: str | None = Query(None),
):
    """Full-duplex WebSocket voice bridge between the browser and StepFun realtime.

    *Browser → StepFun*: binary PCM16 frames are base64-encoded and forwarded as
    ``input_audio_buffer.append`` events.
    *StepFun → Browser*: ``response.audio.delta`` base64 audio chunks are decoded
    and forwarded to the browser as raw binary PCM16 frames.

    Query param ``?token=`` must match ``CV_API_TOKEN`` (constant-time HMAC
    compare) whenever the env var is set; otherwise the connection is rejected
    immediately with close code 4401.
    """
    # ── Auth gate ──────────────────────────────────────────────────────────
    await websocket.accept()
    caller_name = normalize_caller_name(caller_name or DEFAULT_CALLER_NAME)

    if CV_API_TOKEN:
        ok = is_valid_token(token)
        if not ok:
            try:
                first = await asyncio.wait_for(websocket.receive_text(), timeout=5)
                provided = (json.loads(first) or {}).get("token", "")
                ok = is_valid_token(provided)
            except Exception:
                ok = False
        if not ok:
            _log("AUTH", "Invalid/missing token — closing 4401")
            await websocket.close(code=4401, reason="Invalid token")
            return
        _log("AUTH", "Token validated OK")
    else:
        _log("AUTH", "CV_API_TOKEN not set — connection open without auth")

    # ── Connect to StepFun ───────────────────────────────────────────────────────
    if not STEPFUN_API_KEY:
        _log("SF", "STEPFUN_API_KEY not set — closing connection with 5001")
        await websocket.close(code=5001, reason="STEPFUN_API_KEY not configured")
        return

    try:
        import websockets as _ws_lib  # noqa: WPS433
    except ImportError:
        _log("SF", "websockets package not installed — cannot bridge to StepFun")
        await websocket.close(
            code=5002, reason="Server misconfiguration: websockets not installed"
        )
        return

    stepfun_headers = {
        "Authorization": f"Bearer {STEPFUN_API_KEY}",
        "X-Trace-Id": str(uuid.uuid4()),
    }

    step_ws: Any = None
    try:
        # websockets >=14 renamed extra_headers → additional_headers; support both.
        try:
            step_ws = await _ws_lib.connect(
                STEPFUN_WS_URL, additional_headers=stepfun_headers
            )
        except TypeError:
            step_ws = await _ws_lib.connect(
                STEPFUN_WS_URL, extra_headers=stepfun_headers
            )
    except Exception as exc:
        _log("SF", f"Failed to connect to StepFun: {exc}")
        await websocket.close(
            code=5003,
            reason=f"StepFun connection failed: {type(exc).__name__}",
        )
        return

    _log("SF", "Connected to StepFun realtime endpoint")

    # ── Send session.update immediately after connect ────────────────────────────
    session_event_id = str(uuid.uuid4())
    try:
        await step_ws.send(json.dumps(_client_session_update(session_event_id)))
    except Exception as exc:
        _log("SF", f"Failed to send session.update: {exc}")
        await _safe_close(step_ws)
        await websocket.close(
            code=5004, reason="Failed to initialise StepFun session"
        )
        return

    _log("SF", f"session.update sent (event_id={session_event_id})")

    # The opening is model-authored from the fresh-call context above, never a
    # prerecorded script.  It is sent before normal audio pumps take over so
    # Yellow Sheep politely starts the conversation after the connection.
    try:
        await _open_call_conversation(websocket, caller_name=caller_name)
    except Exception as exc:
        _log("OPENING", f"opening turn failed: {exc}")

    # ── Run two pump coroutines ─────────────────────────────────────────────────
    #   browser → StepFun   (binary PCM → base64 JSON)
    #   StepFun → browser   (base64 JSON → binary PCM)
    try:
        await asyncio.gather(
            _pump_browser_to_stepfun(websocket, step_ws),
            _pump_stepfun_to_browser(step_ws, websocket, caller_name=caller_name),
        )
    except asyncio.CancelledError:
        pass
    finally:
        _log("SF", "Bridge shutting down — closing StepFun connection")
        await _safe_close(step_ws)


# ── Pump: browser → StepFun ──────────────────────────────────────────────────────


async def _pump_browser_to_stepfun(browser_ws: WebSocket, step_ws: Any) -> None:
    """Read binary PCM16 frames from the browser and relay them to StepFun as
    base64-encoded ``input_audio_buffer.append`` events."""
    audio_accum = bytearray()

    while True:
        try:
            msg = await browser_ws.receive()
        except WebSocketDisconnect:
            _log("IN", "Browser disconnected")
            break
        except Exception as exc:
            _log("IN", f"Browser receive error: {exc}")
            break

        if msg["type"] == "websocket.disconnect":
            _log("IN", "Browser disconnect signal received")
            break

        data: bytes | None = msg.get("bytes")
        if data is None:
            _log("IN", f"Ignoring text message from browser: {msg.get('text', '')[:80]}")
            continue

        if len(data) > _MAX_WS_MESSAGE_BYTES:
            _log("IN", f"Oversized binary message ({len(data)} bytes) — skipping")
            continue

        audio_accum.extend(data)

        while len(audio_accum) >= _RAW_CHUNK_BYTES:
            chunk = audio_accum[:_RAW_CHUNK_BYTES]
            del audio_accum[:_RAW_CHUNK_BYTES]
            b64 = base64.b64encode(chunk).decode("ascii")
            evt_id = str(uuid.uuid4())
            try:
                await step_ws.send(json.dumps(_client_audio_append(evt_id, b64)))
            except Exception as exc:
                _log("IN", f"StepFun send error: {exc}")
                return


# ── Pump: StepFun → browser ─────────────────────────────────────────────────────


async def _pump_stepfun_to_browser(
    step_ws: Any,
    browser_ws: WebSocket,
    *,
    caller_name: str = DEFAULT_CALLER_NAME,
) -> None:
    """Receive StepFun server events and relay audio deltas to the browser as raw
    binary PCM16 frames.

    Also detects barge-in: if a ``speech_started`` event arrives while we are
    buffering output audio, the buffer is flushed so the new user speech takes
    priority immediately.
    """
    audio_accum = bytearray()
    active_turn: asyncio.Task[None] | None = None

    try:
        while True:
            try:
                raw = await step_ws.recv()
            except Exception as exc:
                _log("OUT", f"StepFun receive error: {exc}")
                break

            if not isinstance(raw, str):
                _log("OUT", "Unexpected binary frame from StepFun — skipping")
                continue

            try:
                evt: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                _log("OUT", f"Non-JSON message from StepFun: {raw[:120]!r}")
                continue

            evt_type: str = evt.get("type", "")

            # ── Audio delta ─────────────────────────────────────────────────────
            if evt_type == "response.audio.delta":
                b64_delta: str | None = evt.get("delta")
                if b64_delta:
                    try:
                        raw_bytes = base64.b64decode(b64_delta)
                        audio_accum.extend(raw_bytes)

                        while len(audio_accum) >= _RAW_CHUNK_BYTES:
                            frame = audio_accum[:_RAW_CHUNK_BYTES]
                            del audio_accum[:_RAW_CHUNK_BYTES]
                            try:
                                await browser_ws.send_bytes(frame)
                            except Exception as exc:
                                _log("OUT", f"Browser send error: {exc}")
                                return
                    except Exception as exc:
                        _log("OUT", f"Audio decode error: {exc}")

            # ── Barge-in ─────────────────────────────────────────────────────────
            elif evt_type == "input_audio_buffer.speech_started":
                _log("OUT", "Barge-in detected — flushing output buffer")
                audio_accum.clear()
                if active_turn and not active_turn.done():
                    active_turn.cancel()
                try:
                    await browser_ws.send_json({"type": "barge-in", "state": "speech-started"})
                except Exception:
                    pass

            elif evt_type == "input_audio_buffer.speech_stopped":
                _log("OUT", "Caller finished speaking")
                try:
                    await browser_ws.send_json({"type": "call-state", "state": "speech-stopped"})
                except Exception:
                    pass
                # With create_response=false, VAD marks the turn boundary but the
                # bridge must commit the audio so ASR emits a final transcript.
                try:
                    await step_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                except Exception as exc:
                    _log("OUT", f"audio commit failed: {exc}")

            # ── Response done ────────────────────────────────────────────────────
            elif evt_type == "response.done":
                _log("OUT", "response.done — flushing remaining audio")
                if audio_accum:
                    try:
                        await browser_ws.send_bytes(bytes(audio_accum))
                    except Exception as exc:
                        _log("OUT", f"Browser tail-send error: {exc}")
                    audio_accum.clear()
                try:
                    await browser_ws.send_json({"type": "response-done"})
                except Exception:
                    pass

            # ── Transcript complete → text reasoning + tools → TTS ──────────────
            elif evt_type == "conversation.item.input_audio_transcription.completed":
                tx = evt.get("transcript", "") or ""
                _log("OUT", f"user transcript received ({len(tx)} chars)")
                if tx.strip():
                    try:
                        await browser_ws.send_json(
                            {"type": "transcript", "speaker": caller_name, "text": tx}
                        )
                    except Exception:
                        pass
                    if active_turn and not active_turn.done():
                        active_turn.cancel()
                    active_turn = asyncio.create_task(
                        _route_and_respond(tx, browser_ws, caller_name=caller_name)
                    )

            # ── Session confirmed ───────────────────────────────────────────────
            elif evt_type == "session.updated":
                _log("OUT", "Session confirmed by StepFun")

            # ── Error from StepFun ──────────────────────────────────────────────
            elif evt_type == "error":
                err_msg = evt.get("error", evt)
                _log("OUT", f"StepFun error event: {err_msg}")

            # ── Other events (logged only) ──────────────────────────────────────
            else:
                _log("OUT", f"Unhandled StepFun event: {evt_type}")
    finally:
        if active_turn and not active_turn.done():
            active_turn.cancel()


# ── Cleanup helpers ──────────────────────────────────────────────────────────────


async def _safe_close(conn: Any) -> None:
    """Close a websocket connection if it is still open. Silently ignores errors."""
    try:
        if getattr(conn, "state", None) in (None, "open", "CONNECTING"):
            await conn.close()
    except Exception:
        pass
