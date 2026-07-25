"""web/qoder_company_routes.py — FastAPI routes for the Qoder company demo.

Endpoints
---------
POST /api/company/run  — spawn the QoderAdapter (fixture mode) and drive the
                          CompanyObserver so card-ops stream to any connected
                          board client via the existing signaling WS.
GET  /api/company      — company status (roles seen, card count, last op).

Mounted in server.py as ``app.include_router(company_router)``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from receptionist.adapters.qoder import QoderAdapter, _SDK_AVAILABLE
from web.auth import is_valid_token
from qoder_company.company_state import (
    active_dispatch_context,
    activate_preset,
    get_active_company,
    public_company_state,
    update_active_avatar,
)
from qoder_company.network import DEFAULT_AVATAR, NetworkGraph
from qoder_company.observer import CompanyObserver, CEO_ROLE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["company"])

# In-progress run registry: run_id → {"task": str, "started_at": float, …}
_runs: dict[str, dict[str, Any]] = {}
_DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "receptionist" / "adapters" / "fixtures" / "qoder_company_demo.jsonl"
_AVATAR_DIR = Path(os.environ.get("CV_AVATAR_DIR", Path(__file__).resolve().parent / "static" / "uploads"))
_AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_TYPES = {
    "image/png": (".png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": (".jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "image/gif": (".gif", lambda b: b.startswith(b"GIF8")),
    "image/webp": (".webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}
_USER_AVATAR = DEFAULT_AVATAR


def _check_auth(request: Request) -> None:
    """Enforce CV_API_TOKEN if configured; mirrors server._check_auth."""
    from web.server import CV_API_TOKEN  # avoid circular at module level  # noqa: PLC0415
    if CV_API_TOKEN:
        token = request.headers.get("x-cv-token") or request.query_params.get("token")
        if not is_valid_token(token):
            raise HTTPException(401, "Missing or invalid API token")


def _latest_run(company_id: str | None = None) -> dict[str, Any] | None:
    """Return the most recent run for the selected company, if one exists."""
    candidates = list(_runs.values())
    if company_id:
        candidates = [run for run in candidates if run.get("company_id") == company_id]
    return max(candidates, key=lambda run: run["started_at"]) if candidates else None


async def start_company_run(
    task: str | None = None,
    *,
    repo_path: str | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start one active-company Qoder run and return its public run metadata.

    This is used by both the HTTP route and the voice dispatcher.  Keeping the
    construction here guarantees the kanban observes the same Qoder process
    that executes work instead of launching a second, unrelated demo run.
    """
    body = body or {}
    active_company = get_active_company()
    context = active_dispatch_context()
    resolved_task = task or body.get("task") or "Write a quick_sort function in Python (with docstring, type hints, tests)"
    if not isinstance(resolved_task, str) or not resolved_task.strip():
        raise ValueError("task must be a non-empty string")
    resolved_repo = repo_path or body.get("repo_path") or "/tmp/cv-demo"
    if not isinstance(resolved_repo, str):
        raise ValueError("repo_path must be a string")
    mode = body.get("mode") or context["mode"]
    if mode not in {"company", "task"}:
        raise ValueError("mode must be 'company' or 'task'")
    context["mode"] = mode

    # The preset owns the CEO contract and permission profile.  Optional roles
    # and model are useful for local experiments, but never replace the safety
    # fields selected by the active company.
    roles = body.get("roles", context["roles"])
    if not isinstance(roles, dict):
        raise ValueError("roles must be an object keyed by agent name")
    context["roles"] = roles
    model = body.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("model must be a string")
    if model:
        context["model"] = model
    fixture_path: str | None = body.get("fixture_path") or os.environ.get("CV_QODER_FIXTURE")
    requested_cli = body.get("use_cli")
    if requested_cli is not None and not isinstance(requested_cli, bool):
        raise ValueError("use_cli must be a boolean")
    use_cli = context["use_cli"] if requested_cli is None else requested_cli
    # Legacy fixture testing stays available, but an active preset defaults to
    # actual qodercli execution rather than silently replaying a canned run.
    if not fixture_path and not _SDK_AVAILABLE and not use_cli:
        fixture_path = str(_DEFAULT_FIXTURE)
    run_id: str = body.get("run_id") or str(uuid.uuid4())[:8]
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")

    adapter = QoderAdapter(
        fixture_path=fixture_path or "",
        default_mode=mode,
        default_company_id=active_company["id"],
        cli_enabled=use_cli,
    )
    run_info: dict[str, Any] = {
        "run_id": run_id,
        "task": resolved_task,
        "repo_path": resolved_repo,
        "fixture_path": fixture_path,
        "roles": roles,
        "model": model,
        "company_id": active_company["id"],
        "preset_id": active_company["preset_id"],
        "started_at": time.time(),
        "status": "running",
        "observer": None,
    }
    _runs[run_id] = run_info

    async def _drive() -> None:
        observer = CompanyObserver(
            adapter=adapter,
            network=NetworkGraph(user_avatar=active_company["avatar"]),
        )
        run_info["observer"] = observer
        try:
            await observer.run(resolved_task, repo_path=resolved_repo, context=context)
        except Exception as exc:
            run_info["error"] = str(exc)
            logger.error("[company] run %s error: %s", run_id, exc)
        finally:
            run_info["status"] = "done"
            run_info["finished_at"] = time.time()

    asyncio.create_task(_drive())
    return {
        "run_id": run_id,
        "status": "running",
        "task": resolved_task,
        "mode": mode,
        "company_id": active_company["id"],
        "preset_id": active_company["preset_id"],
        "roles": list(roles),
        "model": model,
        "fixture_mode": bool(fixture_path),
        "backend": "fixture" if fixture_path else ("sdk" if _SDK_AVAILABLE else "cli"),
        "session_scope": "persistent-company" if mode == "company" and not fixture_path else "single-run",
    }


@router.get("/api/company/presets")
async def company_presets(request: Request):
    """List selectable company shapes without exposing their CEO prompts."""
    _check_auth(request)
    return public_company_state()


@router.get("/api/company/active")
async def company_active(request: Request):
    """Return the selected company and its public role roster."""
    _check_auth(request)
    return public_company_state()


@router.put("/api/company/active")
async def select_company_preset(request: Request, body: dict[str, Any] | None = None):
    """Switch to a known preset; the new company receives its own session."""
    _check_auth(request)
    preset_id = (body or {}).get("preset_id")
    if not isinstance(preset_id, str):
        raise HTTPException(400, "preset_id must be a string")
    try:
        activate_preset(preset_id)
    except KeyError:
        raise HTTPException(404, f"Unknown company preset: {preset_id}") from None
    return public_company_state()


@router.post("/api/company/run")
async def company_run(request: Request, body: dict[str, Any] | None = None):
    """Start the active company's Qoder run and drive its live observer.

    Request body (all optional)::

        {
            "task": "natural-language task description",   # default: quick_sort demo
            "repo_path": "/path/to/repo",                  # default: /tmp/cv-demo
            "fixture_path": "/path/to/qoder_company_demo.jsonl",  # default: CV_QODER_FIXTURE
            "mode": "company|task",                       # default: active company
            "roles": {"engineer": "Implement and test code"}, # local experiment override
            "model": "optional-qoder-model",               # optional Qoder model
            "use_cli": false,                               # fixture/test override only
            "run_id": "my-run-id"                          # auto-generated if omitted
        }

    The selected preset supplies the CEO prompt, persistent Qoder session and
    role roster. Returns immediately with a ``run_id``; the observer streams
    card and network events to connected board clients in the background.
    """
    _check_auth(request)
    try:
        return await start_company_run(body=body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/company")
async def company_status(request: Request, run_id: str | None = None):
    """Return company status for a given *run_id* (or the latest run)."""
    _check_auth(request)
    if run_id and run_id not in _runs:
        return JSONResponse({"error": f"run_id {run_id!r} not found"}, status_code=404)

    company = get_active_company()
    target = _runs.get(run_id) if run_id else _latest_run(company["id"])
    if target is None:
        return {
            "runs": [],
            "message": "No runs yet. POST /api/company/run to start one.",
            "network": NetworkGraph(user_avatar=company["avatar"]).snapshot(),
            "company": public_company_state(),
        }

    observer = target.get("observer")
    emitted: list[dict[str, Any]] = observer.emitted if observer else []
    last_op = emitted[-1] if emitted else None

    return {
        "run_id": target["run_id"],
        "status": target.get("status", "unknown"),
        "task": target.get("task", ""),
        "roles": observer.roles if observer else [CEO_ROLE],
        "card_count": observer.card_count if observer else 0,
        "last_op": last_op,
        "emitted_ops": emitted,
        "network": observer.network_snapshot if observer else NetworkGraph(user_avatar=company["avatar"]).snapshot(),
        "company": public_company_state(),
    }


@router.get("/api/company/network")
async def company_network(request: Request, run_id: str | None = None):
    """Return the graph projection without disturbing the role Kanban API."""
    _check_auth(request)
    if run_id and run_id not in _runs:
        return JSONResponse({"error": f"run_id {run_id!r} not found"}, status_code=404)
    company = get_active_company()
    target = _runs.get(run_id) if run_id else _latest_run(company["id"])
    observer = target.get("observer") if target else None
    return {"run_id": target.get("run_id") if target else None, "network": observer.network_snapshot if observer else NetworkGraph(user_avatar=company["avatar"]).snapshot(), "company": public_company_state()}


@router.post("/api/company/avatar")
async def company_avatar(request: Request):
    """Store a user avatar locally and attach it to the current network graph.

    The endpoint accepts raw image bytes (the browser sends a File body), uses
    a random filename, caps size, and verifies common image signatures.  It
    never accepts a caller-provided path or writes outside ``CV_AVATAR_DIR``.
    """
    _check_auth(request)
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].lower()
    spec = _AVATAR_TYPES.get(content_type)
    if spec is None:
        raise HTTPException(415, "Use PNG, JPEG, GIF, or WebP image data")
    payload = await request.body()
    if not payload or len(payload) > _AVATAR_MAX_BYTES:
        raise HTTPException(413, "Avatar must be between 1 byte and 5 MB")
    ext, signature = spec
    if not signature(payload):
        raise HTTPException(400, "Avatar bytes do not match their image type")

    _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    destination = (_AVATAR_DIR / filename).resolve()
    if destination.parent != _AVATAR_DIR.resolve():
        raise HTTPException(400, "Invalid avatar destination")
    destination.write_bytes(payload)
    avatar_url = f"/api/company/avatar/{filename}"

    # The avatar belongs to the active company and follows it across reloads.
    # Attach it to that company's live graph too, if one is currently running.
    global _USER_AVATAR
    _USER_AVATAR = avatar_url
    company = update_active_avatar(avatar_url)
    target = _latest_run(company["id"])
    if target and target.get("observer"):
        target["observer"].set_user_avatar(avatar_url)
    return {"avatar_url": avatar_url, "fallback": DEFAULT_AVATAR}


@router.get("/api/company/avatar/{filename}")
async def company_avatar_file(filename: str):
    """Serve only generated UUID avatar files from the local avatar directory."""
    if Path(filename).name != filename or Path(filename).suffix.lower() not in {".png", ".jpg", ".gif", ".webp"}:
        raise HTTPException(404, "Avatar not found")
    path = (_AVATAR_DIR / filename).resolve()
    if path.parent != _AVATAR_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "Avatar not found")
    return FileResponse(str(path))
