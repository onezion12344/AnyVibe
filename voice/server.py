"""voice/server.py — StepFun Realtime WebSocket voice server for Coding Vibe.

Replaces the Pipecat WebRTC approach with a direct WebSocket relay:
  Browser <--WebSocket--> Server <--WebSocket (StepFun Realtime API)--> StepFun

Protocol: JSON events over WebSocket; audio as base64 PCM16 mono 24kHz.
Auth: x-cv-token header or ?token= query param (capability token / shared secret).

Run:
    cd /Users/onezion12344/Projects/adv-x/coding-vibe/coding-vibe-qoder
    set -a; source .env; set +a
    /Users/onezion12344/miniforge3/bin/python3 voice/server.py
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from voice.telephony_audio import pcm24k_to_ulaw8k, ulaw8k_to_pcm24k

# ── Project path ─────────────────────────────────────────────────────────────────
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_WORKTREE_ROOT))

from web.engineer_dispatch import CS_VOICE_PERSONA

# ── Config ────────────────────────────────────────────────────────────────────────
_HOST = os.environ.get("CV_PIPECAT_HOST", "127.0.0.1")
_PORT = int(os.environ.get("CV_PIPECAT_PORT", "7860"))
STEPFUN_API_KEY = os.environ.get("STEPFUN_API_KEY", "")
STEPFUN_REALTIME_URL = "wss://api.stepfun.com/v1/realtime"
REALTIME_MODEL = os.environ.get("CV_REALTIME_MODEL", "step-1o-audio")

# Public wss:// URL Twilio dials into (tunnel/ingress → this server's /twilio-stream)
PUBLIC_WSS = os.environ.get("CV_PUBLIC_WSS", "wss://twilio.onezion.top/twilio-stream")

# Cap concurrent Twilio media streams so a flood of connections can't open
# unbounded (paid) StepFun sessions. Each accepted stream opens one StepFun WS.
_MAX_TWILIO_STREAMS = int(os.environ.get("CV_MAX_TWILIO_STREAMS", "4"))
_active_twilio_streams = 0

# Twilio auth token — used to validate X-Twilio-Signature on /twilio-voice so
# only genuine Twilio requests get TwiML (and the minted capability token).
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")

# StepFun Realtime session config — kept verbatim in sync with the browser
# frontend (voice/frontend/index.html session.update): same instructions, voice,
# audio formats, transcription and turn_detection so phone and web behave alike.
STEPFUN_SESSION = {
    "type": "session.update",
    "session": {
        "model": REALTIME_MODEL,
        "modalities": ["text", "audio"],
        "instructions": CS_VOICE_PERSONA,
        "voice": "alloy",
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "input_audio_transcription": {
            "model": "step-asr"
        },
        "turn_detection": {
            "type": "server_vad",
        },
    },
}

# Auth: reuse existing capability token system from the original server.py
CV_API_TOKEN = os.environ.get("CV_API_TOKEN", "")
_CAP_TTL = float(os.environ.get("CV_OFFER_CAP_TTL", "300"))  # 5 minutes
_capabilities: dict[str, float] = {}

# Frontend static files
_FRONTEND_DIR = Path(__file__).parent / "frontend"

# ── Capability tokens ────────────────────────────────────────────────────────────


def _mint_capability() -> str:
    """Create a short-lived capability token, valid for _CAP_TTL seconds."""
    now = time.monotonic()
    # Opportunistically evict expired tokens
    for tok in [t for t, exp in _capabilities.items() if exp <= now]:
        _capabilities.pop(tok, None)
    token = secrets.token_urlsafe(32)
    _capabilities[token] = now + _CAP_TTL
    return token


def _check_token(token: str) -> bool:
    """Validate auth token: long-lived CV_API_TOKEN or short-lived capability."""
    if not CV_API_TOKEN:
        return True  # dev mode — no auth required
    if not token:
        return False
    if hmac.compare_digest(token, CV_API_TOKEN):
        return True
    exp = _capabilities.get(token)
    return exp is not None and exp > time.monotonic()


# ── App ──────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Coding Vibe StepFun Realtime Voice Server")

# Serve node_modules for any JS dependencies
_NM = _FRONTEND_DIR / "node_modules"
if _NM.exists():
    app.mount("/node_modules", StaticFiles(directory=str(_NM)), name="node_modules")


# ── Root → client page ───────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def root():
    """Serve the StepFun realtime voice frontend with injected capability token."""
    index = _FRONTEND_DIR / "index.html"
    if not index.exists():
        return JSONResponse(
            {"status": "Coding Vibe StepFun Realtime server", "port": _PORT}
        )
    html = index.read_text(encoding="utf-8")
    # Inject a short-lived capability token when bound to loopback with auth enabled
    cap = _mint_capability() if (CV_API_TOKEN and _HOST == "127.0.0.1") else ""
    html = html.replace("__CV_OFFER_TOKEN__", cap)
    return HTMLResponse(html)


# ── WebSocket relay endpoint ─────────────────────────────────────────────────────


@app.websocket("/ws")
async def ws_relay(ws: WebSocket):
    """WebSocket relay: browser ↔ StepFun Realtime API.

    Authenticates via x-cv-token header or ?token= query param (capability token
    system reused from the original server.py). Opens a connection to the StepFun
    Realtime WebSocket and relays JSON messages bidirectionally.
    """
    # Extract auth token from query params or headers
    token = (
        ws.query_params.get("token") or ws.headers.get("x-cv-token") or ""
    ).strip()

    if not _check_token(token):
        await ws.close(code=4001, reason="unauthorized")
        return

    await ws.accept()
    print("[server] WebSocket client connected", flush=True)

    stepfun_ws = None

    try:
        # ── Connect to StepFun Realtime API ───────────────────────────────────
        stepfun_ws = await websockets.connect(
            f"{STEPFUN_REALTIME_URL}?model={REALTIME_MODEL}",
            additional_headers={"Authorization": f"Bearer {STEPFUN_API_KEY}"},
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        )
        print(
            f"[server] Connected to StepFun Realtime (model={REALTIME_MODEL})",
            flush=True,
        )

        # ── Bidirectional relay ───────────────────────────────────────────────

        async def browser_to_stepfun():
            """Read JSON from browser WebSocket, forward to StepFun."""
            try:
                while True:
                    data = await ws.receive_text()
                    # Quick validation: ensure parseable JSON before forwarding
                    try:
                        json.loads(data)
                    except json.JSONDecodeError:
                        print(
                            "[server] Browser sent invalid JSON, dropping frame",
                            flush=True,
                        )
                        continue
                    await stepfun_ws.send(data)
            except WebSocketDisconnect:
                print("[server] Browser disconnected", flush=True)
            except Exception as exc:
                print(f"[server] browser→stepfun: {exc}", flush=True)

        async def stepfun_to_browser():
            """Read JSON from StepFun WebSocket, forward to browser."""
            try:
                async for message in stepfun_ws:
                    try:
                        await ws.send_text(message)
                    except Exception:
                        # Browser likely disconnected — stop forwarding
                        break
            except websockets.exceptions.ConnectionClosed as exc:
                print(f"[server] StepFun connection closed (code={exc.code})", flush=True)
            except Exception as exc:
                print(f"[server] stepfun→browser: {exc}", flush=True)

        # Run both relay directions concurrently
        tasks = [
            asyncio.create_task(browser_to_stepfun()),
            asyncio.create_task(stepfun_to_browser()),
        ]

        # Wait for either direction to complete, then cancel the other
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Surface any unexpected exceptions from completed tasks
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                print(f"[server] relay task error: {exc}", flush=True)

    except websockets.exceptions.InvalidHandshake as exc:
        print(
            f"[server] StepFun auth failed (check STEPFUN_API_KEY): {exc}",
            flush=True,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        print(f"[server] StepFun connection timeout: {exc}", flush=True)
    except Exception as exc:
        print(f"[server] StepFun connection error: {exc!r}", flush=True)
    finally:
        # ── Cleanup ──────────────────────────────────────────────────────────
        if stepfun_ws is not None:
            try:
                await stepfun_ws.close()
            except Exception:
                pass
        try:
            await ws.close()
        except Exception:
            pass
        print("[server] WebSocket session ended", flush=True)


# ── Twilio telephony bridge ────────────────────────────────────────────────────


@app.post("/twilio-voice")
async def twilio_voice(request: Request):
    """Return TwiML that connects the incoming call to the StepFun bridge.

    Twilio fetches this when a call reaches the configured number; the returned
    <Connect><Stream> hands the call's media to our /twilio-stream WebSocket.
    """
    # (1) Authenticate the request actually came from Twilio (best-effort:
    #     needs TWILIO_AUTH_TOKEN + the twilio SDK). Rejects forged callers who
    #     would otherwise harvest the capability token from the TwiML.
    if TWILIO_AUTH_TOKEN:
        try:
            from twilio.request_validator import RequestValidator

            validator = RequestValidator(TWILIO_AUTH_TOKEN)
            form = dict(await request.form())
            # Behind a tunnel the app sees localhost, so trust forwarded
            # proto/host (the values Twilio actually signed against).
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = (
                request.headers.get("x-forwarded-host")
                or request.headers.get("host")
                or request.url.netloc
            )
            public_url = f"{proto}://{host}{request.url.path}"
            sig = request.headers.get("X-Twilio-Signature", "")
            if not validator.validate(public_url, form, sig):
                return Response(content="forbidden", status_code=403)
        except ImportError:
            print("[twilio] twilio SDK missing — skipping signature check", flush=True)

    # (2) Embed a SHORT-LIVED capability token (never the long-lived secret) so
    #     a logged TwiML URL only leaks a value that expires in _CAP_TTL.
    stream_url = PUBLIC_WSS
    if CV_API_TOKEN:
        cap = _mint_capability()
        sep = "&amp;" if "?" in PUBLIC_WSS else "?"
        stream_url = f"{PUBLIC_WSS}{sep}token={cap}"
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Connect><Stream url="{stream_url}" /></Connect></Response>'
    )
    return Response(content=twiml, media_type="text/xml")


@app.websocket("/twilio-stream")
async def twilio_stream(ws: WebSocket):
    """Bridge Twilio Media Streams ↔ StepFun Realtime API.

    Twilio speaks 8kHz μ-law over its Media Streams protocol; StepFun speaks
    base64 PCM16 mono 24kHz. We transcode in both directions (see
    voice.telephony_audio) and keep independent resampler state per direction.
    """
    # Authenticate before doing any work: the wss URL is public, and each
    # accepted stream opens a (paid) StepFun session. Reject unauthorized or
    # over-cap connections without accepting — matches the /ws relay pattern.
    global _active_twilio_streams
    token = (ws.query_params.get("token") or ws.headers.get("x-cv-token") or "").strip()
    if not _check_token(token):
        await ws.close(code=4001, reason="unauthorized")
        return
    if _active_twilio_streams >= _MAX_TWILIO_STREAMS:
        print("[twilio] rejecting stream — concurrent cap reached", flush=True)
        await ws.close(code=4429, reason="too many streams")
        return

    _active_twilio_streams += 1
    stepfun_ws = None
    stream_sid: str | None = None
    in_state = None   # Twilio → StepFun resampler state (8k → 24k)
    out_state = None  # StepFun → Twilio resampler state (24k → 8k)

    try:
        # accept() inside the try so the counter always decrements in finally,
        # even if the handshake itself fails (otherwise the cap slot leaks).
        await ws.accept()
        print("[twilio] Media Stream client connected", flush=True)

        # ── Connect to StepFun Realtime API (same params as /ws relay) ────────
        stepfun_ws = await websockets.connect(
            f"{STEPFUN_REALTIME_URL}?model={REALTIME_MODEL}",
            additional_headers={"Authorization": f"Bearer {STEPFUN_API_KEY}"},
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        )
        print(
            f"[twilio] Connected to StepFun Realtime (model={REALTIME_MODEL})",
            flush=True,
        )

        # Configure the session, then kick off the greeting turn
        await stepfun_ws.send(json.dumps(STEPFUN_SESSION))
        await stepfun_ws.send(json.dumps({"type": "response.create"}))

        # ── Bidirectional bridge ──────────────────────────────────────────────

        async def twilio_to_stepfun():
            """Read Twilio Media Stream frames, transcode μ-law→PCM24k, forward."""
            nonlocal stream_sid, in_state
            try:
                while True:
                    data = await ws.receive_text()
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    event = evt.get("event")
                    if event == "start":
                        stream_sid = evt.get("start", {}).get("streamSid") or evt.get(
                            "streamSid"
                        )
                        print(f"[twilio] stream started (sid={stream_sid})", flush=True)
                    elif event == "media":
                        payload = evt.get("media", {}).get("payload")
                        if not payload:
                            continue
                        ulaw = base64.b64decode(payload)
                        pcm24k, in_state = ulaw8k_to_pcm24k(ulaw, in_state)
                        await stepfun_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": base64.b64encode(pcm24k).decode("ascii"),
                                }
                            )
                        )
                    elif event == "stop":
                        print("[twilio] stream stopped", flush=True)
                        break
            except WebSocketDisconnect:
                print("[twilio] Twilio disconnected", flush=True)
            except Exception as exc:
                print(f"[twilio] twilio→stepfun: {exc}", flush=True)

        async def stepfun_to_twilio():
            """Read StepFun events, transcode PCM24k→μ-law, push to Twilio."""
            nonlocal out_state
            try:
                async for message in stepfun_ws:
                    try:
                        msg = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    mtype = msg.get("type")
                    if mtype == "response.audio.delta":
                        delta = msg.get("delta")
                        if not delta or stream_sid is None:
                            continue
                        pcm24k = base64.b64decode(delta)
                        ulaw, out_state = pcm24k_to_ulaw8k(pcm24k, out_state)
                        await ws.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {
                                        "payload": base64.b64encode(ulaw).decode(
                                            "ascii"
                                        )
                                    },
                                }
                            )
                        )
                    elif mtype == "input_audio_buffer.speech_started":
                        # Barge-in: clear any audio already queued on Twilio's side
                        if stream_sid is not None:
                            await ws.send_text(
                                json.dumps(
                                    {"event": "clear", "streamSid": stream_sid}
                                )
                            )
                    elif mtype == "input_audio_buffer.speech_stopped":
                        # Server VAD end-of-turn → commit and request a response
                        await stepfun_ws.send(
                            json.dumps({"type": "input_audio_buffer.commit"})
                        )
                        await stepfun_ws.send(
                            json.dumps({"type": "response.create"})
                        )
            except websockets.exceptions.ConnectionClosed as exc:
                print(
                    f"[twilio] StepFun connection closed (code={exc.code})",
                    flush=True,
                )
            except Exception as exc:
                print(f"[twilio] stepfun→twilio: {exc}", flush=True)

        tasks = [
            asyncio.create_task(twilio_to_stepfun()),
            asyncio.create_task(stepfun_to_twilio()),
        ]

        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                print(f"[twilio] bridge task error: {exc}", flush=True)

    except websockets.exceptions.InvalidHandshake as exc:
        print(
            f"[twilio] StepFun auth failed (check STEPFUN_API_KEY): {exc}",
            flush=True,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        print(f"[twilio] StepFun connection timeout: {exc}", flush=True)
    except Exception as exc:
        print(f"[twilio] StepFun connection error: {exc!r}", flush=True)
    finally:
        _active_twilio_streams -= 1
        if stepfun_ws is not None:
            try:
                await stepfun_ws.close()
            except Exception:
                pass
        try:
            await ws.close()
        except Exception:
            pass
        print("[twilio] Media Stream session ended", flush=True)


# ── Entry point ──────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn

    if not STEPFUN_API_KEY:
        print("\n[FATAL] STEPFUN_API_KEY is not set.", flush=True)
        print(
            "Run: set -a; source .env; set +a && "
            "/Users/onezion12344/miniforge3/bin/python3 voice/server.py",
            flush=True,
        )
        sys.exit(1)

    print(
        f"[server] Coding Vibe StepFun Realtime voice server → "
        f"http://{_HOST}:{_PORT}",
        flush=True,
    )
    uvicorn.run(app, host=_HOST, port=_PORT)
