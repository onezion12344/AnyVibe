"""receptionist/adapters/qoder.py — QoderSDK persistent-company adapter.

Runs the local ``qoder_agent_sdk`` as a coding-vibe company:
* **Company mode** — keeps a persistent ``QoderSDKClient`` alive across
  ``spawn()`` calls, keyed by ``company_id`` in a module-level registry.
* **Task mode** — one-shot session per ``spawn()`` call.

Fixture-first
--------------
If ``CV_QODER_FIXTURE`` is set (path to a JSONL of recorded stream events)
OR the ``qoder_agent_sdk`` import fails, we run in fixture mode: the JSONL
is replayed at a modest pace so ``stream_status()`` yields live-looking
``StatusEvent`` objects.  The adapter never crashes in either case —
unavailable backends produce a graceful *failed* handle (matching the
``openopc.py`` pattern).

SDK shape assumed
-----------------
``QoderSDKClient(QoderAgentOptions)`` — ``connect(prompt)``, ``query(prompt)``,
``receive_messages()`` (async iterator), ``receive_response()``, ``interrupt()``,
``disconnect()``.  ``QoderAgentOptions(auth=qodercli_auth(), agents={…},
allowed_tools=[…], cwd=…)``.  Stream items: ``AssistantMessage`` (``.content``
= list of ``TextBlock`` / ``tool_use`` blocks), ``ToolResult``, ``ResultMessage``,
``StreamEvent``.

These attribute names are **documented** against the SDK.  If the real SDK
uses different names they will be caught in live-mode verification (TODO).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import AsyncIterator

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

# ---------------------------------------------------------------------------
# SDK import guard
# ---------------------------------------------------------------------------
try:
    from qoder_agent_sdk import QoderSDKClient, QoderAgentOptions, qodercli_auth  # type: ignore[import]

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    QoderSDKClient = None  # type: ignore[assignment,misc]
    QoderAgentOptions = None  # type: ignore[assignment,misc]
    qodercli_auth = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Persistent company sessions: company_id -> {"client": QoderSDKClient, "status": …}
_company_sessions: dict[str, dict] = {}

# Task-mode handles (one-shot, not shared)
_handles: dict[str, dict] = {}

# Mode tag for fixture-event role field
_CEO_ROLE = "ceo"
_CLI_PERMISSION_MODES = {"default", "accept_edits", "dont_ask", "auto"}
_SAFE_CLI_ID = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_cli_id(value: object, fallback: str = "company") -> str:
    """Keep session/config identifiers inside the adapter-owned config root."""
    cleaned = _SAFE_CLI_ID.sub("-", str(value or "")).strip(".-")
    return cleaned[:120] or fallback


def _company_session_id(value: object, company_id: object) -> str:
    """Return a valid UUID because qodercli rejects human-readable IDs."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"coding-vibe-company:{_safe_cli_id(company_id)}"))


def _company_cli_config_dir(company_id: object) -> str | None:
    """Return an explicitly configured per-company config directory, if any.

    Qoder stores login credentials in its default config directory.  Creating a
    fresh config directory by default would make an already logged-in CLI look
    anonymous, so company isolation is achieved through UUID session IDs by
    default.  Deployments that provide separately authenticated configurations
    can opt into per-company directories with ``CV_QODER_CONFIG_ROOT``.
    """
    root = os.environ.get("CV_QODER_CONFIG_ROOT")
    if not root:
        return None
    return str((Path(root).expanduser() / _safe_cli_id(company_id)).resolve())

# ---------------------------------------------------------------------------
# Fixture replay
# ---------------------------------------------------------------------------

async def _replay_fixture(fixture_path: str, handle: str) -> None:
    """Read a JSONL fixture and replay events into *_handles[handle]*.

    Each line must be a JSON object.  Supported record types (based on the
    ``type`` field):
    - ``"assistant"`` — map text blocks → StatusEvent("message", …) and
      tool_use blocks → StatusEvent("tool", "…") via ``.content`` list.
    - ``"tool_result"`` — StatusEvent("progress", …)
    - ``"result"`` — signal done.
    - Unknown type → ignore.

    Falls back to a `"text"` key if ``content`` is absent (per-record level).
    """
    store = _handles[handle]
    store["status"] = "running"
    store["events"] = []

    try:
        with open(fixture_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                rtype = record.get("type", "")
                role = str(record.get("role", "") or "ceo")
                content_blocks = record.get("content", [])
                text_field = record.get("text")  # optional per-record text

                if rtype == "assistant":
                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type", "")

                        if btype == "text":
                            txt = block.get("text", "")
                            if txt:
                                store["events"].append(
                                    StatusEvent(kind="message", text=txt, actor=role)
                                )
                        elif btype == "tool_use":
                            name = block.get("name", "tool")
                            inp = block.get("input", {})
                            # Agent delegation: "Agent(role): prompt_summary"
                            if name == "Agent":
                                agent_role = inp.get("agent", "unknown")
                                prompt = inp.get("prompt", "…")
                                summary = prompt[:80] + ("…" if len(prompt) > 80 else "")
                                store["events"].append(
                                    StatusEvent(
                                        kind="tool",
                                        text=f"{agent_role}: {summary}",
                                        actor=role,
                                    )
                                )
                            else:
                                args = str(inp)[:60]
                                store["events"].append(
                                    StatusEvent(
                                        kind="tool",
                                        text=f"{name}({args})",
                                        actor=role,
                                    )
                                )
                        elif btype == "tool_result":
                            res_text = block.get("content", "") or str(block)
                            store["events"].append(
                                StatusEvent(
                                        kind="progress",
                                        text=(res_text[:200] if isinstance(res_text, str) else str(res_text)[:200]),
                                        actor=role,
                                )
                            )

                    # Also check for a plain ``text`` field (simple records)
                    if text_field and not content_blocks:
                        store["events"].append(
                            StatusEvent(kind="message", text=text_field, actor=role)
                        )

                elif rtype == "tool_result":
                    res_text = record.get("content", "") or record.get("text", "") or str(record)
                    store["events"].append(
                        StatusEvent(kind="progress", text=str(res_text)[:200], actor=role)
                    )

                elif rtype == "result":
                    # terminal event — add a done marker
                    store["events"].append(StatusEvent(kind="done", text="Qoder task complete", actor="ceo"))

                # Yield between events so stream_status looks live
                await asyncio.sleep(0.08)

    except FileNotFoundError:
        store["events"].append(
            StatusEvent(kind="error", text=f"Fixture file not found: {fixture_path}")
        )
    except json.JSONDecodeError as exc:
        store["events"].append(
            StatusEvent(kind="error", text=f"Invalid fixture JSONL: {exc}")
        )
    finally:
        # Always emit a done marker so stream_status consumers can assert it.
        if not any(e.kind == "done" for e in store["events"]):
            store["events"].append(StatusEvent(kind="done", text="Qoder task complete", actor="ceo"))
        store["status"] = "done"


def _append_stream_record(store: dict, record: dict) -> bool:
    """Translate one Qoder JSON stream record into ``StatusEvent`` objects.

    The SDK fixture uses a flat ``content`` field, while qodercli's
    ``stream-json`` records wrap that content in ``message``.  Keeping the
    conversion in one place makes both backends present the same UI contract.

    Returns ``True`` when *record* is terminal.
    """
    rtype = str(record.get("type", "")).lower()
    message = record.get("message")
    payload = message if isinstance(message, dict) else record
    actor = str(payload.get("role") or record.get("role") or "ceo")
    content_blocks = payload.get("content", record.get("content", []))
    if not isinstance(content_blocks, list):
        content_blocks = [{"type": "text", "text": str(content_blocks)}]

    if rtype == "assistant":
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                text = str(block.get("text", "")).strip()
                if text:
                    store["events"].append(StatusEvent(kind="message", text=text, actor=actor))
            elif btype == "tool_use":
                name = str(block.get("name", "tool"))
                input_data = block.get("input", {})
                input_data = input_data if isinstance(input_data, dict) else {}
                if name == "Agent":
                    agent_role = input_data.get("agent", "unknown")
                    prompt = str(input_data.get("prompt", "…"))
                    summary = prompt[:80] + ("…" if len(prompt) > 80 else "")
                    store["events"].append(
                        StatusEvent(kind="tool", text=f"{agent_role}: {summary}", actor=actor)
                    )
                else:
                    store["events"].append(
                        StatusEvent(kind="tool", text=f"{name}({str(input_data)[:60]})", actor=actor)
                    )
            elif btype == "tool_result":
                result = block.get("content", "") or str(block)
                store["events"].append(StatusEvent(kind="progress", text=str(result)[:200], actor=actor))
        return False

    if rtype in {"tool_result", "toolresult"}:
        result = payload.get("content", record.get("content", "")) or str(record)
        store["events"].append(StatusEvent(kind="progress", text=str(result)[:200], actor=actor))
        return False

    if rtype == "result":
        if record.get("is_error"):
            error = (
                record.get("error")
                or record.get("result")
                or payload.get("content")
                or "qodercli reported an unsuccessful result"
            )
            store["events"].append(StatusEvent(kind="error", text=str(error)[:500], actor=actor))
        return True

    # stream-json can include a few informational records; they are useful
    # only when they carry human-readable progress and are otherwise ignored.
    text = payload.get("text") or record.get("text")
    if text:
        store["events"].append(StatusEvent(kind="progress", text=str(text)[:200], actor=actor))
    return False


async def _run_cli_session(
    handle: str,
    cli_path: str,
    task: str,
    repo_path: str,
    context: dict | None,
) -> None:
    """Run an explicit qodercli session and translate its JSONL stream.

    This is deliberately opt-in: qodercli may have external network access
    and tool permissions, whereas the default browser demo must always remain
    reproducible from its recorded fixture.
    """
    store = _handles[handle]
    store["status"] = "running"
    store["events"] = []

    context = dict(context or {})
    resolved_repo = str(Path(repo_path).expanduser().resolve())
    mode = str(context.get("mode", "task"))
    persistent_cli = bool(context.get("persistent_cli")) and mode == "company"
    requested_permission = str(context.get("permission_mode", "dont_ask"))
    permission_mode = (
        requested_permission if requested_permission in _CLI_PERMISSION_MODES else "dont_ask"
    )
    command = [
        cli_path,
        "--print",
        "--output-format",
        "stream-json",
        "--cwd",
        resolved_repo,
        "--permission-mode",
        permission_mode,
    ]
    if persistent_cli:
        config_dir = _company_cli_config_dir(context.get("company_id"))
        if config_dir:
            Path(config_dir).mkdir(parents=True, exist_ok=True)
            command.extend(["--config-dir", config_dir])
        resume_session_id = context.get("resume_session_id")
        if resume_session_id:
            command.extend(["--resume", _safe_cli_id(resume_session_id)])
        else:
            command.extend(["--session-id", _safe_cli_id(context.get("session_id"), "cv-company")])
    else:
        command.append("--no-session-persistence")
    model = context.get("model")
    if model:
        command.extend(["--model", str(model)])
    roles = context.get("roles")
    if isinstance(roles, dict) and roles:
        command.extend(["--agents", json.dumps(roles, ensure_ascii=False)])
    ceo_prompt = context.get("ceo_prompt")
    if isinstance(ceo_prompt, str) and ceo_prompt.strip():
        command.extend(["--append-system-prompt", ceo_prompt.strip()])
    command.append(task)

    process: asyncio.subprocess.Process | None = None
    unstructured_output: list[str] = []
    terminal_received = False
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        store["process"] = process
        assert process.stdout is not None
        assert process.stderr is not None
        stderr_task = asyncio.create_task(process.stderr.read())

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue
            try:
                record = json.loads(decoded)
            except json.JSONDecodeError:
                # qodercli may write a one-line diagnostic alongside its JSON
                # stream.  Do not turn harmless logs into a board card.
                unstructured_output.append(decoded)
                continue
            if not isinstance(record, dict):
                continue
            terminal_received = _append_stream_record(store, record) or terminal_received

        return_code = await process.wait()
        stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
        if return_code != 0 and not any(event.kind == "error" for event in store["events"]):
            diagnostic = stderr or ("\n".join(unstructured_output[-3:])) or f"qodercli exited with status {return_code}"
            store["events"].append(StatusEvent(kind="error", text=diagnostic[:500]))
        elif not terminal_received and not any(event.kind == "error" for event in store["events"]):
            store["events"].append(
                StatusEvent(kind="progress", text="qodercli stream ended without a result record")
            )
    except Exception as exc:
        store["events"].append(StatusEvent(kind="error", text=f"qodercli failed: {exc}"))
    finally:
        store.pop("process", None)
        if not any(event.kind == "done" for event in store["events"]):
            store["events"].append(StatusEvent(kind="done", text="Qoder task complete"))
        store["status"] = "done"


# ---------------------------------------------------------------------------
# Live SDK session runner
# ---------------------------------------------------------------------------

async def _run_live_session(handle: str, client: QoderSDKClient, prompt: str, mode: str) -> None:
    """Drive a ``QoderSDKClient`` session end-to-end and store StatusEvents."""
    store = _handles[handle]
    store["status"] = "running"
    store["events"] = []

    try:
        if mode == "company":
            await client.connect(prompt)
        else:
            await client.query(prompt)

        # receive_messages() is documented as an async iterator over the full session
        async for msg in client.receive_messages():
            # ---- AssistantMessage ----
            # SDK documented shape: msg.type == "assistant", msg.content = [...]
            msg_type = getattr(msg, "type", "") or type(msg).__name__.lower()
            actor = str(getattr(msg, "role", "") or "ceo")

            if msg_type in ("assistant", "assistantmessage"):
                content = getattr(msg, "content", [])
                if not isinstance(content, list):
                    content = [{"type": "text", "text": str(content)}]
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "text":
                        txt = block.get("text", "")
                        if txt:
                            store["events"].append(
                                StatusEvent(kind="message", text=txt, actor=actor)
                            )
                    elif btype == "tool_use":
                        name = block.get("name", "tool")
                        inp = block.get("input", {})
                        if name == "Agent":
                            agent_role = inp.get("agent", "unknown")
                            prompt_txt = inp.get("prompt", "…")
                            summary = prompt_txt[:80] + ("…" if len(prompt_txt) > 80 else "")
                            store["events"].append(
                                StatusEvent(kind="tool", text=f"{agent_role}: {summary}", actor=actor)
                            )
                        else:
                            args = str(inp)[:60]
                            store["events"].append(
                                StatusEvent(kind="tool", text=f"{name}({args})", actor=actor)
                            )

            # ---- ToolResult ----
            elif msg_type in ("tool_result", "toolresult"):
                content = getattr(msg, "content", None) or str(msg)
                store["events"].append(
                    StatusEvent(kind="progress", text=str(content)[:200], actor=actor)
                )

            # ---- ResultMessage ----
            elif msg_type in ("result", "resultmessage"):
                # terminal — done
                break

            # ---- StreamEvent (partial deltas) ----
            elif msg_type == "streamevent":
                delta = getattr(msg, "delta", None) or str(msg)
                if delta:
                    store["events"].append(
                        StatusEvent(kind="progress", text=f"[delta] {str(delta)[:120]}", actor=actor)
                    )

            # Unknown type — store as a progress note
            else:
                store["events"].append(
                    StatusEvent(kind="progress", text=f"[{msg_type}] {str(msg)[:120]}", actor=actor)
                )

        store["events"].append(StatusEvent(kind="done", text="Qoder task complete", actor="ceo"))
    except Exception as exc:
        store["events"].append(StatusEvent(kind="error", text=str(exc)))
    finally:
        # Emit "done" before flipping status so stream_status can yield it.
        if store["status"] != "failed":
            store["events"].append(StatusEvent(kind="done", text="Qoder task complete", actor="ceo"))
        store["status"] = "done"
        if mode == "task":
            try:
                await client.disconnect()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class QoderAdapter(HarnessAdapter):
    """Qoder SDK persistent-company adapter.

    Parameters
    ----------
    default_mode:
        ``"company"`` (keep sessions alive across spawns) or ``"task"``
        (ephemeral one-shot per spawn).  Default ``"task"``.
    default_company_id:
        Company identifier used when ``context`` does not supply one.
        Default ``"default"``.
    fixture_path:
        Path to a JSONL fixture file.  Overridden by the ``CV_QODER_FIXTURE``
        env var if set.
    cli_enabled:
        Explicitly enable the qodercli ``stream-json`` fallback when the Python
        SDK is not installed.  Defaults to ``CV_QODER_CLI=1``.  The browser
        demo does not enable this implicitly.
    cli_path:
        qodercli executable path; defaults to ``CV_QODER_CLI_BIN`` or the
        executable on ``PATH``.
    """

    name = "qoder"

    def __init__(
        self,
        *,
        default_mode: str = "task",
        default_company_id: str = "default",
        fixture_path: str | None = None,
        cli_enabled: bool | None = None,
        cli_path: str | None = None,
    ) -> None:
        self._default_mode = default_mode
        self._default_company_id = default_company_id
        self._fixture_path = fixture_path or os.environ.get("CV_QODER_FIXTURE", "")
        self._cli_enabled = (
            os.environ.get("CV_QODER_CLI", "").strip().lower() in {"1", "true", "yes"}
            if cli_enabled is None
            else cli_enabled
        )
        self._configured_cli = cli_path or os.environ.get("CV_QODER_CLI_BIN", "qodercli")
        self._cli_path = shutil.which(self._configured_cli) if self._cli_enabled else None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _build_options(
        self,
        context: dict | None,
        repo_path: str | None = None,
    ) -> QoderAgentOptions | None:
        """Build ``QoderAgentOptions`` from *context*, or ``None`` to use defaults."""
        if not _SDK_AVAILABLE or QoderAgentOptions is None or qodercli_auth is None:
            return None

        roles: dict = {}
        model: str | None = None
        if context:
            roles = context.get("roles", {}) or {}
            model = context.get("model")

        try:
            auth = qodercli_auth()
            opts_kwargs: dict = {
                "auth": auth,
                "agents": roles,
                "allowed_tools": [],
                "cwd": str(Path(repo_path).expanduser().resolve())
                if repo_path
                else os.environ.get("PWD", "."),
            }
            if model:
                opts_kwargs["model"] = model
            return QoderAgentOptions(**opts_kwargs)
        except Exception as exc:
            # qodercli login not done yet — return None to trigger fixture mode
            return None

    # ── HarnessAdapter interface ─────────────────────────────────────────────

    async def spawn(self, task: str, *, repo_path: str, context: dict | None = None) -> str:
        handle = str(uuid.uuid4())

        ctx = dict(context or {})
        mode: str = ctx.get("mode", self._default_mode)
        company_id: str = ctx.get("company_id", self._default_company_id)

        # Fixtures always win.  They keep the Demo Day path deterministic even
        # when a developer has qodercli installed on their machine.
        if self._fixture_path:
            # Fixture mode — replay in a background task
            _handles[handle] = {
                "status": "pending",
                "events": [],
                "fixture": self._fixture_path,
            }
            asyncio.create_task(_replay_fixture(self._fixture_path, handle))
            return handle

        # The Python SDK remains the preferred live backend.  qodercli is a
        # separately explicit fallback so a missing SDK never turns a local
        # fixture demo into a networked coding run by accident.
        # A persisted company preset explicitly opts into qodercli.  This keeps
        # the old fixture-first demo safe while letting the real CS → CEO path
        # work without a process-wide CV_QODER_CLI environment flag.
        cli_enabled = self._cli_enabled or bool(ctx.get("use_cli"))
        cli_path = self._cli_path or (shutil.which(self._configured_cli) if cli_enabled else None)
        if not _SDK_AVAILABLE and cli_enabled and cli_path:
            if mode == "company" and bool(ctx.get("persistent_cli")):
                session_id = _company_session_id(ctx.get("session_id"), company_id)
                previous = _company_sessions.get(company_id)
                if (
                    previous
                    and previous.get("backend") == "cli"
                    and previous.get("session_id") == session_id
                ):
                    ctx["resume_session_id"] = session_id
                else:
                    _company_sessions[company_id] = {
                        "backend": "cli",
                        "session_id": session_id,
                        "status": "running",
                    }
                ctx["session_id"] = session_id
            _handles[handle] = {
                "status": "pending",
                "events": [],
                "mode": mode,
                "company_id": company_id,
                "backend": "cli",
            }
            asyncio.create_task(_run_cli_session(handle, cli_path, task, repo_path, ctx))
            return handle

        if not _SDK_AVAILABLE:
            _handles[handle] = {
                "status": "failed",
                "events": [
                    StatusEvent(
                        kind="error",
                        text=(
                            "Qoder SDK is not installed. Set CV_QODER_FIXTURE=<path> "
                            "for a replay, or explicitly enable CV_QODER_CLI=1."
                        ),
                    )
                ],
            }
            return handle

        # ── Live SDK mode ───────────────────────────────────────────────────
        options = self._build_options(ctx, repo_path)
        if options is None:
            # qodercli not logged in — graceful failure
            _handles[handle] = {
                "status": "failed",
                "events": [
                    StatusEvent(
                        kind="error",
                        text=(
                            "Qoder SDK unavailable: qodercli not logged in "
                            "(or qoder_agent_sdk import failed). "
                            "Run 'qodercli login' or set CV_QODER_FIXTURE=<path>."
                        ),
                    )
                ],
            }
            return handle

        _handles[handle] = {
            "status": "pending",
            "events": [],
            "mode": mode,
            "company_id": company_id,
        }

        if mode == "company":
            # ── Company mode: reuse or create a persistent client ─────────────
            session = _company_sessions.get(company_id)
            if session is None:
                client = QoderSDKClient(options)
                _company_sessions[company_id] = {
                    "client": client,
                    "status": "running",
                }
                session = _company_sessions[company_id]

            client = session["client"]
            asyncio.create_task(
                _run_live_session(handle, client, task, mode="company")
            )
        else:
            # ── Task mode: one-shot session ──────────────────────────────────
            client = QoderSDKClient(options)
            asyncio.create_task(
                _run_live_session(handle, client, task, mode="task")
            )

        return handle

    async def stream_status(self, handle: str) -> AsyncIterator[StatusEvent]:
        store = _handles.get(handle)
        if store is None:
            raise KeyError(f"Unknown handle: {handle!r}")

        # Wait for at least one event if the task is still pending/running
        while store["status"] in ("pending", "running") and not store["events"]:
            await asyncio.sleep(0.05)

        idx: int = store.get("_stream_idx", 0)
        events: list[StatusEvent] = store.get("events", [])

        while idx < len(events):
            yield events[idx]
            idx += 1
        store["_stream_idx"] = idx

        # Keep polling while running
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

        if store.get("status") == "failed":
            events = store.get("events", [])
            err_text = next((e.text for e in events if e.kind == "error"), "Unknown error")
            return TaskResult(
                ok=False,
                summary=err_text,
                files_changed=[],
                raw="\n".join(e.text for e in events),
            )

        events = store.get("events", [])
        errors = [e for e in events if e.kind == "error"]
        if errors:
            return TaskResult(
                ok=False,
                summary=errors[-1].text,
                files_changed=[],
                raw="\n".join(e.text for e in events),
            )

        messages = [e.text for e in events if e.kind == "message"]
        summary = messages[-1] if messages else "Qoder task complete"
        return TaskResult(
            ok=True,
            summary=summary,
            files_changed=[],
            raw="\n".join(messages),
        )

    async def cancel(self, handle: str) -> None:
        store = _handles.get(handle)
        if store is None:
            return
        process = store.get("process")
        if process is not None and process.returncode is None:
            process.terminate()
        store["status"] = "cancelled"
        # Best-effort interrupt if a live client is held in the company session
        if store.get("company_id"):
            session = _company_sessions.get(store["company_id"])
            client = session.get("client") if session else None
            if client is not None:
                try:
                    await client.interrupt()
                except Exception:
                    pass
