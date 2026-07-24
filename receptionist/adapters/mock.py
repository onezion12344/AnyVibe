"""receptionist/adapters/mock.py — In-memory MockAdapter for testing."""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult


class MockAdapter(HarnessAdapter):
    """A fully in-memory adapter that returns canned events and a canned result.

    Every call to `spawn()` gets its own handle and a fresh event sequence.
    No subprocess, no disk — completely deterministic and fast.

    Register with key ``"mock"`` via `register_adapter(MockAdapter)`.
    """

    name = "mock"

    # Default canned sequence — tests can patch _default_events / _default_result
    # on the class or a per-instance basis.
    _default_events: list[StatusEvent] = [
        StatusEvent(kind="progress", text="Starting mock task…"),
        StatusEvent(kind="message", text="Reading source files"),
        StatusEvent(kind="tool", text="apply_patch: src/foo.py"),
        StatusEvent(kind="progress", text="Running tests…"),
        StatusEvent(kind="message", text="All tests passed"),
        StatusEvent(kind="done", text="Mock task complete"),
    ]

    _default_result: TaskResult = TaskResult(
        ok=True,
        summary="Mock task completed successfully",
        files_changed=["src/foo.py"],
        raw="MockAdapter: done",
    )

    def __init__(
        self,
        events: list[StatusEvent] | None = None,
        result: TaskResult | None = None,
        delay: float = 0.0,
    ) -> None:
        self._events = events if events is not None else list(self._default_events)
        self._result = result if result is not None else self._default_result
        self._delay = delay  # seconds between events; 0 = fire immediately

        # Shared runtime state (per-process)
        self._store: dict[str, dict] = {}

    async def spawn(self, task: str, *, repo_path: str, context: dict | None = None) -> str:
        handle = str(uuid.uuid4())
        self._store[handle] = {
            "task": task,
            "repo_path": repo_path,
            "context": context or {},
            "status": "running",
        }
        return handle

    async def stream_status(self, handle: str) -> AsyncIterator[StatusEvent]:
        store = self._store.get(handle)
        if store is None:
            raise KeyError(f"Unknown handle: {handle!r}")

        store["status"] = "streaming"
        for event in self._events:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield event

        store["status"] = "stream_done"

    async def result(self, handle: str) -> TaskResult:
        store = self._store.get(handle)
        if store is None:
            return TaskResult(
                ok=False,
                summary=f"Unknown handle: {handle!r}",
                files_changed=[],
                raw=f"handle {handle!r} not found",
            )
        store["status"] = "done"
        return self._result

    async def cancel(self, handle: str) -> None:
        store = self._store.get(handle)
        if store:
            store["status"] = "cancelled"
