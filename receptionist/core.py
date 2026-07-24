"""receptionist/core.py — The Receptionist: backend-agnostic task dispatcher."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult
from receptionist.registry import get_adapter
from receptionist.state import load_state, save_state


# ---------------------------------------------------------------------------
# Engineer directive — the default "fan out into many parallel subagents"
# preamble prepended to every task before it reaches the harness adapter.
# ---------------------------------------------------------------------------

#: Built-in default directive. Worded harness-neutrally, but lands well for
#: claude-code (which exposes a Task/subagent tool). The receptionist prepends
#: this to the task so the engineer treats parallel decomposition — not a single
#: sequential pass — as the default working mode.
DEFAULT_ENGINEER_DIRECTIVE = (
    "You are the engineer for this task. By DEFAULT, do NOT attempt it in a single "
    "sequential pass. First decompose the work into independent, parallelizable "
    "workstreams. Then deploy MULTIPLE subagents concurrently — roughly one per "
    "workstream — using your harness's parallel-agent capability (for example, the "
    "Task / subagent tool if your harness provides one), so the workstreams run at "
    "the same time rather than one after another. Give each subagent a self-contained "
    "brief and a clearly scoped deliverable. When the subagents return, converge their "
    "outputs, resolve conflicts, and independently verify the combined result (build, "
    "tests, and a review pass) before reporting done. Prefer this fan-out-then-converge "
    "approach; fall back to a single sequential pass only when the task is genuinely "
    "atomic and cannot be meaningfully parallelized."
)

#: Environment variable that overrides the built-in default directive.
_DIRECTIVE_ENV_VAR = "CV_ENGINEER_DIRECTIVE"

#: Separator placed between the directive and the original task.
_DIRECTIVE_SEP = "\n\n---\n\n"

#: Sentinel marking "no per-dispatch override supplied" — distinct from an
#: explicit ``None`` (use built-in default) or ``""`` (disable the directive).
_UNSET: Any = object()


def _coerce_directive(value: str | None) -> str:
    """Resolve a raw directive value to the actual directive text.

    ``None`` → the ``CV_ENGINEER_DIRECTIVE`` env var if set, else the built-in
    default. Any string (including ``""`` to disable) is used verbatim.
    """
    if value is None:
        env = os.environ.get(_DIRECTIVE_ENV_VAR)
        return env if env is not None else DEFAULT_ENGINEER_DIRECTIVE
    return value


def _compose_task(task: str, directive: str) -> str:
    """Prepend *directive* to *task*. Empty/blank directive → *task* unchanged."""
    if not directive:
        return task
    return f"{directive}{_DIRECTIVE_SEP}{task}"


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

    def __init__(self, engineer_directive: str | None = None) -> None:
        """Create a Receptionist.

        Args:
            engineer_directive: Default fan-out preamble prepended to every task
                before it reaches the adapter.

                * ``None`` (default) — resolve at dispatch time to the
                  ``CV_ENGINEER_DIRECTIVE`` env var if set, else the built-in
                  :data:`DEFAULT_ENGINEER_DIRECTIVE`.
                * ``""`` (empty string) — disable the directive; tasks pass
                  through unchanged.
                * any other string — use it verbatim as the directive.
        """
        self._async_tasks: dict[str, asyncio.Task[TaskResult]] = {}
        self._engineer_directive = engineer_directive

    def _resolve_directive(self, override: str | None) -> str:
        """Pick the effective directive text for a dispatch.

        Precedence: per-dispatch *override* (if supplied, i.e. not ``_UNSET``)
        beats the instance default, which in turn resolves ``None`` via
        ``CV_ENGINEER_DIRECTIVE`` / the built-in default.
        """
        raw = self._engineer_directive if override is _UNSET else override
        return _coerce_directive(raw)

    async def dispatch(
        self,
        task: str,
        *,
        backend: str = "mock",
        repo_path: str,
        context: dict[str, Any] | None = None,
        engineer_directive: str | None = _UNSET,
    ) -> TaskResult:
        """Run *task* in *backend* and return its final :class:`TaskResult`.

        Args:
            task:      Natural-language description of what to build/fix.
            backend:   Registered adapter name (e.g. ``"mock"``, ``"claude-code"``).
            repo_path: Absolute path to the project directory.
            context:   Optional metadata dict (``task_id``, ``priority``, …).
            engineer_directive: Per-dispatch override of the fan-out directive.
                Omit to use the instance default; pass ``""`` to disable for
                this call; pass a string to override for this call.
        """
        adapter: HarnessAdapter = get_adapter(backend)()

        directive = self._resolve_directive(engineer_directive)
        composed_task = _compose_task(task, directive)

        handle = await adapter.spawn(composed_task, repo_path=repo_path, context=context)

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
        engineer_directive: str | None = _UNSET,
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
            engineer_directive: Per-dispatch override of the fan-out directive.
                Omit to use the instance default; pass ``""`` to disable for
                this call; pass a string to override for this call.

        Returns:
            A short task-id string (UUID4 fragment).  Use :meth:`result` to
            await or inspect the final :class:`TaskResult`.
        """
        task_id = str(uuid.uuid4())[:8]
        full_context = dict(context) if context else {}
        full_context.setdefault("task_id", task_id)

        directive = self._resolve_directive(engineer_directive)
        composed_task = _compose_task(task, directive)

        async def _run() -> None:
            try:
                adapter: HarnessAdapter = get_adapter(backend)()

                handle = await adapter.spawn(composed_task, repo_path=repo_path, context=full_context)

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
