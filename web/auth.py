"""Shared short-lived capability tokens for the local demo surfaces.

The long-lived ``CV_API_TOKEN`` stays out of browser URLs.  The unified
company page receives a short-lived capability when it is opened locally;
HTTP and WebSocket routes accept either the configured bearer token or that
capability.  With no configured token, authentication remains disabled for
local development as before.
"""

from __future__ import annotations

import hmac
import os
import secrets
import time
from base64 import urlsafe_b64encode

EXPECTED_TOKEN = os.environ.get("CV_API_TOKEN", "")
CAPABILITY_TTL = float(os.environ.get("CV_CAPABILITY_TTL", "600"))


def _capability_signature(payload: str) -> str:
    """Return a URL-safe signature for a browser capability payload."""
    digest = hmac.digest(EXPECTED_TOKEN.encode("utf-8"), payload.encode("utf-8"), "sha256")
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def mint_capability() -> str:
    """Mint a reload-safe, short-lived browser capability.

    Older capabilities lived only in process memory.  That made a normal
    development-server reload look like a successful WebSocket connection
    followed by an immediate auth failure.  A signed expiry-bound capability
    keeps the browser session valid across a reload without exposing the
    long-lived API token.
    """
    if not EXPECTED_TOKEN:
        return ""
    expires_at = int(time.time() + CAPABILITY_TTL)
    payload = f"v1.{expires_at}.{secrets.token_urlsafe(16)}"
    return f"{payload}.{_capability_signature(payload)}"


def is_valid_token(raw: str | None) -> bool:
    """Validate the configured bearer token or an unexpired capability."""
    if not EXPECTED_TOKEN:
        return True
    token = (raw or "").strip()
    if token and hmac.compare_digest(token, EXPECTED_TOKEN):
        return True
    try:
        version, expiry_text, nonce, signature = token.split(".")
        expires_at = int(expiry_text)
    except (TypeError, ValueError):
        return False
    if version != "v1" or not nonce or expires_at <= time.time():
        return False
    payload = f"{version}.{expiry_text}.{nonce}"
    return hmac.compare_digest(signature, _capability_signature(payload))
