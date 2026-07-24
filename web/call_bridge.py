"""web/call_bridge.py — StepFun Realtime voice bridge.

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

Tokens
  CV_API_TOKEN  – if set, required on the WS query string ?token= (constant-time
                  compare; close 4401 on mismatch).
  STEPFUN_API_KEY  – StepFun Bearer token (read from env).
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

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

# ── Config ────────────────────────────────────────────────────────────────────────

router = APIRouter()

STEPFUN_API_KEY: str = os.environ.get("STEPFUN_API_KEY", "")
STEPFUN_WS_URL = "wss://api.stepfun.com/v1/realtime?model=stepaudio-2.5-realtime"
CV_API_TOKEN: str = os.environ.get("CV_API_TOKEN", "")

# Audio constants (PCM16 / 24 kHz / mono)
_SAMPLE_RATE = 24_000
_FRAMES_PER_CHUNK = 480  # 20 ms
_RAW_CHUNK_BYTES = _FRAMES_PER_CHUNK * 2  # 960 bytes per 20 ms chunk

# CS "receptionist" system prompt — judges intent, dispatches coding work itself.
_SYSTEM_INSTRUCTIONS = (
    "你是 Coding Vibe 工作室的电话接线员（CS）。你说话简短、自然、友好，像在打电话。"
    "你要自己判断来电者的意图：如果只是闲聊、问候或询问进度，就正常对话，不要调用工具。"
    "但只要来电者表达出要『做/写/修/搭建/实现某个东西』这类编程或工程需求，你就必须调用 "
    "dispatch_to_engineer 工具，把需求整理成一句清晰的任务描述交给工程团队——不要自己写代码。"
    "调用工具后，用一句话告诉来电者『已经交给工程师了，忙完我打给你』。始终乐于帮忙。"
)

# Backend the CS dispatches to. Real code-exec backends (claude-code/openopc) are
# OFF by default — enabling one is a deliberate, separately-gated decision:
# set CV_CALL_BACKEND=claude-code AND a token (the /api/call WS is token-gated).
# Without a token we force mock (fail-closed) so a spoken request can never reach
# an unauthenticated code-exec path.
_CALL_BACKEND = os.environ.get("CV_CALL_BACKEND", "mock")
if _CALL_BACKEND in ("claude-code", "openopc") and not CV_API_TOKEN:
    _CALL_BACKEND = "mock"
_CALL_REPO = os.environ.get("CV_DEMO_REPO", "/tmp/cv-demo")

# Tool the CS can call when it judges the caller wants engineering work done.
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_to_engineer",
            "description": (
                "Send a coding/engineering task to the engineering team. Call this "
                "whenever the caller wants something built, written, fixed, or implemented."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "A clear, self-contained description of the task to build.",
                    }
                },
                "required": ["task"],
            },
        },
    }
]

# Maximum incoming message size (bytes) — defend against memory bombs
_MAX_WS_MESSAGE_BYTES = 1 << 20  # 1 MiB


# ── Helper: tool-call stub ────────────────────────────────────────────────────────

async def dispatch_to_engineer(task: str) -> dict[str, Any]:
    """Dispatch a coding task to the engineer (CEO) backend.

    Spawns the task via the receptionist, records a delegation in shared state so
    the kanban shows it live, and RINGS the caller back when the engineer finishes
    (the agent-calls-you differentiator). Returns an ack dict for the CS to voice.
    """
    import time as _time
    from pathlib import Path as _Path
    try:
        from receptionist.core import Receptionist
        from receptionist.state import load_state, save_state
    except Exception as exc:
        _log("DISPATCH", f"receptionist import failed: {exc}")
        return {"status": "error", "error": str(exc)}

    try:
        _Path(_CALL_REPO).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    r = Receptionist()

    async def _on_complete(result: Any) -> None:
        # mark the delegation done, then ring the caller back
        try:
            st2 = load_state()
            for d in st2.get("delegations", []):
                if d.get("task_id") == tid:
                    d["status"] = "completed"
            save_state(st2)
        except Exception:
            pass
        try:
            from web.signaling import ring
            summary = (getattr(result, "summary", "") or "")[:80]
            await ring(reason=f"任务完成：{summary}", frm="CEO")
        except Exception as exc:
            _log("DISPATCH", f"ring failed: {exc}")

    tid = await r.dispatch_async(
        task,
        backend=_CALL_BACKEND,
        repo_path=_CALL_REPO,
        on_complete=_on_complete,
    )

    # record a delegation so /api/board shows it as in-progress right away
    try:
        st = load_state()
        st.setdefault("delegations", []).append({
            "task_id": tid,
            "description": task,
            "status": "running",
            "created_at": _time.time(),
        })
        save_state(st)
    except Exception as exc:
        _log("DISPATCH", f"state write failed: {exc}")

    thash = hashlib.sha256(task.encode()).hexdigest()[:8]
    _log("DISPATCH", f"dispatched task_id={tid} backend={_CALL_BACKEND} task#{thash}")
    return {"status": "dispatched", "task_id": tid, "backend": _CALL_BACKEND}


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
            "tools": _TOOLS,
            "tool_choice": "auto",
            "turn_detection": {
                "type": "server_vad",
                "prefix_padding_ms": 500,
                "silence_duration_ms": 100,
                "energy_awakeness_threshold": 2500,
            },
        },
    }


def _client_audio_append(event_id: str, b64_audio: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "type": "input_audio_buffer.append",
        "audio": b64_audio,
    }


# ── Helper: log to stdout with structured prefix ─────────────────────────────────

def _log(prefix: str, msg: str) -> None:
    print(f"[{prefix}] {msg}", flush=True)


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
    # Browsers can't set headers on a WebSocket, and a token in the URL leaks
    # into access logs. Accept it from the query (back-compat) OR, preferably,
    # as the first text message {"type":"auth","token":"..."} the client sends
    # right after the socket opens.
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
        await websocket.close(code=5002, reason="Server misconfiguration: websockets not installed")
        return

    stepfun_headers = {
        "Authorization": f"Bearer {STEPFUN_API_KEY}",
        "X-Trace-Id": str(uuid.uuid4()),
    }

    step_ws: Any = None
    try:
        # websockets >=14 renamed extra_headers → additional_headers; support both.
        try:
            step_ws = await _ws_lib.connect(STEPFUN_WS_URL, additional_headers=stepfun_headers)
        except TypeError:
            step_ws = await _ws_lib.connect(STEPFUN_WS_URL, extra_headers=stepfun_headers)
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
        await websocket.close(code=5004, reason="Failed to initialise StepFun session")
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
    audio_accum = bytearray()   # accumulate bytes until we have a full chunk

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
            # Ignore text messages from browser in the voice channel.
            # A future extension could use JSON text for control signals
            # (e.g. "end-of-utterance" or "hang-up").
            _log("IN", f"Ignoring text message from browser: {msg.get('text', '')[:80]}")
            continue

        if len(data) > _MAX_WS_MESSAGE_BYTES:
            _log("IN", f"Oversized binary message ({len(data)} bytes) — skipping")
            continue

        audio_accum.extend(data)

        # Drain full chunks
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
    audio_accum = bytearray()   # accumulate decoded chunks for partial sends

    while True:
        try:
            raw = await step_ws.recv()
        except Exception as exc:
            _log("OUT", f"StepFun receive error: {exc}")
            break

        if not isinstance(raw, str):
            _log("OUT", f"Unexpected binary frame from StepFun — skipping")
            continue

        try:
            evt: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            _log("OUT", f"Non-JSON message from StepFun: {raw[:120]!r}")
            continue

        evt_type: str = evt.get("type", "")

        # ── Audio delta: decode base64 → raw PCM → forward to browser ───────────
        if evt_type == "response.audio.delta":
            b64_delta: str | None = evt.get("delta")
            if b64_delta:
                try:
                    raw_bytes = base64.b64decode(b64_delta)
                    audio_accum.extend(raw_bytes)

                    # Flush in whole 960-byte frames so the browser sees
                    # exact 20-ms chunks.
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

        # ── Barge-in: user started speaking while AI was talking ─────────────────
        elif evt_type == "input_audio_buffer.speech_started":
            _log("OUT", "Barge-in detected — flushing output buffer")
            audio_accum.clear()
            try:
                await browser_ws.send_json({"type": "barge-in"})
            except Exception:
                pass

        # ── Response done ───────────────────────────────────────────────────────
        elif evt_type == "response.done":
            _log("OUT", "response.done — flushing remaining audio")
            # Flush any remaining bytes (< 960) so the browser gets the tail.
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

        # ── Function call: CS decided to dispatch to the engineer ───────────────
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
                # defense-in-depth vs argv flag smuggling (adapters also use `--`)
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
