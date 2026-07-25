"""receptionist/adapters/base.py — Abstract harness adapter interface."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class StatusEvent:
    """A single status update emitted by a running harness.

    ``actor`` is the emitting Qoder role when the backend provides it.  It is
    intentionally optional so older adapters remain compatible, but it lets
    the company network distinguish a CEO update from a CS handoff.
    """

    kind: str
    text: str
    actor: str = ""

    # Allowed kinds
    PROGRESS = "progress"
    TOOL = "tool"
    MESSAGE = "message"
    DONE = "done"
    ERROR = "error"

    def __post_init__(self) -> None:
        valid = {"progress", "tool", "message", "done", "error"}
        if self.kind not in valid:
            raise ValueError(f"Invalid StatusEvent kind {self.kind!r}. Must be one of {valid}")


@dataclass
class TaskResult:
    """Final result of a dispatched task."""

    ok: bool
    summary: str
    files_changed: list[str]
    raw: str


class HarnessAdapter(ABC):
    """Thin, backend-pluggable abstraction over any engineer harness.

    Subclasses must set:
        name (class attribute) — registry key, e.g. "claude-code"

    Implement the three async methods; `cancel()` has a sensible default no-op.
    """

    name: str = ""

    @abstractmethod
    async def spawn(self, task: str, *, repo_path: str, context: dict | None = None) -> str:
        """Kick off the task in the harness.

        Args:
            task:    Natural-language description of what to build/fix.
            repo_path: Absolute path to the project directory.
            context: Optional key/value metadata (priority, files, …).

        Returns:
            An opaque *handle id* — feed this to `stream_status()` and `result()`.
        """
        ...

    @abstractmethod
    async def stream_status(self, handle: str) -> AsyncIterator[StatusEvent]:
        """Yield StatusEvents for a running task until it finishes."""
        ...

    @abstractmethod
    async def result(self, handle: str) -> TaskResult:
        """Return the final TaskResult for a completed handle."""
        ...

    async def cancel(self, handle: str) -> None:
        """Best-effort cancellation. Default is a no-op."""
        # Subclasses that support cancellation override this.
        return None
