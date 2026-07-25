"""web/signaling.py — FastAPI APIRouter for real-time signaling / callbacks.

Endpoints:
  WS   /api/events   — client connects and stays open; server pushes JSON events.
  POST /api/call/ring — emits an 'incoming_call' event to all connected clients.

Auth
  WebSocket: ?token=<CV_API_TOKEN> query param.
  POST:      x-cv-token header OR ?token= query param.
  Both checked with hmac.compare_digest (constant-time) when CV_API_TOKEN is set.

When CV_API_TOKEN is NOT set (local dev) auth is skipped.

Server.py must mount this router, e.g.:
    from web.signaling import router as signaling_router
    app.include_router(signaling_router)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from web.auth import is_valid_token

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_TOKEN = os.environ.get("CV_API_TOKEN", "")  # empty → auth disabled

EVENT_TYPES = frozenset(
    {"incoming_call", "call_state", "task_update", "board_update", "network_update"}
)

router = APIRouter(prefix="", tags=["signaling"])

# ---------------------------------------------------------------------------
# In-memory client registry
# ---------------------------------------------------------------------------


class _ClientRegistry:
    """Thread-safe set of active WebSocket connections."""

    def __init__(self) -> None:
        self._clients: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> str:
        cid = str(uuid.uuid4())
        async with self._lock:
            self._clients[cid] = ws
        return cid

    async def remove(self, cid: str) -> None:
        async with self._lock:
            self._clients.pop(cid, None)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Push *event* to every connected client; drop dead connections."""
        payload = json.dumps(event, ensure_ascii=False)
        async with self._lock:
            targets = list(self._clients.items())

        for cid, ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                # Connection lost — remove silently
                await self.remove(cid)


_clients = _ClientRegistry()


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _check_token(raw: str) -> bool:
    """Return True if *raw* matches CV_API_TOKEN (constant-time)."""
    return is_valid_token(raw)


def _reject(msg: str) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=401)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/api/events")
async def ws_events(
    websocket: WebSocket,
    token: str = Query("", description="CV_API_TOKEN"),
) -> None:
    """
    Persistent WebSocket connection.

    The server may push any of these event shapes at any time::

        {"type": "incoming_call", "reason": "...", "from": "..."}
        {"type": "call_state",    "state": "ringing|accepted|ended", ...}
        {"type": "task_update",   "task_id": "...", "status": "...", ...}
        {"type": "board_update",  "board": {...}}

    Clients may also send text frames (ignored by the server at present).
    """
    # ---- auth ----
    # Token from query (back-compat) OR first message {"type":"auth","token":...}
    # so the secret never has to appear in the WS URL / access logs.
    await websocket.accept()
    if EXPECTED_TOKEN:
        ok = bool(token) and _check_token(token)
        if not ok:
            try:
                first = await asyncio.wait_for(websocket.receive_text(), timeout=5)
                provided = (json.loads(first) or {}).get("token", "")
                ok = bool(provided) and _check_token(provided)
            except Exception:
                ok = False
        if not ok:
            await websocket.close(code=4401, reason="Invalid token")
            return

    cid = await _clients.add(websocket)
    try:
        # Keep the connection alive; just drain incoming frames.
        while True:
            data = await websocket.receive_text()
            # Silently discard — the server initiates all events.
    except WebSocketDisconnect:
        pass
    finally:
        await _clients.remove(cid)


# ---------------------------------------------------------------------------
# POST endpoint — agent triggers an incoming-call event
# ---------------------------------------------------------------------------


@router.post("/api/call/ring")
async def post_call_ring(
    request: Request,
    reason: str | None = Query(None, description="Human-readable reason for the call"),
    frm: str | None = Query(None, alias="from", description="Caller identifier"),
) -> JSONResponse:
    """
    Trigger an ``incoming_call`` event for every connected WebSocket client.

    Called by the AGENT to notify the USER of an incoming call.

    Auth: ``x-cv-token`` header or ``?token=`` query param must match
    ``CV_API_TOKEN`` (checked with ``hmac.compare_digest``).
    """
    # ---- auth (header takes priority, then query) ----
    raw = request.headers.get("x-cv-token", "")
    if not raw:
        raw = request.query_params.get("token", "")
    if EXPECTED_TOKEN and not _check_token(raw):
        return _reject("Invalid token")

    await _clients.broadcast(
        {
            "type": "incoming_call",
            "reason": reason or "",
            "from": frm or "",
        }
    )
    # Do not leak the live client count to callers (connection-probe side channel).
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Public helper — importable by other modules
# ---------------------------------------------------------------------------


async def ring(reason: str = "", frm: str = "") -> int:
    """Broadcast an ``incoming_call`` event to all connected clients.

    Returns the number of clients the event was sent to.

    Usage in another module::

        from web.signaling import ring
        await ring(reason="Urgent review needed", frm="agent")
    """
    await _clients.broadcast(
        {
            "type": "incoming_call",
            "reason": reason,
            "from": frm,
        }
    )
    # Access is safe because _ClientRegistry holds the lock internally;
    # reading len after broadcast is best-effort (no lock on _clients here).
    return len(_clients._clients)
