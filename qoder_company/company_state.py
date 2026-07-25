"""Persistent active-company state shared by voice dispatch and the dashboard."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from qoder_company.network import DEFAULT_AVATAR
from qoder_company.presets import get_preset, list_presets

DEFAULT_PRESET_ID = "rapid-startup"
_SAFE_ID = re.compile(r"[^a-z0-9-]+")
_ALLOWED_PERMISSION_MODES = {"dont_ask", "accept_edits", "auto"}


def state_path() -> Path:
    """Resolve storage lazily so tests and deployments can set it per process."""
    explicit = os.environ.get("CV_COMPANY_STATE_FILE")
    if explicit:
        return Path(explicit).expanduser()
    state_dir = Path(os.environ.get("CODING_VIBE_STATE_DIR", Path.home() / ".coding-vibe"))
    return state_dir / "company.json"


def _safe_id(value: str, fallback: str = DEFAULT_PRESET_ID) -> str:
    cleaned = _SAFE_ID.sub("-", (value or "").strip().lower()).strip("-")
    return cleaned[:80] or fallback


def _session_id(company_id: str) -> str:
    """Create Qoder's required UUID session id deterministically per company."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"coding-vibe-company:{company_id}"))


def _normalise_session_id(value: object, company_id: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return _session_id(company_id)


def _new_company(preset_id: str, *, company_id: str | None = None, name: str | None = None) -> dict[str, Any]:
    preset = get_preset(preset_id)
    resolved_id = _safe_id(company_id or preset_id, preset_id)
    return {
        "id": resolved_id,
        "preset_id": preset_id,
        "name": (name or preset["name"]).strip()[:120],
        "avatar": DEFAULT_AVATAR,
        "qoder_session_id": _session_id(resolved_id),
        # This allows a user-approved company run to complete without a click
        # per local file edit, while never selecting a bypass mode.
        "permission_mode": "accept_edits",
    }


def _default_state() -> dict[str, Any]:
    company = _new_company(DEFAULT_PRESET_ID)
    return {"active_company_id": company["id"], "companies": {company["id"]: company}}


def _load() -> dict[str, Any]:
    path = state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(data, dict) or not isinstance(data.get("companies"), dict):
        return _default_state()
    return data


def _save(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents a concurrent dashboard refresh seeing partial
    # JSON.  The temporary file lives beside the target so replace is atomic.
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _normalise_company(raw: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    preset_id = raw.get("preset_id") if isinstance(raw.get("preset_id"), str) else DEFAULT_PRESET_ID
    try:
        preset = get_preset(preset_id)
    except KeyError:
        preset_id = DEFAULT_PRESET_ID
        preset = get_preset(preset_id)
    company_id = _safe_id(str(raw.get("id") or fallback_id), preset_id)
    permission_mode = str(raw.get("permission_mode") or "accept_edits")
    if permission_mode not in _ALLOWED_PERMISSION_MODES:
        permission_mode = "accept_edits"
    return {
        "id": company_id,
        "preset_id": preset_id,
        "name": str(raw.get("name") or preset["name"]).strip()[:120] or preset["name"],
        "avatar": str(raw.get("avatar") or DEFAULT_AVATAR),
        "qoder_session_id": _normalise_session_id(raw.get("qoder_session_id"), company_id),
        "permission_mode": permission_mode,
    }


def get_active_company() -> dict[str, Any]:
    """Return the selected company, repairing malformed persisted state safely."""
    state = _load()
    active_id = _safe_id(str(state.get("active_company_id") or DEFAULT_PRESET_ID))
    raw = state.get("companies", {}).get(active_id)
    if not isinstance(raw, dict):
        raw = _new_company(DEFAULT_PRESET_ID, company_id=active_id)
    return _normalise_company(raw, active_id)


def activate_preset(preset_id: str, *, company_id: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Create/select a company based on a known preset and persist the choice."""
    get_preset(preset_id)  # validate before writing
    state = _load()
    company = _new_company(preset_id, company_id=company_id, name=name)
    existing = state.setdefault("companies", {}).get(company["id"])
    if isinstance(existing, dict) and existing.get("preset_id") == preset_id:
        preserved = _normalise_company(existing, company["id"])
        company["avatar"] = preserved["avatar"]
        company["qoder_session_id"] = preserved["qoder_session_id"]
        company["permission_mode"] = preserved["permission_mode"]
    state["companies"][company["id"]] = company
    state["active_company_id"] = company["id"]
    _save(state)
    return deepcopy(company)


def update_active_avatar(avatar_url: str) -> dict[str, Any]:
    """Persist the already-validated user avatar for the active company."""
    if not avatar_url or len(avatar_url) > 2_000_000:
        raise ValueError("avatar URL is empty or too large")
    state = _load()
    company = get_active_company()
    company["avatar"] = avatar_url
    state.setdefault("companies", {})[company["id"]] = company
    state["active_company_id"] = company["id"]
    _save(state)
    return deepcopy(company)


def active_dispatch_context() -> dict[str, Any]:
    """Build the trusted Qoder context for an engineer dispatch.

    Callers never supply the CEO prompt or Qoder permission setting.  They are
    selected locally from a preset, which prevents a browser request from
    escalating the execution profile.
    """
    company = get_active_company()
    preset = get_preset(company["preset_id"])
    return {
        "mode": "company",
        "company_id": company["id"],
        "company_name": company["name"],
        "preset_id": company["preset_id"],
        "roles": deepcopy(preset["roles"]),
        "ceo_prompt": preset["ceo_prompt"],
        "use_cli": True,
        "persistent_cli": True,
        "session_id": company["qoder_session_id"],
        "permission_mode": company["permission_mode"],
        "backend": "qoder",
    }


def public_company_state() -> dict[str, Any]:
    """Return safe dashboard data without exposing the CEO system prompt."""
    company = get_active_company()
    preset = get_preset(company["preset_id"])
    return {
        "active": {
            "id": company["id"],
            "name": company["name"],
            "preset_id": company["preset_id"],
            "avatar": company["avatar"],
            "permission_mode": company["permission_mode"],
            "type": preset["type"],
            "tagline": preset["tagline"],
            "roles": list(preset["roles"]),
        },
        "presets": list_presets(),
    }
