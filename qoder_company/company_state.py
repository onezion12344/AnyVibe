"""Persistent active company and employee-team state.

The browser, the Company Kanban, and the single Yellow Sheep receptionist all
read this module.  That makes a selector change an execution decision rather
than a cosmetic dashboard change.
"""

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
from qoder_company.presets import (
    DEFAULT_COMPANY_PRESET_ID,
    DEFAULT_TEAM_PRESET_ID,
    build_ceo_prompt,
    get_company_preset,
    get_team_preset,
    list_company_presets,
    list_team_presets,
)

_SAFE_ID = re.compile(r"[^a-z0-9-]+")
_ALLOWED_PERMISSION_MODES = {"dont_ask", "accept_edits", "auto"}


def state_path() -> Path:
    """Resolve storage lazily so tests and deployments can set it per process."""
    explicit = os.environ.get("CV_COMPANY_STATE_FILE")
    if explicit:
        return Path(explicit).expanduser()
    state_dir = Path(os.environ.get("CODING_VIBE_STATE_DIR", Path.home() / ".coding-vibe"))
    return state_dir / "company.json"


def _safe_id(value: str, fallback: str = DEFAULT_COMPANY_PRESET_ID) -> str:
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


def _new_company(
    company_preset_id: str,
    *,
    team_preset_id: str | None = None,
    company_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    company_preset = get_company_preset(company_preset_id)
    resolved_team_id = team_preset_id or company_preset["default_team_preset_id"]
    get_team_preset(resolved_team_id)  # validate before writing state
    resolved_id = _safe_id(company_id or company_preset_id, company_preset_id)
    return {
        "id": resolved_id,
        "company_preset_id": company_preset_id,
        "team_preset_id": resolved_team_id,
        "name": (name or company_preset["name"]).strip()[:120],
        "avatar": DEFAULT_AVATAR,
        "qoder_session_id": _session_id(resolved_id),
        # This allows a user-approved company run to complete without a click
        # per local file edit, while never selecting a bypass mode.
        "permission_mode": "accept_edits",
    }


def _default_state() -> dict[str, Any]:
    company = _new_company(DEFAULT_COMPANY_PRESET_ID, team_preset_id=DEFAULT_TEAM_PRESET_ID)
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
    # Atomic replacement prevents a concurrent dashboard refresh seeing partial JSON.
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
    """Read both the new two-layer shape and the old one-layer persisted shape."""
    company_preset_id = raw.get("company_preset_id")
    if not isinstance(company_preset_id, str):
        # Older state called a company profile simply ``preset_id``.
        company_preset_id = raw.get("preset_id") if isinstance(raw.get("preset_id"), str) else DEFAULT_COMPANY_PRESET_ID
    try:
        company_preset = get_company_preset(company_preset_id)
    except KeyError:
        company_preset_id = DEFAULT_COMPANY_PRESET_ID
        company_preset = get_company_preset(company_preset_id)

    team_preset_id = raw.get("team_preset_id")
    if not isinstance(team_preset_id, str):
        team_preset_id = company_preset["default_team_preset_id"]
    try:
        get_team_preset(team_preset_id)
    except KeyError:
        team_preset_id = company_preset["default_team_preset_id"]

    company_id = _safe_id(str(raw.get("id") or fallback_id), company_preset_id)
    permission_mode = str(raw.get("permission_mode") or "accept_edits")
    if permission_mode not in _ALLOWED_PERMISSION_MODES:
        permission_mode = "accept_edits"
    return {
        "id": company_id,
        "company_preset_id": company_preset_id,
        "team_preset_id": team_preset_id,
        "name": str(raw.get("name") or company_preset["name"]).strip()[:120] or company_preset["name"],
        "avatar": str(raw.get("avatar") or DEFAULT_AVATAR),
        "qoder_session_id": _normalise_session_id(raw.get("qoder_session_id"), company_id),
        "permission_mode": permission_mode,
    }


def get_active_company() -> dict[str, Any]:
    """Return the selected company, repairing malformed persisted state safely."""
    state = _load()
    active_id = _safe_id(str(state.get("active_company_id") or DEFAULT_COMPANY_PRESET_ID))
    raw = state.get("companies", {}).get(active_id)
    if not isinstance(raw, dict):
        raw = _new_company(DEFAULT_COMPANY_PRESET_ID, company_id=active_id)
    return _normalise_company(raw, active_id)


def _persist_active(company: dict[str, Any]) -> dict[str, Any]:
    state = _load()
    state.setdefault("companies", {})[company["id"]] = company
    state["active_company_id"] = company["id"]
    _save(state)
    return deepcopy(company)


def activate_company_preset(
    company_preset_id: str,
    *,
    team_preset_id: str | None = None,
    company_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Create/select a company profile and persist its active employee team.

    Returning to an existing company preserves its avatar, session, and prior
    team selection.  Selecting a new company uses that profile's default team
    unless the caller explicitly supplies a team preset.
    """
    company_preset = get_company_preset(company_preset_id)  # validate before writing
    resolved_id = _safe_id(company_id or company_preset_id, company_preset_id)
    state = _load()
    existing_raw = state.setdefault("companies", {}).get(resolved_id)
    existing = _normalise_company(existing_raw, resolved_id) if isinstance(existing_raw, dict) else None

    resolved_team_id = team_preset_id
    if resolved_team_id is None and existing and existing["company_preset_id"] == company_preset_id:
        resolved_team_id = existing["team_preset_id"]
    resolved_team_id = resolved_team_id or company_preset["default_team_preset_id"]
    company = _new_company(
        company_preset_id,
        team_preset_id=resolved_team_id,
        company_id=resolved_id,
        name=name or (existing and existing["name"]),
    )
    if existing and existing["company_preset_id"] == company_preset_id:
        company["avatar"] = existing["avatar"]
        company["qoder_session_id"] = existing["qoder_session_id"]
        company["permission_mode"] = existing["permission_mode"]
    state["companies"][company["id"]] = company
    state["active_company_id"] = company["id"]
    _save(state)
    return deepcopy(company)


def select_team_preset(team_preset_id: str) -> dict[str, Any]:
    """Switch the active company's employee preset without replacing its session."""
    get_team_preset(team_preset_id)  # validate before mutating state
    company = get_active_company()
    company["team_preset_id"] = team_preset_id
    return _persist_active(company)


def activate_preset(preset_id: str, *, company_id: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Backward-compatible one-click company selection for older clients."""
    return activate_company_preset(preset_id, company_id=company_id, name=name)


def update_active_avatar(avatar_url: str) -> dict[str, Any]:
    """Persist the already-validated user avatar for the active company."""
    if not avatar_url or len(avatar_url) > 2_000_000:
        raise ValueError("avatar URL is empty or too large")
    company = get_active_company()
    company["avatar"] = avatar_url
    return _persist_active(company)


def active_dispatch_context() -> dict[str, Any]:
    """Build trusted CEO/Qoder context from the active company and team pair."""
    company = get_active_company()
    company_preset = get_company_preset(company["company_preset_id"])
    team_preset = get_team_preset(company["team_preset_id"])
    return {
        "mode": "company",
        "company_id": company["id"],
        "company_name": company["name"],
        "company_preset_id": company["company_preset_id"],
        "team_preset_id": company["team_preset_id"],
        "team_name": team_preset["name"],
        # Keep this alias for adapters that previously read one preset field.
        "preset_id": company["company_preset_id"],
        "roles": deepcopy(team_preset["roles"]),
        "ceo_prompt": build_ceo_prompt(company_preset, team_preset),
        "use_cli": True,
        "persistent_cli": True,
        "session_id": company["qoder_session_id"],
        "permission_mode": company["permission_mode"],
        "backend": "qoder",
    }


def receptionist_routing_brief() -> str:
    """Return the non-secret active context injected into Yellow Sheep's router."""
    context = active_dispatch_context()
    roles = ", ".join(
        f"{role_id} ({role['label']})" for role_id, role in context["roles"].items()
    )
    return (
        "Active handoff destination for this call: "
        f"company={context['company_name']} [{context['company_preset_id']}]; "
        f"employee_team={context['team_name']} [{context['team_preset_id']}]; "
        f"available_roles={roles}. If and only if the caller has an explicit "
        "software task, dispatch it to this CEO and this selected employee team."
    )


def public_company_state() -> dict[str, Any]:
    """Return safe dashboard data without exposing the CEO or worker prompts."""
    company = get_active_company()
    company_preset = get_company_preset(company["company_preset_id"])
    team_preset = get_team_preset(company["team_preset_id"])
    active = {
        "id": company["id"],
        "name": company["name"],
        "company_preset_id": company["company_preset_id"],
        # Legacy name retained so an older client can still display the company.
        "preset_id": company["company_preset_id"],
        "team_preset_id": company["team_preset_id"],
        "team_name": team_preset["name"],
        "avatar": company["avatar"],
        "permission_mode": company["permission_mode"],
        "type": company_preset["type"],
        "tagline": company_preset["tagline"],
        "roles": list(team_preset["roles"]),
        "role_profiles": [
            {
                "id": role_id,
                "label": role["label"],
                "description": role["description"],
            }
            for role_id, role in team_preset["roles"].items()
        ],
    }
    company_presets = list_company_presets()
    return {
        "active": active,
        "company_presets": company_presets,
        "team_presets": list_team_presets(),
        # Compatibility fields for a client that has not yet received the new UI.
        "presets": company_presets,
    }
