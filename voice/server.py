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
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Project path ─────────────────────────────────────────────────────────────────
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_WORKTREE_ROOT))

# ── Config ────────────────────────────────────────────────────────────────────────
_HOST = os.environ.get("CV_PIPECAT_HOST", "127.0.0.1")
_PORT = int(os.environ.get("CV_PIPECAT_PORT", "7860"))
STEPFUN_API_KEY = os.environ.get("STEPFUN_API_KEY", "")
STEPFUN_REALTIME_URL = "wss://api.stepfun.com/v1/realtime"
REALTIME_MODEL = os.environ.get("CV_REALTIME_MODEL", "step-1o-audio")

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
