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
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from receptionist.adapters.qoder import QoderAdapter
from qoder_company.observer import CompanyObserver, CEO_ROLE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["company"])

# In-progress run registry: run_id → {"task": str, "started_at": float, …}
_runs: dict[str, dict[str, Any]] = {}


def _check_auth(request: Request) -> None:
    """Enforce CV_API_TOKEN if configured; mirrors server._check_auth."""
    from web.server import CV_API_TOKEN  # avoid circular at module level  # noqa: PLC0415
    import hmac as _hmac
    if CV_API_TOKEN:
        token = request.headers.get("x-cv-token") or request.query_params.get("token")
        if not token or not _hmac.compare_digest(token, CV_API_TOKEN):
            raise HTTPException(401, "Missing or invalid API token")


@router.post("/api/company/run")
async def company_run(request: Request, background_tasks: BackgroundTasks, body: dict[str, Any] | None = None):
    """Spawn a fixture-mode QoderAdapter run and drive the observer.

    Request body (all optional)::

        {
            "task": "natural-language task description",   # default: quick_sort demo
            "repo_path": "/path/to/repo",                  # default: /tmp/cv-demo
            "fixture_path": "/path/to/qoder_company_demo.jsonl",  # default: CV_QODER_FIXTURE
            "run_id": "my-run-id"                          # auto-generated if omitted
        }

    Returns immediately with a ``run_id``; the observer drives in the background.
    Card-ops are pushed to connected board clients via the signaling WS.
    """
    _check_auth(request)
    body = body or {}
    task: str = body.get("task") or "Write a quick_sort function in Python (with docstring, type hints, tests)"
    repo_path: str = body.get("repo_path") or "/tmp/cv-demo"
    fixture_path: str | None = body.get("fixture_path") or os.environ.get("CV_QODER_FIXTURE")
    run_id: str = body.get("run_id") or str(uuid.uuid4())[:8]

    adapter = QoderAdapter(fixture_path=fixture_path or "")

    run_info: dict[str, Any] = {
        "run_id": run_id,
        "task": task,
        "repo_path": repo_path,
        "fixture_path": fixture_path,
        "started_at": time.time(),
        "status": "running",
        "observer": None,   # set once background task has the observer
    }
    _runs[run_id] = run_info

    # ── Background task: drive the observer ───────────────────────────────────
    async def _drive() -> None:
        observer = CompanyObserver(adapter=adapter)
        run_info["observer"] = observer
        try:
            await observer.run(task, repo_path=repo_path)
        except Exception as exc:
            run_info["error"] = str(exc)
            logger = __import__("logging").getLogger(__name__)
            logger.error("[company] run %s error: %s", run_id, exc)
        finally:
            run_info["status"] = "done"
            run_info["finished_at"] = time.time()

    asyncio.create_task(_drive())

    return {
        "run_id": run_id,
        "status": "running",
        "task": task,
        "fixture_mode": bool(fixture_path),
    }


@router.get("/api/company")
async def company_status(request: Request, run_id: str | None = None):
    """Return company status for a given *run_id* (or the latest run)."""
    _check_auth(request)
    if run_id and run_id not in _runs:
        return JSONResponse({"error": f"run_id {run_id!r} not found"}, status_code=404)

    target = _runs.get(run_id) if run_id else (max(_runs.values(), key=lambda r: r["started_at"]) if _runs else None)
    if target is None:
        return {"runs": [], "message": "No runs yet. POST /api/company/run to start one."}

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
    }
