"""receptionist/adapters/openopc.py — OpenOPC subprocess adapter.

Wraps the ``opc exec … --stream-json`` invocation from ``agent.py`` behind
the standard :class:`~receptionist.adapters.base.HarnessAdapter` interface.

Staffing pre-flight
-------------------
Before each ``opc exec`` call, ``spawn()`` runs
``uv run python3 scripts/coding-vibe-preset.py --project <project>`` in
``OPC_ROOT``.  The preset script:

1. Writes ``.opc/projects/<project>/company_staffing_defaults.json`` so
   the engine can resolve saved staffing defaults.
2. Creates a pre-confirmed session/task row in
   ``.opc/projects/<project>/tasks.db`` (``recruitment_confirmation_completed:
   True``), thereby bypassing the interactive staffing selection loop.
3. Emits the ``session_id`` as a single UUID line on stdout (exit 0).

``spawn()`` parses that session_id and passes ``--session-id <id>`` to
``opc exec``.  This makes every ``opc exec`` call pick up the already-
confirmed session so company-mode execution proceeds without any manual
staffing prompt.

The pre-step is idempotent (safe if already run) and can be skipped by
setting ``CV_OPENOPC_SKIP_STAFFING=1``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import AsyncIterator

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

# OpenOPC project root — where `uv run opc` must execute. Overridable via env.
OPC_ROOT = os.environ.get("OPC_ROOT") or str(Path.home() / "Projects" / "OpenOPC")

# Module-level handle store (per-process, shared across instances)
_handles: dict[str, dict] = {}

# Subprocess timeouts (seconds)
_PRESET_TIMEOUT = 120
_HELP_TIMEOUT = 30

# Magic stdout marker that the preset emits to communicate session_id back.
# coding-vibe-preset.py prints all human-readable output to stdout; the
# session_id UUID appears as its own line so we can reliably parse it.
_SESSION_ID_RE = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b"
)


def _store_failure(handle: str, error: str) -> None:
    _handles[handle] = {
        "status": "failed",
        "events": [StatusEvent(kind="error", text=error)],
        "_error": error,
    }


def _parse_session_id_from_stdout(stdout: str) -> str | None:
    """Extract the session_id UUID emitted by coding-vibe-preset.py on stdout.

    The preset's main() runs a sync helper via ``loop.run_in_executor`` and
    returns the ``(session_id, task_id)`` tuple — both are UUIDs.  We look
    for UUID-like tokens on the last line of stdout, which is the last-printed
    value in the ``print()`` sequence.
    """
    lines = stdout.strip().splitlines()
    # Prefer the last non-empty line (the most recently-printed output).
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            m = _SESSION_ID_RE.search(stripped)
            if m:
                return m.group(1)
    return None


async def _run_preset(
    opc_root: str,
    project: str,
    timeout: float = _PRESET_TIMEOUT,
) -> tuple[bool, str, str]:
    """Run ``coding-vibe-preset.py`` and return ``(ok, session_id_or_empty, reason)``.

    The preset writes ``company_staffing_defaults.json`` into ``.opc/projects/``
    and seeds ``tasks.db`` with a confirmed session.  Success is signalled by
    exit code 0 with at least one UUID-like token on stdout.
    """
    # Path-traversal / integrity guard: OPC_ROOT is operator config, but validate
    # defensively that the preset script resolves to a real file inside OPC_ROOT.
    opc_root_resolved = Path(opc_root).expanduser().resolve()
    script_path = (opc_root_resolved / "scripts" / "coding-vibe-preset.py").resolve()
    if opc_root_resolved not in script_path.parents or not script_path.is_file():
        return False, "", f"Preset script not found under OPC_ROOT: {script_path}"
    script = str(script_path)
    cmd = ["uv", "run", "python3", script, "--project", project]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=opc_root,
        )
    except FileNotFoundError:
        return False, "", "`uv` not found — cannot run coding-vibe-preset.py"

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except OSError:
            pass
        return (
            False,
            "",
            f"Preset timed out after {timeout}s "
            f"(uv run python3 scripts/coding-vibe-preset.py --project {project})",
        )

    stdout_s = stdout.decode(errors="replace").strip()
    stderr_s = stderr.decode(errors="replace").strip()

    if proc.returncode != 0:
        err = stderr_s or f"preset exited {proc.returncode}"
        return False, "", f"Preset failed (exit {proc.returncode}): {err}"

    session_id = _parse_session_id_from_stdout(stdout_s)
    reason = (
        f"Preset OK — session_id={session_id[:8]}…"
        if session_id
        else "Preset OK but no session_id found in stdout"
    )
    return True, session_id or "", reason


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

        # ── Pre-flight: can we run opc via uv in the OpenOPC project root? ──
        try:
            proc = await asyncio.create_subprocess_exec(
                "uv", "run", "opc", "--help",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._opc_root),
            )
            await asyncio.wait_for(proc.communicate(), timeout=_HELP_TIMEOUT)
            if proc.returncode != 0:
                raise RuntimeError("`uv run opc --help` returned non-zero")
        except (FileNotFoundError, TimeoutError, RuntimeError) as exc:
            _store_failure(handle, f"OpenOPC pre-flight failed: {exc}")
            return handle

        project = context.get("project", "demo") if context else "demo"
        if not project or project.startswith("-"):
            _store_failure(handle, f"Invalid project name: {project!r}")
            return handle

        # ── Staffing pre-step: run coding-vibe-preset.py ───────────────────
        # Ensures the org is confirmed-staffed before opc exec so the engine
        # skips the interactive staffing-selection loop.  Skip with
        #   CV_OPENOPC_SKIP_STAFFING=1
        # if already handled externally.
        skip_staffing = os.environ.get("CV_OPENOPC_SKIP_STAFFING", "") == "1"
        confirmed_session_id = ""

        if not skip_staffing:
            preset_ok, confirmed_session_id, preset_reason = await _run_preset(
                str(self._opc_root), project
            )
            if not preset_ok:
                _store_failure(
                    handle,
                    f"OpenOPC staffing pre-step failed: {preset_reason}",
                )
                return handle
            # confirmed_session_id may be empty if stdout parsing failed but
            # the preset itself succeeded — continue without session_id (will
            # still hit staffing loop, but we won't crash here).
        # else: skip_staffing=True — run opc exec without --session-id

        # ── Build the opc exec command ─────────────────────────────────────
        cmd: list[str] = [
            "uv", "run", "opc", "exec",
            "-p", project,
            "--mode", "org",
            "--org", "coding-vibe",
            "--agent", "claude_code",
            "--stream-json",
        ]
        if confirmed_session_id:
            cmd += ["--session-id", confirmed_session_id]
        cmd += ["--", task]

        # ── Pre-flight passed — create the handle entry before handing to _run
        _handles[handle] = {"status": "pending", "events": [], "_stream_idx": 0}
        asyncio.create_task(self._run(handle, cmd))
        return handle

    async def _run(self, handle: str, cmd: list[str]) -> None:
        _handles[handle]["status"] = "running"
        stderr_drainer: asyncio.Task[None] | None = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._opc_root),
            )

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
