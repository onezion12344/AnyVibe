"""Secure Photon Spectrum webhook: inbound messages → engineering dispatch.

Photon signs the exact HTTP bytes it sends.  Keep verification here, before
JSON parsing, so a decoded/re-encoded JSON document can never invalidate the
security boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from web import photon_send
from web.engineer_dispatch import classify_and_dispatch


router = APIRouter(tags=["photon"])

_SIGNATURE_VERSION = "v0"
_MAX_CLOCK_SKEW_SECONDS = 300
_MAX_WEBHOOK_BYTES = 128 * 1024
_MAX_REPLAY_ENTRIES = 4_096
_MAX_TEXT_CHARS = 8_000
_TIMESTAMP_RE = re.compile(r"^[0-9]{1,16}$")


class _ReplayGuard:
    """Bounded replay cache for valid signed requests inside the clock window."""

    def __init__(self) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()

    def consume(self, fingerprint: str, *, now: float) -> bool:
        """Return True only for the first sighting of a valid request."""
        cutoff = now - _MAX_CLOCK_SKEW_SECONDS
        for key, seen_at in list(self._seen.items()):
            if seen_at < cutoff:
                self._seen.pop(key, None)
        if fingerprint in self._seen:
            return False
        self._seen[fingerprint] = now
        self._seen.move_to_end(fingerprint)
        while len(self._seen) > _MAX_REPLAY_ENTRIES:
            self._seen.popitem(last=False)
        return True

    def clear(self) -> None:
        self._seen.clear()


_replay_guard = _ReplayGuard()


def _signing_secret() -> str:
    """Read lazily so an unset deployment fails closed and tests stay isolated."""
    return os.environ.get("PHOTON_SIGNING_SECRET", "")


def _parse_timestamp(value: str) -> int | None:
    if not _TIMESTAMP_RE.fullmatch(value or ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def verify_spectrum_signature(
    raw: bytes,
    timestamp: str,
    signature: str,
    *,
    now: float | None = None,
) -> bool:
    """Verify a raw Spectrum webhook and consume its replay nonce.

    Verification fails closed for missing configuration, malformed timestamps,
    stale/future timestamps, invalid signatures, and duplicate valid delivery.
    ``raw`` must be the untouched bytes returned by ``Request.body()``.
    """
    secret = _signing_secret()
    parsed_timestamp = _parse_timestamp(timestamp)
    current = time.time() if now is None else now
    if not secret or parsed_timestamp is None or not signature:
        return False
    if abs(current - parsed_timestamp) > _MAX_CLOCK_SKEW_SECONDS:
        return False

    signed = timestamp.encode("ascii") + b"." + raw
    expected = _SIGNATURE_VERSION + "=" + hmac.new(
        secret.encode("utf-8"), signed, hashlib.sha256
    ).hexdigest()
    try:
        valid = hmac.compare_digest(expected, signature)
    except TypeError:
        return False
    if not valid:
        return False

    fingerprint = hashlib.sha256(
        timestamp.encode("ascii") + b"\0" + signature.encode("ascii")
    ).hexdigest()
    return _replay_guard.consume(fingerprint, now=current)


def _extract_text_message(payload: object) -> tuple[str, dict[str, Any], str] | None:
    """Return (text, space, platform) for a supported inbound Spectrum event."""
    if not isinstance(payload, dict):
        return None
    message = payload.get("message")
    space = payload.get("space")
    if not isinstance(message, dict) or not isinstance(space, dict):
        return None
    content = message.get("content")
    if not isinstance(content, dict) or content.get("type") != "text":
        return None
    text = content.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    if len(text) > _MAX_TEXT_CHARS or photon_send._validated_space(space) is None:
        return None
    platform = message.get("platform")
    return text.strip(), space, platform if isinstance(platform, str) else ""


@router.post("/photon-webhook")
async def photon_webhook(request: Request) -> JSONResponse:
    """Receive a signed Spectrum event without exposing dispatch to the public."""
    content_length = request.headers.get("content-length")
    try:
        if content_length is not None and int(content_length) > _MAX_WEBHOOK_BYTES:
            return JSONResponse({"error": "payload too large"}, status_code=413)
    except ValueError:
        return JSONResponse({"error": "invalid content length"}, status_code=400)

    raw = await request.body()
    if len(raw) > _MAX_WEBHOOK_BYTES:
        return JSONResponse({"error": "payload too large"}, status_code=413)

    timestamp = request.headers.get("X-Spectrum-Timestamp", "")
    signature = request.headers.get("X-Spectrum-Signature", "")
    if not verify_spectrum_signature(raw, timestamp, signature):
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        payload = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid json"}, status_code=400)

    inbound = _extract_text_message(payload)
    if inbound is None:
        # A valid signed media, reaction, or unrelated lifecycle event is not an
        # error.  Acknowledge it without running the text classifier.
        return JSONResponse({"ok": True, "ignored": True})
    text, space, platform = inbound

    def _on_task_started(info: dict[str, Any]) -> bool:
        """Bind task id before its asynchronously scheduled work can finish."""
        if not isinstance(info, dict) or info.get("status") != "dispatched":
            return False
        task_id = str(info.get("task_id") or "").strip()
        if not task_id:
            return False
        return photon_send.transport_registry.remember_now(
            task_id, space, platform=platform
        )

    async def _on_dispatched(info: dict[str, Any]) -> None:
        if not isinstance(info, dict) or info.get("status") != "dispatched":
            return
        task_id = str(info.get("task_id") or "").strip()
        if not task_id:
            return
        task = str(info.get("task") or "").strip()[:400]
        acknowledgement = "收到，已交给工程团队处理。"
        if task:
            acknowledgement = f"收到，已交给工程团队：{task}（#{task_id}）"
        # Delivery failures are intentionally non-fatal: the task-to-space
        # route remains so the eventual completion can still be sent.
        await photon_send.send_message(space, acknowledgement)

    await classify_and_dispatch(text, _on_dispatched, on_task_started=_on_task_started)
    return JSONResponse({"ok": True})
