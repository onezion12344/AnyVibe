"""web/engineer_dispatch.py — Backend-agnostic CEO-dispatch logic.

Shared by every voice/web backend (StepFun bridge, Pipecat bot, …).

Public API
----------
dispatch_to_engineer(task) -> dict
    Spawn the task via the receptionist, write delegation to session.json, and
    ring the caller back when the engineer finishes.
    Returns ``{"status": "dispatched", "task_id": ..., "backend": ...}``.

classify_and_dispatch(transcript, on_dispatched) -> None
    Ask the text CS brain (step-3.7-flash) whether the transcript is a coding
    request.  If so, call ``dispatch_to_engineer`` and pass the result dict to
    ``on_dispatched(info)`` — a BACKEND-SUPPLIED callback so neither bridge
    hard-codes a specific transport (browser WS vs Pipecat pipeline).

Config (read from env, set once here)
---------------------------------------
CV_CALL_BACKEND   – which CEO harness to use (default: "mock")
CV_DEMO_REPO      – repo path for dispatched tasks (default: "/tmp/cv-demo")
CS_BRAIN_MODEL    – text-LLM model for intent classification
STEPFUN_BASE_URL  – StepFun API base URL (for classification call)
CV_API_TOKEN      – bearer token for dispatch auth
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

# ── Config ────────────────────────────────────────────────────────────────────────

STEPFUN_API_KEY: str = os.environ.get("STEPFUN_API_KEY", "")
STEPFUN_BASE_URL: str = os.environ.get(
    "STEPFUN_BASE_URL", "https://api.stepfun.com/v1"
)
CS_BRAIN_MODEL: str = os.environ.get("CV_CS_BRAIN_MODEL", "step-3.7-flash")
_CALL_BACKEND: str = os.environ.get("CV_CALL_BACKEND", "mock")
CV_API_TOKEN: str = os.environ.get("CV_API_TOKEN", "")

# Fail-closed: real backends require an explicit token.
if _CALL_BACKEND in ("claude-code", "openopc") and not CV_API_TOKEN:
    _CALL_BACKEND = "mock"

_CALL_REPO: str = os.environ.get("CV_DEMO_REPO", "/tmp/cv-demo")

# ── Company kanban bridge ──────────────────────────────────────────────────────────
# The company board's WS clients live in the web-server process, so a voice-side
# dispatch lights up the board by POSTing to that server's /api/company/run
# (server-to-server, token-authed). Best-effort; never blocks or fails the call.
_COMPANY_BOARD_URL: str = os.environ.get("CV_COMPANY_BOARD_URL", "http://127.0.0.1:5091")
_AUTO_BOARD: bool = os.environ.get("CV_COMPANY_AUTO_BOARD", "1") == "1"


async def _notify_company_board(task: str) -> None:
    """Fire the company kanban run for *task* (best-effort, non-blocking).

    Lights up any board client connected to the web server's signaling WS.
    Failures are logged and never affect the voice call.
    """
    if not _AUTO_BOARD:
        return
    url = _COMPANY_BOARD_URL.rstrip("/") + "/api/company/run"
    headers = {"content-type": "application/json"}
    if CV_API_TOKEN:
        headers["x-cv-token"] = CV_API_TOKEN
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"task": task}, headers=headers)
        _log("BOARD", f"company board run → {url} [{resp.status_code}]")
    except Exception as exc:
        _log("BOARD", f"board notify failed (non-fatal): {exc}")


# ── Tool schema ──────────────────────────────────────────────────────────────────
# Both the realtime bridge (StepFun tool-calling) and the text brain
# (step-3.7-flash function-calling) use this identical schema.

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_to_engineer",
            "description": (
                "Dispatch a software-engineering / coding task to the on-call "
                "engineer team. Call this when the user wants to build, write, "
                "fix, modify, create, script, or develop anything code-related."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "A clear, self-contained description of the task. "
                            "Include the goal, relevant context, and any "
                            "constraints the engineer should know."
                        ),
                    }
                },
                "required": ["task"],
            },
        },
    }
]

# ── Helpers ───────────────────────────────────────────────────────────────────────


def _log(prefix: str, msg: str) -> None:
    print(f"[{prefix}] {msg}", flush=True)


# ── Core dispatch ────────────────────────────────────────────────────────────────


async def dispatch_to_engineer(task: str) -> dict[str, Any]:
    """Spawn *task* on the CEO backend and return immediately.

    The callback pattern lets the caller attach an *on_complete* hook before
    spawning (so the hook owns the task_id).  Here we provide the out-of-the-box
    variant that records the delegation and rings on completion.

    Args:
        task: Natural-language description of the engineering work.

    Returns:
        Ack dict ``{"status": "dispatched", "task_id": ..., "backend": ...}``.
        On error: ``{"status": "error", "error": "..."}``.
    """
    from receptionist.core import Receptionist  # lazy import to keep this module cheap
    from receptionist.state import load_state, save_state

    task_hash = hashlib.sha256(task.encode()).hexdigest()[:8]
    _log("DISPATCH", f"task#{task_hash} backend={_CALL_BACKEND}")

    try:
        Path(_CALL_REPO).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    r = Receptionist()

    async def _on_complete(result: Any) -> None:
        """Mark delegation done and ring the caller."""
        try:
            st = load_state()
            for d in st.get("delegations", []):
                if d.get("task_id") == tid:
                    d["status"] = "completed"
            save_state(st)
        except Exception:
            pass
        try:
            from web.signaling import ring

            summary = (getattr(result, "summary", "") or "")[:80]
            await ring(reason=f"Task complete: {summary}", frm="CEO")
        except Exception as exc:
            _log("DISPATCH", f"ring failed: {exc}")

    try:
        tid = await r.dispatch_async(
            task,
            backend=_CALL_BACKEND,
            repo_path=_CALL_REPO,
            on_complete=_on_complete,
        )
    except Exception as exc:
        _log("DISPATCH", f"dispatch_async failed: {exc}")
        return {"status": "error", "error": str(exc)}

    # Record delegation so the kanban board shows it as in-progress right away.
    try:
        st = load_state()
        st.setdefault("delegations", []).append(
            {
                "task_id": tid,
                "description": task,
                "status": "running",
                "created_at": time.time(),
            }
        )
        save_state(st)
    except Exception as exc:
        _log("DISPATCH", f"state write failed: {exc}")

    _log("DISPATCH", f"dispatched  task_id={tid}")

    # Light up the company kanban for this dispatch (best-effort, non-blocking).
    asyncio.create_task(_notify_company_board(task))

    return {"status": "dispatched", "task_id": tid, "backend": _CALL_BACKEND}


# ── Intent classification ─────────────────────────────────────────────────────────


async def classify_and_dispatch(
    transcript: str,
    on_dispatched: Callable[[dict[str, Any]], Optional[asyncio.Future]],
) -> None:
    """Ask the text CS brain whether *transcript* is a coding request.

    If it is, call :func:`dispatch_to_engineer` and hand the result to
    ``on_dispatched(info)`` — a **backend-supplied** callable so this module
    never hard-codes a specific transport.

    The callback may be a coroutine function or return a Future; both patterns
    are handled.  The callback is *not* awaited here so the classification step
    never blocks the audio pipeline.

    Args:
        transcript:    Transcribed text from the user's most recent turn.
        on_dispatched: Callable ``(info: dict) -> None | asyncio.Future``.
                       Called with the dispatch ack dict if a task was dispatched;
                       called with ``None`` if the transcript was smalltalk.
    """
    text = (transcript or "").strip()
    if not text or not STEPFUN_API_KEY:
        return

    payload = {
        "model": CS_BRAIN_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a triage agent for a software studio. "
                    "Decide whether the user is asking the engineering team to "
                    "build / write / fix / modify / create / script / develop "
                    "anything software-related. "
                    "If YES: call the dispatch_to_engineer tool with a clear "
                    "description of the work. "
                    "If NO (smalltalk, status check, greeting): do nothing, "
                    "do not call any tool."
                ),
            },
            {"role": "user", "content": text},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{STEPFUN_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {STEPFUN_API_KEY}"},
                json=payload,
            )
        if r.status_code != 200:
            _log("CLASSIFY", f"brain non-200: {r.status_code} {r.text[:120]}")
            return

        choice = (r.json().get("choices") or [{}])[0]
        tool_calls = (choice.get("message") or {}).get("tool_calls") or []
        for tc in tool_calls:
            if (tc.get("function") or {}).get("name") == "dispatch_to_engineer":
                args = json.loads(tc["function"].get("arguments") or "{}")
                task = (args.get("task") or "").strip()
                if task and not task.startswith("-"):
                    info = await dispatch_to_engineer(task)
                    try:
                        result = on_dispatched(info)
                        if asyncio.isfuture(result):
                            await result
                    except Exception as exc:
                        _log("CLASSIFY", f"on_dispatched error: {exc}")
                return
    except Exception as exc:
        _log("CLASSIFY", f"error: {exc}")
