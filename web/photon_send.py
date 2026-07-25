"""Photon Spectrum outbound transport and established-space registry.

Spectrum's Python-facing webhook lands in :mod:`web.photon`, while Photon’s
official SDK runs in the small, loopback-only Node sidecar.  This module is the
only Python code that talks to that sidecar.  It deliberately keeps a task →
space mapping only after a user has contacted us, so task-completion messages
cannot become cold outreach.

All functions are best-effort.  A missing sidecar or Photon configuration must
never affect the browser callback, the kanban, or task completion.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


_DEFAULT_SIDECAR_URL = "http://127.0.0.1:8790/send"
_MAX_SPACE_BYTES = 16_384
_MAX_TEXT_CHARS = 2_000
_MAX_REGISTRY_ENTRIES = 1_024
_REGISTRY_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class PhotonRoute:
    """A previously established Spectrum conversation suitable for a reply."""

    space: dict[str, Any]
    platform: str = ""
    created_at: float = 0.0


class PhotonTransportRegistry:
    """Bounded in-memory map of dispatched task IDs to established spaces.

    The registry intentionally does not persist conversations.  A restart
    therefore errs on the safe side: it may skip a completion notification, but
    can never message a user without a fresh inbound conversation in this
    process.
    """

    def __init__(self) -> None:
        self._routes: OrderedDict[str, PhotonRoute] = OrderedDict()
        self._lock = asyncio.Lock()

    def remember_now(
        self, task_id: str, space: dict[str, Any], *, platform: str = ""
    ) -> bool:
        """Synchronously associate a just-created task with its conversation.

        Dispatch calls this before its background worker can report completion,
        eliminating the otherwise possible task-id → conversation registration
        race.  The web server handles these mutations on one asyncio loop; the
        async wrapper below remains available to ordinary callers/tests.
        """
        clean_task_id = str(task_id or "").strip()
        clean_space = _validated_space(space)
        if not clean_task_id or clean_space is None:
            return False
        now = time.time()
        route = PhotonRoute(
            space=clean_space,
            platform=str(platform or "")[:80],
            created_at=now,
        )
        self._prune_locked(now)
        self._routes[clean_task_id] = route
        self._routes.move_to_end(clean_task_id)
        while len(self._routes) > _MAX_REGISTRY_ENTRIES:
            self._routes.popitem(last=False)
        return True

    async def remember(
        self, task_id: str, space: dict[str, Any], *, platform: str = ""
    ) -> bool:
        """Async wrapper for callers that are not on the dispatch fast path."""
        async with self._lock:
            return self.remember_now(task_id, space, platform=platform)

    async def get(self, task_id: str) -> PhotonRoute | None:
        """Return a still-fresh reply route for *task_id*, if one exists."""
        clean_task_id = str(task_id or "").strip()
        if not clean_task_id:
            return None
        now = time.time()
        async with self._lock:
            self._prune_locked(now)
            route = self._routes.get(clean_task_id)
            if route is not None:
                self._routes.move_to_end(clean_task_id)
            return route

    async def forget(self, task_id: str) -> None:
        """Discard a route after a successful terminal notification."""
        async with self._lock:
            self._routes.pop(str(task_id or "").strip(), None)

    async def clear(self) -> None:
        """Clear state; primarily useful for deterministic tests."""
        async with self._lock:
            self._routes.clear()

    def _prune_locked(self, now: float) -> None:
        cutoff = now - _REGISTRY_TTL_SECONDS
        for task_id, route in list(self._routes.items()):
            if route.created_at < cutoff:
                self._routes.pop(task_id, None)


transport_registry = PhotonTransportRegistry()


def _validated_space(space: object) -> dict[str, Any] | None:
    """Accept a JSON-object Spectrum space small enough to retain and forward."""
    if not isinstance(space, dict) or not space:
        return None
    try:
        encoded = json.dumps(space, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > _MAX_SPACE_BYTES:
        return None
    # JSON round-tripping removes any mutable caller-owned object references.
    return json.loads(encoded)


def _sidecar_url() -> str | None:
    """Return a configured loopback sidecar endpoint, never an arbitrary URL."""
    # The Python process needs only its local capability token.  Photon project
    # credentials remain inside the Node sidecar, which is the process using
    # the official SDK.
    if not os.environ.get("PHOTON_SIDECAR_TOKEN", "").strip():
        return None
    raw = os.environ.get("PHOTON_SIDECAR_URL", _DEFAULT_SIDECAR_URL).strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or not parsed.path
        or parsed.username
        or parsed.password
    ):
        return None
    return raw


async def send_message(space: dict[str, Any], text: str) -> bool:
    """Best-effort send through the local Node sidecar.

    Returns ``False`` for absent configuration, invalid payloads, a non-2xx
    sidecar response, or connection failures.  Callers should treat that as a
    skipped notification rather than an error in the underlying task.
    """
    url = _sidecar_url()
    clean_space = _validated_space(space)
    clean_text = str(text or "").strip()[:_MAX_TEXT_CHARS]
    if not url or clean_space is None or not clean_text:
        return False

    headers = {"x-photon-sidecar-token": os.environ["PHOTON_SIDECAR_TOKEN"]}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                url,
                json={"space": clean_space, "text": clean_text},
                headers=headers,
            )
        return 200 <= response.status_code < 300
    except (httpx.HTTPError, OSError, ValueError):
        return False


async def notify_task_complete(
    task_id: str, summary: str, *, ok: bool | None = None
) -> bool:
    """Reply to the exact inbound Photon space that dispatched *task_id*.

    This function is intentionally a no-op when there was no established
    Photon conversation, for example for browser/phone initiated work.
    """
    route = await transport_registry.get(task_id)
    if route is None:
        return False
    headline = "✅ 完成" if ok is not False else "⚠️ 任务结束"
    detail = str(summary or "").strip()[:1_600] or "工程团队已结束本次处理。"
    delivered = await send_message(route.space, f"{headline}：{detail}")
    if delivered:
        await transport_registry.forget(task_id)
    return delivered
