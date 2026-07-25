"""voice/server.py — FastAPI server that hosts the Pipecat voice bot.

Pipecat 1.6.0 SmallWebRTCTransport requires an HTTP endpoint to exchange SDP
offers/answers with the browser.  This server provides that, plus serves the
browser client.

Endpoints:
  GET  /           → voice/client/index.html (browser client)
  POST /api/offer  → receive browser SDP offer, return SDP answer
  WS   /ws/signaling (optional) → data-channel messaging between browser and bot

Run
---
    /Users/onezion12344/miniforge3/bin/python3 voice/server.py

Then open http://localhost:7860 in a browser and click "Connect".
"""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import sys
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Project path ─────────────────────────────────────────────────────────────────
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_WORKTREE_ROOT))

# ── Frontend: serve the official Pipecat JS client from voice/frontend/ ────────────
_FRONTEND_DIR = Path(__file__).parent / "frontend"

# ── Pipecat imports ──────────────────────────────────────────────────────────────
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.base_transport import TransportParams

from voice.bot import main as bot_main  # noqa: E402 — local, after sys.path

# ── Config ────────────────────────────────────────────────────────────────────────

# Bind to loopback by default; binding to 0.0.0.0 must be an explicit opt-in.
_HOST = os.environ.get("CV_PIPECAT_HOST", "127.0.0.1")
_PORT = int(os.environ.get("CV_PIPECAT_PORT", "7860"))
_ICE_SERVERS = os.environ.get(
    "CV_PIPECAT_ICE_SERVERS",  # comma-separated STUN URLs
    "stun:stun.l.google.com:19302",
).split(",")

# Auth: /api/offer starts a bot that can reach dispatch → CEO (code exec), so it
# must be gated. Two accepted credentials:
#   • the long-lived shared secret CV_API_TOKEN (for API/programmatic clients),
#     via x-cv-token header, ?token= query, or body {"token": ...}; and
#   • a short-lived, single-use capability token minted per page load (see
#     _mint_capability). The browser page never receives the long-lived secret —
#     only an ephemeral capability that is consumed on first use and expires.
CV_API_TOKEN = os.environ.get("CV_API_TOKEN", "")
_DANGEROUS_BACKENDS = {"claude-code", "openopc"}
_MAX_CONNECTIONS = int(os.environ.get("CV_PIPECAT_MAX_CONN", "32"))

# Ephemeral single-use capability tokens: token -> expiry epoch seconds.
_CAP_TTL = float(os.environ.get("CV_OFFER_CAP_TTL", "300"))  # 5 minutes
_capabilities: dict[str, float] = {}


def _mint_capability() -> str:
    """Create a short-lived, single-use capability token for /api/offer."""
    now = time.monotonic()
    # Opportunistically evict expired tokens so the store can't grow unbounded.
    for tok in [t for t, exp in _capabilities.items() if exp <= now]:
        _capabilities.pop(tok, None)
    token = secrets.token_urlsafe(32)
    _capabilities[token] = now + _CAP_TTL
    return token


def _consume_capability(token: str) -> bool:
    """Validate and single-use-consume a capability token (constant-time-ish)."""
    if not token:
        return False
    exp = _capabilities.pop(token, None)  # pop = single use
    return exp is not None and exp > time.monotonic()


# ── In-memory connection registry ────────────────────────────────────────────────
# Each browser peer gets its own SmallWebRTCConnection + background bot task.
_connections: dict[str, SmallWebRTCConnection] = {}
_connection_lock = asyncio.Lock()


def _check_offer_auth(request: "Request", body: dict) -> bool:
    """Auth for /api/offer: long-lived shared secret OR single-use capability.

    Open only if no CV_API_TOKEN is configured (mock/dev). The capability path
    lets the browser authenticate without ever being handed the shared secret.
    """
    if not CV_API_TOKEN:
        return True
    tok = (
        request.headers.get("x-cv-token")
        or request.query_params.get("token")
        or (body.get("token") if isinstance(body, dict) else "")
        or ""
    )
    if not tok:
        return False
    # Long-lived shared secret (constant-time compare).
    if hmac.compare_digest(tok, CV_API_TOKEN):
        return True
    # Otherwise, a valid unexpired single-use capability token.
    return _consume_capability(tok)


# ── App ──────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Coding Vibe Pipecat Voice Server")

# Serve the official Pipecat frontend from voice/frontend/
# The frontend uses @pipecat-ai/client-js + @pipecat-ai/small-webrtc-transport
# and must be mounted to expose node_modules via /node_modules/ for ESM imports.
_FRONTEND_DIR = Path(__file__).parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/client", StaticFiles(directory=str(_FRONTEND_DIR)), name="frontend")
    # Also serve node_modules from the frontend dir so ESM module imports work
    _NM = _FRONTEND_DIR / "node_modules"
    if _NM.exists():
        app.mount("/node_modules", StaticFiles(directory=str(_NM)), name="node_modules")


# ── SDP offer/answer endpoint ───────────────────────────────────────────────────


@app.post("/api/offer")
async def handle_offer(request: Request) -> JSONResponse:
    """Receive a browser SDP offer, create a bot task, and return the SDP answer.

    The browser sends::

        POST /api/offer
        {"sdp": "<browser SDP offer>", "type": "offer"}

    We respond::

        {"sdp": "<bot SDP answer>", "type": "answer", "session_id": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # Auth gate — same token as the rest of the API (this endpoint reaches the CEO).
    if not _check_offer_auth(request, body):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    sdp: str = body.get("sdp", "")
    sdp_type: str = body.get("type", "offer")
    # Always server-generated — never trust a client-supplied session_id.
    session_id: str = str(uuid.uuid4())[:8]

    if not sdp or sdp_type != "offer":
        return JSONResponse(
            {"error": "Expected body {sdp, type='offer'}"},
            status_code=400,
        )

    # Create a WebRTC connection for this peer
    ice_servers = [s.strip() for s in _ICE_SERVERS if s.strip()]
    connection = SmallWebRTCConnection(ice_servers=ice_servers)

    async with _connection_lock:
        if len(_connections) >= _MAX_CONNECTIONS:
            return JSONResponse({"error": "server at capacity"}, status_code=429)
        _connections[session_id] = connection

    # Build transport params
    params = TransportParams(
        audio_in_enabled=True,
        audio_in_sample_rate=24_000,
        audio_in_channels=1,
        audio_out_enabled=True,
        audio_out_sample_rate=24_000,
        audio_out_channels=1,
    )

    try:
        # Initialize the connection with the browser's offer — this generates the answer
        await connection.initialize(sdp=sdp, type=sdp_type)
        answer_sdp = connection.get_answer()
        if answer_sdp is None:
            raise RuntimeError("SmallWebRTC connection produced no SDP answer")

        print(f"[server] Session {session_id}: SDP answer generated", flush=True)

        # Start the bot as a background task (it will run until the call ends)
        transport = SmallWebRTCTransport(connection, params)
        asyncio.create_task(_run_bot(session_id, transport, connection))

        return JSONResponse(
            {
                "sdp": answer_sdp,
                "type": "answer",
                "session_id": session_id,
            }
        )

    except Exception as exc:
        print(f"[server] Session {session_id}: offer error: {exc}", flush=True)
        async with _connection_lock:
            _connections.pop(session_id, None)
        return JSONResponse({"error": str(exc)}, status_code=500)


async def _run_bot(
    session_id: str,
    transport: SmallWebRTCTransport,
    connection: SmallWebRTCConnection,
) -> None:
    """Run the Pipecat bot pipeline for one session, then clean up."""
    try:
        print(f"[server] Session {session_id}: bot starting", flush=True)
        await bot_main(transport)
    except asyncio.CancelledError:
        print(f"[server] Session {session_id}: bot cancelled", flush=True)
    except Exception as exc:
        print(f"[server] Session {session_id}: bot error: {exc}", flush=True)
    finally:
        print(f"[server] Session {session_id}: bot ended, closing connection", flush=True)
        try:
            await connection.close()
        except Exception:
            pass
        async with _connection_lock:
            _connections.pop(session_id, None)


# ── Root → client page ───────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def root():
    """Serve the official Pipecat voice client.

    The client must authenticate ``POST /api/offer`` (it can reach the CEO
    backend). Rather than embed the long-lived ``CV_API_TOKEN`` in the page, we
    mint a **short-lived, single-use capability token** per load and inject it
    into ``__CV_OFFER_TOKEN__``; the client appends it as ``?token=``. It is
    consumed on first use and expires after ``CV_OFFER_CAP_TTL`` seconds, so log
    or history exposure is time-bounded and useless after the call starts.

    The capability is only minted when bound to loopback. When bound to a
    non-loopback interface we do NOT auto-inject any credential — an operator
    must supply the real token out-of-band — so the page is never a credential
    disclosure surface on the network.
    """
    index = _FRONTEND_DIR / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        cap = _mint_capability() if (CV_API_TOKEN and _HOST == "127.0.0.1") else ""
        html = html.replace("__CV_OFFER_TOKEN__", cap)
        return HTMLResponse(html)
    return JSONResponse(
        {"status": "Coding Vibe Pipecat server running", "port": _PORT},
    )


# ── Entry point ──────────────────────────────────────────────────────────────────


def _check_env() -> dict[str, str]:
    """Return missing env vars."""
    missing: dict[str, str] = {}
    if not os.environ.get("STEPFUN_API_KEY"):
        missing["STEPFUN_API_KEY"] = "Required for StepFun LLM + TTS"
    return missing


if __name__ == "__main__":
    import uvicorn  # pip install uvicorn

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

    # Fail closed: never arm a subprocess backend (claude-code/openopc → code exec)
    # without an auth token, since /api/offer would then be an unauthenticated RCE.
    _backend = os.environ.get("CV_CALL_BACKEND", "mock")
    if _backend in _DANGEROUS_BACKENDS and not CV_API_TOKEN:
        print(
            f"\n[FATAL] CV_CALL_BACKEND={_backend!r} spawns subprocesses but CV_API_TOKEN "
            "is unset — /api/offer would be an unauthenticated code-exec surface. "
            "Set CV_API_TOKEN or use CV_CALL_BACKEND=mock.\n",
            flush=True,
        )
        sys.exit(1)
    if _HOST != "127.0.0.1" and not CV_API_TOKEN:
        print(
            f"\n[WARN] Binding to {_HOST} without CV_API_TOKEN — /api/offer is open on "
            "the network. Set CV_API_TOKEN or bind CV_PIPECAT_HOST=127.0.0.1.\n",
            flush=True,
        )

    print(f"[server] Coding Vibe Pipecat voice server → http://{_HOST}:{_PORT}", flush=True)
    uvicorn.run(app, host=_HOST, port=_PORT)
