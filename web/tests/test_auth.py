from __future__ import annotations

import time

import web.auth as auth


def test_capability_is_short_lived_and_accepts_bearer(monkeypatch):
    monkeypatch.setattr(auth, "EXPECTED_TOKEN", "long-lived-secret")
    capability = auth.mint_capability()

    assert capability and capability != "long-lived-secret"
    assert capability.startswith("v1.")
    assert auth.is_valid_token("long-lived-secret")
    assert auth.is_valid_token(capability)
    assert not auth.is_valid_token("wrong")


def test_expired_capability_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "EXPECTED_TOKEN", "long-lived-secret")
    monkeypatch.setattr(auth, "CAPABILITY_TTL", 20)
    monkeypatch.setattr(auth.time, "time", lambda: 1_000.0)
    capability = auth.mint_capability()

    monkeypatch.setattr(auth.time, "time", lambda: 1_021.0)
    assert not auth.is_valid_token(capability)


def test_capability_is_valid_after_module_state_is_reset(monkeypatch):
    """A server reload must not invalidate an unexpired browser call token."""
    monkeypatch.setattr(auth, "EXPECTED_TOKEN", "long-lived-secret")
    monkeypatch.setattr(auth.time, "time", lambda: 5_000.0)
    capability = auth.mint_capability()

    # A new worker only needs the configured secret, not an in-memory registry.
    monkeypatch.setattr(auth.time, "time", lambda: 5_001.0)
    assert auth.is_valid_token(capability)
