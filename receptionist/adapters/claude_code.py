"""receptionist/adapters/claude_code.py — Claude Code subprocess adapter."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult


class ClaudeCodeAdapter(HarnessAdapter):
    """Spawns `claude -p` in stream-json mode and maps events to StatusEvents.

    Requires the ``claude`` binary on PATH. If it is missing, ``spawn()``
    and ``result()`` will surface a clear :class:`TaskResult` with ``ok=False``
    rather than raising at import time.
    """

    name = "claude-code"

    def __init__(self, *, timeout: float = 300.0) -> None:
        self._timeout = timeout

    async def spawn(self, task: str, *, repo_path: str, context: dict | None = None) -> str:
        handle = str(uuid.uuid4())
        # Pre-flight check: is claude on PATH?
        try:
            proc = await asyncio.create_subprocess_exec(
                "command", "claude", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                raise RuntimeError("claude returned non-zero")
        except (FileNotFoundError, TimeoutError, RuntimeError) as exc:
            _store_failure(handle, str(exc))
            return handle

        # Pre-flight passed — initialise the handle before handing to _run
        _handles[handle] = {"status": "pending", "events": [], "_stream_idx": 0}

        # Launch the real task in the background
        asyncio.create_task(self._run(handle, task, repo_path, context))
        return handle

    async def _run(self, handle: str, task: str, repo_path: str, context: dict | None) -> None:
        cmd = [
            "command", "claude", "-p", task,
            "--verbose",
            "--output-format", "stream-json",
            "-c", repo_path,   # cd into repo_path before running
        ]

        _handles[handle]["status"] = "running"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )

            collected: list[str] = []
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "assistant":
                    # Emit a progress event so the stream is visible
                    msg = event.get("message", {})
                    content_blocks = msg.get("content", [])
                    for block in content_blocks:
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                _handles[handle]["events"].append(
                                    StatusEvent(kind="message", text=text[:500])
                                )
                            break

                elif etype == "result":
                    # Task finished
                    result_text = event.get("result", "")
                    collected.append(result_text)
                    subtype = event.get("subtype", "")
                    is_error = event.get("is_error", False)

                    _handles[handle]["events"].append(
                        StatusEvent(
                            kind="error" if is_error else "done",
                            text=(
                                f"Task failed: {result_text[:200]}"
                                if is_error
                                else f"Task complete: {result_text[:200]}"
                            ),
                        )
                    )
                    break

                elif etype == "system":
                    subtype = event.get("subtype", "")
                    if subtype == "hook_response" and event.get("outcome") == "success":
                        _handles[handle]["events"].append(
                            StatusEvent(kind="progress", text="Hook started")
                        )

            await proc.wait()

        except asyncio.TimeoutError:
            _handles[handle]["events"].append(
                StatusEvent(kind="error", text=f"Timed out after {self._timeout}s")
            )
        except Exception as exc:
            _handles[handle]["events"].append(
                StatusEvent(kind="error", text=str(exc))
            )
        finally:
            _handles[handle]["status"] = "done"

    async def stream_status(self, handle: str) -> AsyncIterator[StatusEvent]:
        store = _handles.get(handle)
        if store is None:
            raise KeyError(f"Unknown handle: {handle!r}")

        # Wait for running if not yet started
        while store["status"] in ("pending", "running") and not store["events"]:
            await asyncio.sleep(0.05)

        idx = store.get("_stream_idx", 0)
        events = store["events"]
        while idx < len(events):
            yield events[idx]
            idx += 1
        store["_stream_idx"] = idx

        # If still running, keep watching for new events
        while store["status"] == "running":
            await asyncio.sleep(0.05)
            while idx < len(events):
                yield events[idx]
                idx += 1
            store["_stream_idx"] = idx

    async def result(self, handle: str) -> TaskResult:
        store = _handles.get(handle)
        if store is None:
            return TaskResult(
                ok=False,
                summary="Unknown handle",
                files_changed=[],
                raw=f"handle {handle!r} not found",
            )

        # Wait for completion
        while store["status"] not in ("done", "failed"):
            await asyncio.sleep(0.05)

        if store.get("_error"):
            return TaskResult(
                ok=False,
                summary=store["_error"],
                files_changed=[],
                raw=store["_error"],
            )

        # Reconstruct from events
        messages = [e.text for e in store["events"] if e.kind == "message"]
        done_events = [e for e in store["events"] if e.kind == "done"]
        error_events = [e for e in store["events"] if e.kind == "error"]

        if error_events:
            return TaskResult(
                ok=False,
                summary=error_events[-1].text,
                files_changed=[],
                raw="\n".join(e.text for e in store["events"]),
            )

        summary = done_events[-1].text if done_events else (messages[-1] if messages else "Completed")
        return TaskResult(
            ok=True,
            summary=summary,
            files_changed=[],  # Would need git diff parsing to populate
            raw="\n".join(messages),
        )

    async def cancel(self, handle: str) -> None:
        store = _handles.get(handle)
        if store and store["status"] == "running":
            store["status"] = "cancelled"


# ---------------------------------------------------------------------------
# Module-level handle store (per-process, shared across instances)
# ---------------------------------------------------------------------------

_handles: dict[str, dict] = {}


def _store_failure(handle: str, error: str) -> None:
    _handles[handle] = {
        "status": "failed",
        "events": [StatusEvent(kind="error", text=error)],
        "_error": error,
    }
