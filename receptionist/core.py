"""receptionist/core.py — The Receptionist: backend-agnostic task dispatcher."""

from __future__ import annotations

import asyncio
from typing import Any

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult
from receptionist.registry import get_adapter
from receptionist.state import load_state, save_state


def _progress_from_kind(kind: str) -> int:
    """Rough progress estimate for each event kind."""
    return {
        "progress": 25,
        "tool": 50,
        "message": 60,
        "done": 100,
        "error": 0,
    }.get(kind, 50)


class Receptionist:
    """Dispatch a task to any registered backend and collect the result.

    The full lifecycle:

    1. ``spawn()`` — get an opaque handle
    2. ``stream_status()`` — yield each event as it arrives, writing a
       checkpoint to ``~/.coding-vibe/session.json`` for every event
    3. ``result()`` — block until the adapter is done, return ``TaskResult``
    4. Append a ``task-complete`` checkpoint so the MCP/hook flow can
       discover completion on the next turn

    The Receptionist itself never calls a specific CLI — it only ever
    goes through :class:`~receptionist.adapters.base.HarnessAdapter`.
    """

    async def dispatch(
        self,
        task: str,
        *,
        backend: str = "mock",
        repo_path: str,
        context: dict[str, Any] | None = None,
    ) -> TaskResult:
        """Run *task* in *backend* and return its final :class:`TaskResult`.

        Args:
            task:      Natural-language description of what to build/fix.
            backend:   Registered adapter name (e.g. ``"mock"``, ``"claude-code"``).
            repo_path: Absolute path to the project directory.
            context:   Optional metadata dict (``task_id``, ``priority``, …).
        """
        adapter: HarnessAdapter = get_adapter(backend)()

        handle = await adapter.spawn(task, repo_path=repo_path, context=context)

        # Step 2: consume every status event and checkpoint it
        async for event in adapter.stream_status(handle):
            _append_checkpoint(
                milestone=event.kind,
                message=event.text,
                progress_pct=_progress_from_kind(event.kind),
            )

        # Step 3: wait for the final result
        result = await adapter.result(handle)

        # Step 4: task-complete checkpoint (mirrors cv_mcp/server.py's
        # complete_delegation behaviour)
        _append_checkpoint(
            milestone="task-complete",
            message=result.summary,
            progress_pct=100 if result.ok else 0,
            task_id=(context or {}).get("task_id"),
            files_changed=result.files_changed,
        )

        return result


# ---------------------------------------------------------------------------
# Thin wrappers around receptionist/state.py, keeping the dependency
# direction clean (core → state, not state → core).
# ---------------------------------------------------------------------------

def _append_checkpoint(
    milestone: str,
    message: str,
    *,
    progress_pct: int = 50,
    task_id: str | None = None,
    files_changed: list[str] | None = None,
) -> dict:
    from receptionist.state import append_checkpoint as _ac
    return _ac(
        milestone=milestone,
        message=message,
        progress_pct=progress_pct,
        task_id=task_id,
        files_changed=files_changed,
    )
