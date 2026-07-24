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
import hashlib
import hmac
import json
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

# ── Config ────────────────────────────────────────────────────────────────────────

router = APIRouter()

# ── Shared dispatch config (imported from engineer_dispatch) ─────────────────────
# All backend-agnostic logic lives in web/engineer_dispatch.py.
from web.engineer_dispatch import (  # noqa: E402
    STEPFUN_BASE_URL,
    CS_BRAIN_MODEL,
    CV_API_TOKEN,
    STEPFUN_API_KEY,      # re-exported for StepFun WS auth
    TOOLS,
    classify_and_dispatch,
    dispatch_to_engineer,
)

# Audio constants (PCM16 / 24 kHz / mono) — StepFun transport-specific
_SAMPLE_RATE = 24_000
_FRAMES_PER_CHUNK = 480  # 20 ms
_RAW_CHUNK_BYTES = _FRAMES_PER_CHUNK * 2  # 960 bytes per 20 ms chunk

# StepFun WebSocket URL — transport constant
STEPFUN_WS_URL = "wss://api.stepfun.com/v1/realtime?model=stepaudio-2.5-realtime"

# CS "receptionist" VOICE persona. The realtime model ONLY talks — it does NOT
# decide dispatch (its audio tool-calling is unreliable). A separate text brain
# (_classify_and_dispatch on the transcript) makes the dispatch decision.
_SYSTEM_INSTRUCTIONS = (
    "你是 Coding Vibe 工作室的电话接线员（CS）。说话简短、自然、口语化，像在打电话。"
    "如果来电者想做/写/改某个代码或功能，就热情、简短地回应：『好的，我马上安排工程师处理，"
    "忙完打给你哈。』然后就好——不要自己写代码、不要解释实现细节。"
    "如果只是闲聊或问进度，就自然地聊。始终友好。"
)

# Maximum incoming message size (bytes) — defend against memory bombs
_MAX_WS_MESSAGE_BYTES = 1 << 20  # 1 MiB


# ── StepFun-realtime-specific classify + dispatch ─────────────────────────────────
# _classify_and_dispatch from engineer_dispatch is backend-agnostic (calls
# on_dispatched callback).  The StepFun bridge needs a thin wrapper that also
# sends the dispatched event back to the browser WebSocket — that's done here.


async def _classify_and_dispatch(transcript: str, browser_ws: Any) -> None:
    """Decide — via the text CS brain (reliable tool-calling) — whether the user's
    spoken turn is a coding request, and if so dispatch it.

    Wraps the shared :func:`~web.engineer_dispatch.classify_and_dispatch`,
    passing a StepFun-bridge-specific callback that relays dispatched events
    back to the browser WebSocket.
    """
    text = (transcript or "").strip()
    if not text:
        return

    def _on_dispatched(info: dict[str, Any]) -> None:
        """Fire-and-forget: push dispatched event to the browser WS."""
        try:
            task = (info or {}).get("task", "")
            asyncio.get_running_loop().create_task(
                browser_ws.send_json({"type": "dispatched", "task": task, **(info or {})})
            )
        except Exception:
            pass

    # Fire-and-forget so we never block the audio pump loop.
    try:
        asyncio.create_task(classify_and_dispatch(text, on_dispatched=_on_dispatched))
    except Exception as exc:
        _log("CLASSIFY", f"schedule error: {exc}")


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
            "turn_detection": {
                "type": "server_vad",
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
                "create_response": True,
            },
        },
    }


def _client_audio_append(event_id: str, b64_audio: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "type": "input_audio_buffer.append",
        "audio": b64_audio,
    }


# ── WebSocket route ──────────────────────────────────────────────────────────────


@router.websocket("/api/call")
async def voice_call(websocket: WebSocket, token: str | None = Query(None)):
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

    if CV_API_TOKEN:
        ok = bool(token) and hmac.compare_digest(token, CV_API_TOKEN)
        if not ok:
            try:
                first = await asyncio.wait_for(websocket.receive_text(), timeout=5)
                provided = (json.loads(first) or {}).get("token", "")
                ok = bool(provided) and hmac.compare_digest(provided, CV_API_TOKEN)
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

    # ── Run two pump coroutines ─────────────────────────────────────────────────
    #   browser → StepFun   (binary PCM → base64 JSON)
    #   StepFun → browser   (base64 JSON → binary PCM)
    try:
        await asyncio.gather(
            _pump_browser_to_stepfun(websocket, step_ws),
            _pump_stepfun_to_browser(step_ws, websocket),
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


async def _pump_stepfun_to_browser(step_ws: Any, browser_ws: WebSocket) -> None:
    """Receive StepFun server events and relay audio deltas to the browser as raw
    binary PCM16 frames.

    Also detects barge-in: if a ``speech_started`` event arrives while we are
    buffering output audio, the buffer is flushed so the new user speech takes
    priority immediately.
    """
    audio_accum = bytearray()

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

        # ── Audio delta ─────────────────────────────────────────────────────────
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

        # ── Barge-in ─────────────────────────────────────────────────────────────
        elif evt_type == "input_audio_buffer.speech_started":
            _log("OUT", "Barge-in detected — flushing output buffer")
            audio_accum.clear()
            try:
                await browser_ws.send_json({"type": "barge-in"})
            except Exception:
                pass

        # ── Response done ────────────────────────────────────────────────────────
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

        # ── Function call: CS dispatched to engineer via realtime tool-calling ────
        elif evt_type == "response.function_call_arguments.done":
            call_id = evt.get("call_id", "")
            try:
                args = json.loads(evt.get("arguments", "") or "{}")
            except Exception:
                args = {}
            task = (args.get("task") or "").strip()
            thash = hashlib.sha256(task.encode()).hexdigest()[:8] if task else "-"
            _log("OUT", f"CS dispatched via tool (task#{thash})")
            ack: dict[str, Any] = {"status": "no-op"}
            if task.startswith("-"):
                _log("OUT", f"Rejected task starting with '-' (task#{thash})")
                ack = {"status": "error", "error": "Invalid task"}
            elif task:
                try:
                    ack = await dispatch_to_engineer(task)
                except Exception as exc:
                    ack = {"status": "error", "error": str(exc)}
                try:
                    await browser_ws.send_json({"type": "dispatched", "task": task, **ack})
                except Exception:
                    pass
            # Feed the tool result back so the CS voices a confirmation.
            try:
                await step_ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(ack, ensure_ascii=False),
                    },
                }))
                await step_ws.send(json.dumps({"type": "response.create"}))
            except Exception as exc:
                _log("OUT", f"function_call_output send failed: {exc}")

        # ── Transcript complete → classify via text brain ────────────────────────
        elif evt_type == "conversation.item.input_audio_transcription.completed":
            tx = evt.get("transcript", "") or ""
            # Content redacted by default (PII); set CV_LOG_TRANSCRIPTS=1 for local debug.
            if os.environ.get("CV_LOG_TRANSCRIPTS") == "1":
                _log("OUT", f"user transcript: {tx}")
            else:
                _log("OUT", f"user transcript received ({len(tx)} chars)")
            asyncio.create_task(_classify_and_dispatch(tx, browser_ws))

        # ── Session confirmed ───────────────────────────────────────────────────
        elif evt_type == "session.updated":
            _log("OUT", "Session confirmed by StepFun")

        # ── Error from StepFun ──────────────────────────────────────────────────
        elif evt_type == "error":
            err_msg = evt.get("error", evt)
            _log("OUT", f"StepFun error event: {err_msg}")

        # ── Other events (logged only) ──────────────────────────────────────────
        else:
            _log("OUT", f"Unhandled StepFun event: {evt_type}")


# ── Cleanup helpers ──────────────────────────────────────────────────────────────


async def _safe_close(conn: Any) -> None:
    """Close a websocket connection if it is still open. Silently ignores errors."""
    try:
        if getattr(conn, "state", None) in (None, "open", "CONNECTING"):
            await conn.close()
    except Exception:
        pass
