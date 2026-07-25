from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import pytest
from fastapi import Request

from web import photon, photon_send


def _request(raw: bytes, headers: dict[str, str]) -> Request:
    """Build a minimal in-memory ASGI request without opening a socket."""
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/photon-webhook",
            "raw_path": b"/photon-webhook",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
        receive,
    )


def _signature(raw: bytes, timestamp: str, secret: str = "test-secret") -> str:
    digest = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return f"v0={digest}"


def _headers(raw: bytes, *, timestamp: str | None = None) -> dict[str, str]:
    timestamp = timestamp or str(int(time.time()))
    return {
        "content-type": "application/json",
        "content-length": str(len(raw)),
        "x-spectrum-timestamp": timestamp,
        "x-spectrum-signature": _signature(raw, timestamp),
    }


def _text_event(text: str = "请做一个计时器") -> bytes:
    return json.dumps(
        {
            "message": {
                "platform": "telegram",
                "content": {"type": "text", "text": text},
            },
            "space": {"id": "space-1", "kind": "group"},
        },
        ensure_ascii=False,
    ).encode()


async def _clear_runtime_state() -> None:
    photon._replay_guard.clear()
    await photon_send.transport_registry.clear()


@pytest.mark.asyncio
async def test_webhook_fails_closed_without_a_signing_secret(monkeypatch):
    await _clear_runtime_state()
    monkeypatch.delenv("PHOTON_SIGNING_SECRET", raising=False)
    raw = _text_event()
    response = await photon.photon_webhook(_request(raw, _headers(raw)))

    assert response.status_code == 401
    assert json.loads(response.body) == {"error": "invalid signature"}


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_and_replayed_signed_payloads(monkeypatch):
    await _clear_runtime_state()
    monkeypatch.setenv("PHOTON_SIGNING_SECRET", "test-secret")
    raw = _text_event()
    headers = _headers(raw)
    calls: list[str] = []

    async def fake_classify(text: str, _callback, **_kwargs) -> None:
        calls.append(text)

    monkeypatch.setattr(photon, "classify_and_dispatch", fake_classify)

    invalid = dict(headers)
    invalid["x-spectrum-signature"] = "v0=not-a-valid-signature"
    bad_response = await photon.photon_webhook(_request(raw, invalid))
    first_response = await photon.photon_webhook(_request(raw, headers))
    replay_response = await photon.photon_webhook(_request(raw, headers))

    assert bad_response.status_code == 401
    assert first_response.status_code == 200
    assert replay_response.status_code == 401
    assert calls == ["请做一个计时器"]


def test_signature_rejects_stale_timestamps_and_uses_raw_bytes(monkeypatch):
    photon._replay_guard.clear()
    monkeypatch.setenv("PHOTON_SIGNING_SECRET", "test-secret")
    raw = b'{"message":{"content":{"type":"text","text":"A"}}}'
    timestamp = "1000"
    signature = _signature(raw, timestamp)

    assert not photon.verify_spectrum_signature(raw, timestamp, signature, now=1301)
    assert photon.verify_spectrum_signature(raw, timestamp, signature, now=1000)
    # Re-encoding semantically equivalent JSON changes the signed bytes and is
    # correctly rejected.  This guards against accidental Request.json() use.
    assert not photon.verify_spectrum_signature(
        b'{"message": {"content": {"type": "text", "text": "A"}}}',
        timestamp,
        signature,
        now=1000,
    )


@pytest.mark.asyncio
async def test_non_text_event_is_acknowledged_without_dispatch(monkeypatch):
    await _clear_runtime_state()
    monkeypatch.setenv("PHOTON_SIGNING_SECRET", "test-secret")
    raw = json.dumps(
        {
            "message": {"content": {"type": "image", "url": "https://example.test/a"}},
            "space": {"id": "space-1"},
        }
    ).encode()

    async def unexpected_classifier(*_args, **_kwargs):
        raise AssertionError("non-text content must not reach dispatch")

    monkeypatch.setattr(photon, "classify_and_dispatch", unexpected_classifier)
    response = await photon.photon_webhook(_request(raw, _headers(raw)))

    assert response.status_code == 200
    assert json.loads(response.body) == {"ok": True, "ignored": True}


@pytest.mark.asyncio
async def test_dispatched_message_records_space_and_acknowledges_same_space(monkeypatch):
    await _clear_runtime_state()
    monkeypatch.setenv("PHOTON_SIGNING_SECRET", "test-secret")
    raw = _text_event("请实现登录页")
    delivered: list[tuple[dict[str, Any], str]] = []

    async def fake_classify(text: str, callback, *, on_task_started) -> None:
        assert text == "请实现登录页"
        info = {
            "status": "dispatched",
            "task_id": "task-42",
            "task": "实现登录页",
            "backend": "mock",
        }
        # This is the crucial order enforced by engineer_dispatch: establish
        # the completion route before sending the ordinary dispatch ack.
        assert on_task_started(info)
        await callback(info)

    async def fake_send(space: dict[str, Any], text: str) -> bool:
        delivered.append((space, text))
        return True

    monkeypatch.setattr(photon, "classify_and_dispatch", fake_classify)
    monkeypatch.setattr(photon_send, "send_message", fake_send)
    response = await photon.photon_webhook(_request(raw, _headers(raw)))
    route = await photon_send.transport_registry.get("task-42")

    assert response.status_code == 200
    assert route is not None
    assert route.space == {"id": "space-1", "kind": "group"}
    assert route.platform == "telegram"
    assert delivered == [
        ({"id": "space-1", "kind": "group"}, "收到，已交给工程团队：实现登录页（#task-42）")
    ]


@pytest.mark.asyncio
async def test_completion_returns_only_to_the_established_task_space(monkeypatch):
    await _clear_runtime_state()
    await photon_send.transport_registry.remember(
        "task-7", {"id": "origin-space"}, platform="telegram"
    )
    delivered: list[tuple[dict[str, Any], str]] = []

    async def fake_send(space: dict[str, Any], text: str) -> bool:
        delivered.append((space, text))
        return True

    monkeypatch.setattr(photon_send, "send_message", fake_send)
    assert await photon_send.notify_task_complete("task-7", "登录页已完成", ok=True)
    assert not await photon_send.notify_task_complete("unknown-task", "不会发送")
    assert delivered == [({"id": "origin-space"}, "✅ 完成：登录页已完成")]
    assert await photon_send.transport_registry.get("task-7") is None


@pytest.mark.asyncio
async def test_sender_skips_missing_or_unsafe_local_configuration(monkeypatch):
    await _clear_runtime_state()

    class UnexpectedClient:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("sender must not make a network call")

    monkeypatch.setattr(photon_send.httpx, "AsyncClient", UnexpectedClient)
    for key in (
        "PHOTON_PROJECT_ID",
        "PHOTON_PROJECT_SECRET",
        "PHOTON_SIDECAR_TOKEN",
        "PHOTON_SIDECAR_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    assert not await photon_send.send_message({"id": "space"}, "hello")

    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "local-token")
    monkeypatch.setenv("PHOTON_SIDECAR_URL", "https://example.test/send")
    assert not await photon_send.send_message({"id": "space"}, "hello")


@pytest.mark.asyncio
async def test_sender_posts_only_to_configured_loopback_sidecar(monkeypatch):
    await _clear_runtime_state()
    # The Python sender intentionally does not receive Photon project
    # credentials; only the loopback sidecar owns those SDK credentials.
    monkeypatch.delenv("PHOTON_PROJECT_ID", raising=False)
    monkeypatch.delenv("PHOTON_PROJECT_SECRET", raising=False)
    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "local-token")
    monkeypatch.setenv("PHOTON_SIDECAR_URL", "http://127.0.0.1:9876/send")
    seen: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            seen["timeout"] = kwargs["timeout"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            seen["url"] = url
            seen.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(photon_send.httpx, "AsyncClient", FakeClient)
    assert await photon_send.send_message({"id": "space"}, " ready ")

    assert seen == {
        "timeout": 3.0,
        "url": "http://127.0.0.1:9876/send",
        "json": {"space": {"id": "space"}, "text": "ready"},
        "headers": {"x-photon-sidecar-token": "local-token"},
    }


def test_server_mounts_the_photon_webhook_router():
    """The handler is reachable from the same FastAPI app as dispatch/ring."""
    from web.server import app

    mounted_paths = {
        child.path
        for included in app.routes
        for child in getattr(getattr(included, "original_router", None), "routes", [])
    }
    assert "/photon-webhook" in mounted_paths
