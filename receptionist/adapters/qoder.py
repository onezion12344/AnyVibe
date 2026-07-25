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
                role = record.get("role", "")
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
                                    StatusEvent(kind="message", text=txt)
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
                                    )
                                )
                            else:
                                args = str(inp)[:60]
                                store["events"].append(
                                    StatusEvent(
                                        kind="tool",
                                        text=f"{name}({args})",
                                    )
                                )
                        elif btype == "tool_result":
                            res_text = block.get("content", "") or str(block)
                            store["events"].append(
                                StatusEvent(
                                    kind="progress",
                                    text=(res_text[:200] if isinstance(res_text, str) else str(res_text)[:200]),
                                )
                            )

                    # Also check for a plain ``text`` field (simple records)
                    if text_field and not content_blocks:
                        store["events"].append(
                            StatusEvent(kind="message", text=text_field)
                        )

                elif rtype == "tool_result":
                    res_text = record.get("content", "") or record.get("text", "") or str(record)
                    store["events"].append(
                        StatusEvent(kind="progress", text=str(res_text)[:200])
                    )

                elif rtype == "result":
                    # terminal event — add a done marker
                    store["events"].append(StatusEvent(kind="done", text="Qoder task complete"))

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
                                StatusEvent(kind="message", text=txt)
                            )
                    elif btype == "tool_use":
                        name = block.get("name", "tool")
                        inp = block.get("input", {})
                        if name == "Agent":
                            agent_role = inp.get("agent", "unknown")
                            prompt_txt = inp.get("prompt", "…")
                            summary = prompt_txt[:80] + ("…" if len(prompt_txt) > 80 else "")
                            store["events"].append(
                                StatusEvent(kind="tool", text=f"{agent_role}: {summary}")
                            )
                        else:
                            args = str(inp)[:60]
                            store["events"].append(
                                StatusEvent(kind="tool", text=f"{name}({args})")
                            )

            # ---- ToolResult ----
            elif msg_type in ("tool_result", "toolresult"):
                content = getattr(msg, "content", None) or str(msg)
                store["events"].append(
                    StatusEvent(kind="progress", text=str(content)[:200])
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
                        StatusEvent(kind="progress", text=f"[delta] {str(delta)[:120]}")
                    )

            # Unknown type — store as a progress note
            else:
                store["events"].append(
                    StatusEvent(kind="progress", text=f"[{msg_type}] {str(msg)[:120]}")
                )

        store["events"].append(StatusEvent(kind="done", text="Qoder task complete"))
    except Exception as exc:
        store["events"].append(StatusEvent(kind="error", text=str(exc)))
    finally:
        # Emit "done" before flipping status so stream_status can yield it.
        if store["status"] != "failed":
            store["events"].append(StatusEvent(kind="done", text="Qoder task complete"))
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
    """

    name = "qoder"

    def __init__(
        self,
        *,
        default_mode: str = "task",
        default_company_id: str = "default",
        fixture_path: str | None = None,
    ) -> None:
        self._default_mode = default_mode
        self._default_company_id = default_company_id
        self._fixture_path = fixture_path or os.environ.get("CV_QODER_FIXTURE", "")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _build_options(self, context: dict | None) -> QoderAgentOptions | None:
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
                "cwd": os.environ.get("PWD", "."),
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

        ctx = context or {}
        mode: str = ctx.get("mode", self._default_mode)
        company_id: str = ctx.get("company_id", self._default_company_id)

        # ── Decide: fixture vs live ──────────────────────────────────────────
        use_fixture = bool(self._fixture_path) or not _SDK_AVAILABLE

        if use_fixture:
            # Fixture mode — replay in a background task
            fixture = self._fixture_path or ""
            _handles[handle] = {
                "status": "pending",
                "events": [],
                "fixture": fixture,
            }
            asyncio.create_task(_replay_fixture(fixture, handle))
            return handle

        # ── Live SDK mode ───────────────────────────────────────────────────
        options = self._build_options(ctx)
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
        store["status"] = "cancelled"
        # Best-effort interrupt if a live client is held in the company session
        if store.get("company_id"):
            session = _company_sessions.get(store["company_id"])
            if session:
                try:
                    await session["client"].interrupt()
                except Exception:
                    pass
