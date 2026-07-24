"""receptionist/adapters/openopc.py — OpenOPC subprocess adapter.

Wraps the ``opc exec … --stream-json`` invocation from ``agent.py`` behind
the standard :class:`~receptionist.adapters.base.HarnessAdapter` interface.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import AsyncIterator

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

# OpenOPC project root — where `uv run opc` must execute. Overridable via env.
OPC_ROOT = os.environ.get("OPC_ROOT") or str(Path.home() / "Projects" / "OpenOPC")

# Module-level handle store (per-process, shared across instances)
_handles: dict[str, dict] = {}


def _store_failure(handle: str, error: str) -> None:
    _handles[handle] = {
        "status": "failed",
        "events": [StatusEvent(kind="error", text=error)],
        "_error": error,
    }


class OpenOPCAdapter(HarnessAdapter):
    """Spawns ``opc exec … --stream-json`` and parses its output.

    If ``opc`` is not on PATH the handle is created in a failed state so
    callers can still call :meth:`result` without crashing.
    """

    name = "openopc"

    def __init__(self, *, timeout: float = 300.0, opc_root: str | None = None) -> None:
        self._timeout = timeout
        self._opc_root = opc_root or OPC_ROOT

    async def spawn(self, task: str, *, repo_path: str, context: dict | None = None) -> str:
        handle = str(uuid.uuid4())

        # Pre-flight: can we run opc via uv in the OpenOPC project root?
        # (opc has no --version; `--help` always exits 0. Must run in OPC_ROOT
        # so `uv run` resolves the OpenOPC project/venv, not the target repo.)
        try:
            proc = await asyncio.create_subprocess_exec(
                "uv", "run", "opc", "--help",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._opc_root),
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                raise RuntimeError("`uv run opc --help` returned non-zero")
        except (FileNotFoundError, TimeoutError, RuntimeError) as exc:
            _store_failure(handle, f"OpenOPC pre-flight failed: {exc}")
            return handle

        # Pre-flight passed — create the handle entry before handing to _run
        _handles[handle] = {"status": "pending", "events": [], "_stream_idx": 0}

        project = context.get("project", "demo") if context else "demo"
        # Guard against argv flag smuggling: `project` is the value of opc's
        # -p flag, so a leading dash could be parsed as a flag.
        if not project or project.startswith("-"):
            _store_failure(handle, f"Invalid project name: {project!r}")
            return handle
        asyncio.create_task(self._run(handle, task, repo_path, project))
        return handle

    async def _run(self, handle: str, task: str, repo_path: str, project: str) -> None:
        cmd = [
            "uv", "run", "opc", "exec",
            "-p", project,
            "--mode", "org",
            "--org", "coding-vibe",
            "--agent", "claude_code",
            "--stream-json",
            "--",
            task,
        ]

        _handles[handle]["status"] = "running"
        stderr_drainer: asyncio.Task[None] | None = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._opc_root),
            )

            # Drain stderr concurrently to prevent the child from blocking on a
            # full ~64 KB pipe buffer.
            async def _drain_stderr() -> None:
                async for _ in proc.stderr:
                    pass

            stderr_drainer = asyncio.create_task(_drain_stderr())

            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                typ = event.get("type", "")
                payload = event.get("payload", {})

                if typ in ("message", "final"):
                    content = payload.get("content") or payload.get("response", "")
                    if content:
                        _handles[handle]["events"].append(
                            StatusEvent(kind="message", text=content[:500])
                        )
                elif typ == "error":
                    _handles[handle]["events"].append(
                        StatusEvent(kind="error", text=payload.get("error", str(payload))),
                    )
                    break

            await asyncio.wait_for(proc.wait(), timeout=self._timeout)

        except asyncio.TimeoutError:
            _handles[handle]["events"].append(
                StatusEvent(kind="error", text=f"Timed out after {self._timeout}s"),
            )
        except Exception as exc:
            _handles[handle]["events"].append(
                StatusEvent(kind="error", text=str(exc)),
            )
        finally:
            _handles[handle]["status"] = "done"
            # Ensure the stderr drainer finishes cleanly
            if stderr_drainer is not None:
                try:
                    await asyncio.wait_for(stderr_drainer, timeout=1.0)
                except asyncio.TimeoutError:
                    stderr_drainer.cancel()

    async def stream_status(self, handle: str) -> AsyncIterator[StatusEvent]:
        store = _handles.get(handle)
        if store is None:
            raise KeyError(f"Unknown handle: {handle!r}")

        while store["status"] in ("pending", "running") and not store["events"]:
            await asyncio.sleep(0.05)

        idx = store.get("_stream_idx", 0)
        events = store["events"]
        while idx < len(events):
            yield events[idx]
            idx += 1
        store["_stream_idx"] = idx

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

        while store["status"] not in ("done", "failed"):
            await asyncio.sleep(0.05)

        if store.get("_error"):
            return TaskResult(
                ok=False,
                summary=store["_error"],
                files_changed=[],
                raw=store["_error"],
            )

        messages = [e.text for e in store["events"] if e.kind == "message"]
        errors = [e for e in store["events"] if e.kind == "error"]

        if errors:
            return TaskResult(
                ok=False,
                summary=errors[-1].text,
                files_changed=[],
                raw="\n".join(e.text for e in store["events"]),
            )

        summary = messages[-1] if messages else "OpenOPC task complete"
        return TaskResult(
            ok=True,
            summary=summary,
            files_changed=[],
            raw="\n".join(messages),
        )
