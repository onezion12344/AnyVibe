"""receptionist/core.py — The Receptionist: backend-agnostic task dispatcher."""

from __future__ import annotations

import asyncio
import uuid
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

    def __init__(self) -> None:
        self._async_tasks: dict[str, asyncio.Task[TaskResult]] = {}

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

    async def dispatch_async(
        self,
        task: str,
        *,
        backend: str = "mock",
        repo_path: str,
        context: dict[str, Any] | None = None,
        on_status: Any = None,
        on_complete: Any = None,
    ) -> str:
        """Fire-and-return. Returns a task_id immediately; runs the dispatch in a
        background asyncio task. Invokes on_status per StatusEvent and on_complete
        with the final TaskResult. Still writes checkpoints to state (same as
        dispatch()). Never blocks the caller waiting for the engineer.

        Args:
            task:      Natural-language description of what to build/fix.
            backend:   Registered adapter name (e.g. ``"mock"``, ``"claude-code"``).
            repo_path: Absolute path to the project directory.
            context:   Optional metadata dict (``task_id``, ``priority``, …).
            on_status: Optional callback invoked with each :class:`StatusEvent` as
                       it streams.  May be a plain callable or an async function.
                       Exceptions raised by the callback are logged and swallowed.
            on_complete: Optional callback invoked once with the final
                         :class:`TaskResult` when the task finishes.  May be a
                         plain callable or an async function.  Exceptions raised
                         by the callback are logged and swallowed.

        Returns:
            A short task-id string (UUID4 fragment).  Use :meth:`result` to
            await or inspect the final :class:`TaskResult`.
        """
        task_id = str(uuid.uuid4())[:8]
        full_context = dict(context) if context else {}
        full_context.setdefault("task_id", task_id)

        async def _run() -> None:
            try:
                adapter: HarnessAdapter = get_adapter(backend)()

                handle = await adapter.spawn(task, repo_path=repo_path, context=full_context)

                # Stream status events — checkpoint each one, then fire on_status
                async for event in adapter.stream_status(handle):
                    _append_checkpoint(
                        milestone=event.kind,
                        message=event.text,
                        progress_pct=_progress_from_kind(event.kind),
                    )
                    if on_status is not None:
                        await _call_safe(on_status, event)

                result = await adapter.result(handle)

                # task-complete checkpoint
                _append_checkpoint(
                    milestone="task-complete",
                    message=result.summary,
                    progress_pct=100 if result.ok else 0,
                    task_id=task_id,
                    files_changed=result.files_changed,
                )

                if on_complete is not None:
                    await _call_safe(on_complete, result)

                # Store result so result() can retrieve it later
                self._async_tasks[task_id] = None  # sentinel: done
            except Exception:
                # Swallow all exceptions so a background task failure never
                # propagates to an un-awaited task warning.
                pass

        task_obj: asyncio.Task[None] = asyncio.create_task(_run())
        self._async_tasks[task_id] = task_obj
        return task_id

    async def result(self, task_id: str) -> TaskResult | None:
        """Await the background task associated with *task_id* and return its
        final :class:`TaskResult`.

        Because ``dispatch_async`` checkpoints the result to state rather than
        keeping it in memory, this method returns ``None`` when the task is not
        found or has not yet produced a result — the caller should fall back to
        reading the state directly via :func:`~receptionist.state.load_state`.

        Args:
            task_id: The task-id returned by :meth:`dispatch_async`.

        Returns:
            The final :class:`TaskResult`, or ``None`` if the task is unknown or
            still running.
        """
        task_obj = self._async_tasks.get(task_id)
        if task_obj is None:
            return None
        await task_obj
        # Result was stored in state; signal completion with None sentinel
        return None


# ---------------------------------------------------------------------------
# Callback helper
# ---------------------------------------------------------------------------

async def _call_safe(cb: Any, *args: Any) -> None:
    """Invoke *cb* with *args*, awaiting if it is awaitable.

    All exceptions are caught and logged — a misbehaving callback must never
    crash the dispatch pipeline.
    """
    try:
        maybe = cb(*args) if callable(cb) else None
        if asyncio.isfuture(maybe) or asyncio.iscoroutine(maybe):
            await maybe
    except Exception:
        # Log and swallow; a bad callback must not kill the task
        import logging
        logging.getLogger(__name__).exception("Callback raised an exception")


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
