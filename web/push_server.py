"""web/push_server.py — Native VoIP push notification helpers + device registry.

Mount in ``web/server.py`` with::

    from web.push_server import router
    app.include_router(router)

Public symbols
--------------
router          FastAPI APIRouter (mounted routes live here)
send_apns_voip  Apple VoIP push via APNs HTTP/2 (.p8 key)
send_fcm        Google FCM HTTP v1 (service-account JSON)
ring_native     async — ring every registered device with a reason
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("coding-vibe.push")

# ── Env config ─────────────────────────────────────────────────────────────────

APNS_KEY_ID   = os.environ.get("APNS_KEY_ID", "")
APNS_TEAM_ID  = os.environ.get("APNS_TEAM_ID", "")
APNS_BUNDLE_ID = os.environ.get("APNS_BUNDLE_ID", "")
APNS_KEY_PATH = os.environ.get("APNS_KEY_PATH", "")

FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", "")
FCM_SERVICE_ACCOUNT_JSON = os.environ.get("FCM_SERVICE_ACCOUNT_JSON", "")

CV_API_TOKEN = os.environ.get("CV_API_TOKEN", "")

# ── In-memory device registry ──────────────────────────────────────────────────
# Structure: { "<device_id>": {"platform": str, "token": str, "registered_at": float} }
# NOTE: persist to disk / DB in a follow-up pass.

device_registry: dict[str, dict[str, Any]] = {}

# ── Push-provider availability flags ──────────────────────────────────────────
_apns_available: bool | None = None
_fcm_available:  bool | None = None


def _detect_apns() -> bool:
    """Return True if the APNs helper dependencies are importable."""
    try:
        import httpx
        import cryptography  # noqa: F401 — just needs to be importable
        return True
    except ImportError:
        return False


def _detect_fcm() -> bool:
    """Return True if the FCM helper dependencies are importable."""
    try:
        import google.oauth2.service_account  # noqa: F401
        import google.auth.transport.requests  # noqa: F401
        import httpx
        return True
    except ImportError:
        return False


def _check_auth(token: str | None) -> None:
    """Shared token-auth helper used by push routes."""
    if CV_API_TOKEN:
        if not token or not hmac.compare_digest(token, CV_API_TOKEN):
            raise HTTPException(401, "Missing or invalid API token (x-cv-token)")


# ── APNs VoIP push ─────────────────────────────────────────────────────────────

async def send_apns_voip(
    token: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Send a native VoIP push via Apple Push Notification service (APNs HTTP/2).

    Uses a .p8 key (JWT-based auth).  The push topic is ``<bundle>.voip``.

    Parameters
    ----------
    token:
        The device's APNs voip token (hex string).
    payload:
        Dict that will be JSON-serialised as the ``aps`` body.
        Callers should include at least ``{"alert": "..."}``.

    Returns
    -------
    The APNs response dict on success, or ``None`` if APNs is unavailable.

    Environment variables
    ----------------------
    APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID, APNS_KEY_PATH
    """
    global _apns_available
    if _apns_available is None:
        _apns_available = _detect_apns()
    if not _apns_available:
        logger.warning("[apns] Optional deps missing; skipping VoIP push. "
                       "Install: httpx cryptography")
        return None

    if not all([APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID, APNS_KEY_PATH]):
        logger.warning("[apns] Env vars not set; skipping VoIP push. "
                       "Set APNS_KEY_ID / APNS_TEAM_ID / APNS_BUNDLE_ID / APNS_KEY_PATH")
        return None

    from pathlib import Path as _Path

    key_path = _Path(APNS_KEY_PATH)
    if not key_path.exists():
        logger.warning(f"[apns] Key file not found: {key_path}")
        return None

    try:
        # Build a short-lived JWT (exp = now + 20 min)
        import jwt  # PyJWT — optional, same dep as cryptography
        from datetime import timedelta

        with open(key_path) as f:
            private_key = f.read()

        now = datetime.now(timezone.utc)
        jwt_token = jwt.encode(
            {
                "iss": APNS_TEAM_ID,
                "iat": now,
                "exp": now + timedelta(minutes=20),
            },
            private_key,
            algorithm="ES256",
            headers={"alg": "ES256", "kid": APNS_KEY_ID},
        )

        topic = f"{APNS_BUNDLE_ID}.voip"
        apns_host = "api.push.apple.com"
        url = f"https://{apns_host}/3/device/{token}"

        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={
                    "apns-topic": topic,
                    "apns-push-type": "voip",
                    "authorization": f"bearer {jwt_token}",
                    "content-type": "application/json",
                },
                json={"aps": payload},
            )
            if resp.status_code == 200:
                logger.info(f"[apns] VoIP push sent to {token[:16]}...")
                return resp.json()
            logger.warning(f"[apns] APNs returned {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as exc:
        logger.warning(f"[apns] Exception: {exc}")
        return None


# ── FCM HTTP v1 ────────────────────────────────────────────────────────────────

async def send_fcm(token: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Send a high-priority push via Firebase Cloud Messaging HTTP v1 API.

    Parameters
    ----------
    token:
        The FCM registration token (device token).
    data:
        Custom data payload dict.  Use ``{"title": "...", "body": "..."}``
        for notification fields, or ``{"key": "value", ...}`` for data-only.

    Returns
    -------
    The FCM response dict on success, or ``None`` if FCM is unavailable.

    Environment variables
    ----------------------
    FCM_PROJECT_ID, FCM_SERVICE_ACCOUNT_JSON  (path to a .json service-account file)
    """
    global _fcm_available
    if _fcm_available is None:
        _fcm_available = _detect_fcm()
    if not _fcm_available:
        logger.warning("[fcm] Optional deps missing; skipping FCM push. "
                       "Install: google-auth google-auth-httplib2 httpx")
        return None

    if not all([FCM_PROJECT_ID, FCM_SERVICE_ACCOUNT_JSON]):
        logger.warning("[fcm] Env vars not set; skipping FCM push. "
                       "Set FCM_PROJECT_ID / FCM_SERVICE_ACCOUNT_JSON")
        return None

    from pathlib import Path as _Path

    sa_path = _Path(FCM_SERVICE_ACCOUNT_JSON)
    if not sa_path.exists():
        logger.warning(f"[fcm] Service-account file not found: {sa_path}")
        return None

    try:
        import google.oauth2.service_account
        import google.auth.transport.requests
        import httpx

        credentials = google.oauth2.service_account.Credentials.from_service_account_file(
            str(sa_path),
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        request_obj = google.auth.transport.requests.Request()
        credentials.refresh(request_obj)
        access_token = credentials.token

        url = (
            f"https://fcm.googleapis.com/v1/projects/"
            f"{FCM_PROJECT_ID}/messages:send"
        )
        message: dict[str, Any] = {
            "token": token,
            "android": {
                "priority": "high",
            },
        }
        # Separate notification fields from data fields
        notification_fields = {"title", "body", "image", "sound", "tag", "color"}
        notif_part: dict[str, Any] = {}
        data_part: dict[str, Any] = {}
        for k, v in data.items():
            if k in notification_fields:
                notif_part[k] = v
            else:
                data_part[k] = v
        if notif_part:
            message["notification"] = notif_part
        if data_part:
            message["data"] = data_part

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"message": message},
            )
            if resp.status_code == 200:
                logger.info(f"[fcm] FCM push sent to {token[:16]}...")
                return resp.json()
            logger.warning(f"[fcm] FCM returned {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as exc:
        logger.warning(f"[fcm] Exception: {exc}")
        return None


# ── Device registry ────────────────────────────────────────────────────────────

async def ring_native(reason: str) -> None:
    """Send a native VoIP / notification push to every registered device.

    Called alongside web-signalling ring events so the native app can be
    woken up and present an incoming-call UI even if the browser tab is
    backgrounded.

    Parameters
    ----------
    reason:
        Human-readable text forwarded in the push payload (e.g. "new_task",
        "agent_ready", "outgoing_call").
    """
    payload_base = {"reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()}
    tasks: list[asyncio.Task[Any]] = []

    for device_id, device in device_registry.items():
        platform = device["platform"]
        token    = device["token"]

        if platform == "ios":
            apns_payload = {**payload_base, "alert": reason}
            tasks.append(
                asyncio.create_task(send_apns_voip(token, apns_payload))
            )
        elif platform == "android":
            fcm_data = {"reason": reason, "action": "ring"}
            tasks.append(
                asyncio.create_task(send_fcm(token, fcm_data))
            )
        else:
            logger.debug(f"[ring_native] Unknown platform {platform!r}; skipping.")

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for device_id, result in zip(device_registry, results):
            if isinstance(result, Exception):
                logger.warning(f"[ring_native] Push failed for {device_id}: {result}")

    logger.info(f"[ring_native] Rung {len(tasks)} device(s) for reason={reason!r}")


# ── FastAPI router ─────────────────────────────────────────────────────────────

router = APIRouter(prefix="", tags=["push"])


@router.post("/api/devices/register")
async def register_device(body: dict[str, Any], request: Request):
    """Register or update a device token for native VoIP push.

    Request body::

        {
            "platform": "ios" | "android",
            "token": "<device push token>",
            "device_id": "<optional stable id, e.g. uuid>"
        }

    Returns the device record.  Omitting ``device_id`` generates one from
    the token hash.
    """
    _check_auth(request.headers.get("x-cv-token"))

    platform = (body.get("platform") or "").lower().strip()
    token    = (body.get("token") or "").strip()
    if platform not in ("ios", "android"):
        raise HTTPException(400, "'platform' must be 'ios' or 'android'")
    if not token:
        raise HTTPException(400, "'token' is required")

    device_id = body.get("device_id") or token[:16]
    record = {
        "platform":      platform,
        "token":         token,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "user_agent":    request.headers.get("user-agent", ""),
    }
    device_registry[device_id] = record
    logger.info(f"[register_device] {platform} device {device_id!r}")
    return {"ok": True, "device_id": device_id, **record}


@router.get("/api/devices")
async def list_devices(request: Request):
    """Return the current device registry (redacted tokens)."""
    _check_auth(request.headers.get("x-cv-token"))
    summary = []
    for device_id, record in device_registry.items():
        summary.append({
            "device_id":      device_id,
            "platform":       record["platform"],
            "token_preview":  record["token"][:16] + "...",
            "registered_at":  record["registered_at"],
        })
    return {"devices": summary, "count": len(summary)}


@router.post("/api/devices/ring")
async def trigger_ring(body: dict[str, Any], request: Request):
    """Manually trigger a native push ring to all registered devices.

    Body::

        {"reason": "agent_ready"}   # optional, default "ring"
    """
    _check_auth(request.headers.get("x-cv-token"))
    reason = (body.get("reason") or "ring").strip()
    await ring_native(reason)
    return {"ok": True, "reason": reason, "devices_targeted": len(device_registry)}
