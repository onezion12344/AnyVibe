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
import re
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

import httpx

# ── Config ────────────────────────────────────────────────────────────────────────

STEPFUN_API_KEY: str = os.environ.get("STEPFUN_API_KEY", "")
STEPFUN_BASE_URL: str = os.environ.get(
    "STEPFUN_BASE_URL", "https://api.stepfun.com/v1"
)
# ``step-3.5-flash`` is StepFun's flagship reasoning/tool-use model.  Keep the
# existing CV_CS_BRAIN_MODEL knob as an override so deployed callers can pin a
# model without a code change.
CS_BRAIN_MODEL: str = os.environ.get("CV_CS_BRAIN_MODEL", "step-3.5-flash")
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


# ── CS role contract ─────────────────────────────────────────────────────────────
#
# This is the runtime counterpart of docs/CS-RECEPTIONIST-SKILL.md.  Keep the
# conversational persona and the handoff policy here, rather than duplicating
# slightly different versions in every voice backend.

CS_VOICE_PERSONA = """
你是 Yellow Sheep（黄羊），Coding Vibe 的客户成功伙伴（CS），不是急着转单的
自动接线员。你的职责是先把用户当作正在聊天的同事来回应：听懂、陪聊、澄清，
再在确有软件交付需求时连接 CEO 与工程团队。

对话方式：
- 用自然、简短、口语化的中文回答，通常 1–3 句。先回应用户这一句话，不要只说
  “收到”或“Got it”。
- 用户问候、问你最近如何、闲聊、问能力、问项目近况、要进度或报告时，正常聊天或
  诚实说明已知情况；这不是新任务。不要说“已安排”“马上处理”“忙完回电”或暗示你
  要挂断。如果没有可靠的任务信息，就直说目前没有可确认的新进展，并邀请用户继续聊。
- 对模糊的想法或“帮我看看”之类的请求，先问一个最有帮助的澄清问题；不要猜测任务，
  不要自行转给工程师。
- 只有用户明确要团队开始一个可执行的软件交付或改动（例如新增功能、修 bug、写代码、
  改网站、测试或部署）时，才简短复述需求并表示会交给团队。交接后仍可继续通话、记录
  补充；不要主动结束通话，也不要承诺“马上回电”。只有任务实际完成或用户明确要求时，
  才谈回电或通知。
- 不要编造项目状态、任务编号、已完成的工作或工程团队的回复。
""".strip()

CS_TRIAGE_INSTRUCTIONS = """
You are the careful handoff gate for Yellow Sheep, a customer-success
receptionist at a software studio. Dispatch is exceptional, not the default.

Call dispatch_to_engineer ONLY when the user explicitly asks the engineering
team to begin a concrete software deliverable or change now: for example build
or change a product feature, fix a bug, write or modify code, implement a
website/app/API, run software tests, or deploy a software change. Preserve the
user's language and describe the requested work without inventing scope.

Never call the tool for greetings, wellbeing questions, small talk, capability
questions, status/progress/report requests, discussion of an existing task,
brainstorming, or vague requests such as “take a look” with no requested
software change. A request for an update or report remains a conversation even
when it mentions an app or project. If the request is ambiguous, do not call a
tool yet; the CS should ask one short clarifying question first.
""".strip()

# Exact status/social turns are common in calls.  This fast-path prevents a
# model's occasional over-eager function call from turning “最近怎么样？给我报告一下”
# into an engineering ticket.  It only suppresses the classifier when no clear
# engineering action is present; mixed requests still reach the careful LLM gate.
_STATUS_OR_SOCIAL_RE = re.compile(
    r"(?:最近.*怎么样|怎么样了|近况|进展|进度|状态|汇报|报告|"
    r"how\s*(?:are|is).*going|how\s+are\s+you|status|progress|update)",
    re.IGNORECASE,
)
_ENGINEERING_ACTION_RE = re.compile(
    r"(?:新增|添加|加上|修复|修一下|修 bug|改(?:一下|成|掉)?|实现|开发|部署|"
    r"重构|写(?:个|一段|代码|程序|脚本)|测试|上线|build|implement|develop|"
    r"fix|refactor|deploy|test|add|create|modify|change|write\s+(?:code|a\s+(?:web|app)))",
    re.IGNORECASE,
)


def _is_status_or_social_turn(text: str) -> bool:
    """Return whether *text* is plainly conversation/reporting, not a handoff.

    The regex deliberately has a narrow remit: it is a safety brake for status
    checks, while the LLM remains responsible for judging all other requests.
    """
    return bool(_STATUS_OR_SOCIAL_RE.search(text)) and not bool(
        _ENGINEERING_ACTION_RE.search(text)
    )


_SOFTWARE_TARGET_RE = re.compile(
    r"(?:代码|程序|脚本|网站|网页|前端|后端|功能|登录|接口|api|app|应用|"
    r"bug|测试|部署|database|数据库|repo|项目|software|code|website|web|"
    r"feature|endpoint|service)",
    re.IGNORECASE,
)


def _looks_like_explicit_software_task(text: str) -> bool:
    """Conservative fallback for a clear task when text tool use is missed."""
    return (
        not _is_status_or_social_turn(text)
        and bool(_ENGINEERING_ACTION_RE.search(text))
        and bool(_SOFTWARE_TARGET_RE.search(text))
    )


# ── Tool schema ──────────────────────────────────────────────────────────────────
# Both the realtime bridge (StepFun tool-calling) and the text brain
# (step-3.7-flash function-calling) use this identical schema.

DISPATCH_TOOL_DESCRIPTION = (
    "Start a concrete software-engineering task for the CEO/engineer team. Use "
    "only when the user explicitly requests a software deliverable or change "
    "(build, implement, fix, code, test, or deploy). Do not use this for "
    "greetings, conversation, wellbeing questions, status/progress/report "
    "requests, capability questions, brainstorming, or vague requests that "
    "need clarification."
)

END_CALL_TOOL_DESCRIPTION = (
    "End the active voice call after the caller clearly says goodbye or asks to "
    "hang up. Do not use it for a pause, a question, an unfinished task, or a "
    "casual mention of a call."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_to_engineer",
            "description": DISPATCH_TOOL_DESCRIPTION,
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

END_CALL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "end_call",
        "description": END_CALL_TOOL_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "A short description of the caller's goodbye.",
                }
            },
            "required": ["reason"],
        },
    },
}

CALL_TOOLS: list[dict[str, Any]] = [*TOOLS, END_CALL_TOOL]

CALL_ROUTER_INSTRUCTIONS = """
You are the decision brain for Yellow Sheep, a warm customer-success partner
on a software-studio voice call. Reply in concise, natural Chinese.

Use dispatch_to_engineer only for a caller's explicit, concrete request to
start software work now. Never dispatch greetings, wellbeing questions,
status/progress/report requests, capability questions, brainstorming, or vague
requests. Ask one short clarifying question for vague work.

Use end_call only when the caller clearly says goodbye or explicitly asks to
hang up and has no unfinished request in the same turn. Do not end the call
just because a task was handed off. For a normal conversational turn, do not
call a tool; answer helpfully in one to three sentences. Do not invent work,
project status, or team responses.
""".strip()

CALL_OPENING_INSTRUCTIONS = """
You are Yellow Sheep, the warm customer-success partner for Coding Vibe. A
caller has just joined a new voice call. No concrete task or reliable project
status has been provided in this call yet.

Speak exactly one short, natural Chinese sentence: a friendly welcome followed
by one open question. It should sound like a thoughtful colleague starting a
conversation, not like a product demo or call-centre script.

This is the actual spoken greeting, not a description of what you would say.
Never introduce yourself as an assistant, decision-maker, AI, system, or
agent. Never list capabilities, services, task types, or examples of work.
Do not mention prompts, systems, tools, callbacks, engineering teams, project
status, or anything not yet said by the caller. Do not call any tool.
""".strip()

_GOODBYE_ONLY_RE = re.compile(
    r"(?:^|[，,。.!！?？\s])(?:再见|拜拜|拜了|先这样|先挂了|挂了|下次聊|"
    r"goodbye|bye|see\s+you)(?:$|[，,。.!！?？\s])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CallTurn:
    """A text-model decision for one completed caller utterance."""

    action: str = "reply"  # reply | dispatch | end_call
    reply: str = ""
    task: str = ""


def _is_goodbye_only_turn(text: str) -> bool:
    """Fast, deterministic handling for unmistakable farewells.

    A caller saying “再见” should never depend on a probabilistic model tool
    call.  Mixed turns (for example “先别挂，帮我修 bug”) still go to the
    planner because they contain an engineering action.
    """
    return bool(_GOODBYE_ONLY_RE.search(text)) and not bool(
        _ENGINEERING_ACTION_RE.search(text)
    )


def _routing_instructions(base: str) -> str:
    """Inject the selected company/team into the shared CS decision prompt.

    This adds only public routing information, never the CEO or employee
    system prompts.  If the company layer is absent in an older deployment the
    receptionist keeps its existing conservative behaviour.
    """
    try:
        from qoder_company.company_state import receptionist_routing_brief  # noqa: PLC0415

        return f"{base}\n\n{receptionist_routing_brief()}"
    except Exception as exc:
        _log("ROUTING", f"active company brief unavailable: {exc}")
        return base


async def plan_call_turn(transcript: str) -> CallTurn:
    """Use the reasoning model to choose a reply, dispatch, or hang-up action.

    This is the control plane of the cascaded call architecture: ASR text goes
    to a text reasoning model with explicit tools, then the bridge executes the
    chosen action and TTS voices the result.  It intentionally does *not* ask a
    realtime audio model to make safety-sensitive tool decisions.
    """
    text = (transcript or "").strip()
    if not text:
        return CallTurn(reply="我刚才没有听清，可以再说一遍吗？")
    if _is_goodbye_only_turn(text):
        return CallTurn(action="end_call", reply="好，那我先挂了。下次见。")
    if not STEPFUN_API_KEY:
        return CallTurn(reply="我现在的语音决策服务还没有连上，可以稍后再试一次。")

    payload = {
        "model": CS_BRAIN_MODEL,
        "messages": [
            {"role": "system", "content": _routing_instructions(CALL_ROUTER_INSTRUCTIONS)},
            {"role": "user", "content": text},
        ],
        "tools": CALL_TOOLS,
        "tool_choice": "auto",
        "reasoning_format": "general",
    }
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(
                f"{STEPFUN_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {STEPFUN_API_KEY}"},
                json=payload,
            )
        if response.status_code != 200:
            _log("PLAN", f"brain non-200: {response.status_code} {response.text[:120]}")
            # A transient rate limit must not discard a request that already
            # matches our deliberately narrow local definition of explicit
            # software work.  This keeps tool execution reliable without
            # allowing small-talk or ambiguous requests to bypass the LLM.
            if _looks_like_explicit_software_task(text):
                _log("PLAN", "using conservative explicit-task fallback")
                return CallTurn(action="dispatch", task=text)
            return CallTurn(reply="我这边正在重新连线，麻烦你稍后再说一次。")

        choice = (response.json().get("choices") or [{}])[0]
        message = choice.get("message") or {}
        reply = (message.get("content") or "").strip()
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            name = function.get("name")
            try:
                args = json.loads(function.get("arguments") or "{}")
            except (TypeError, json.JSONDecodeError):
                args = {}
            if name == "dispatch_to_engineer":
                task = (args.get("task") or "").strip()
                if task and not task.startswith("-"):
                    return CallTurn(action="dispatch", reply=reply, task=task)
            if name == "end_call":
                return CallTurn(action="end_call", reply=reply)

        # Tool calling is usually reliable for text models, but a concrete
        # software ask must not disappear merely because the model replied in
        # prose.  Use the caller's own words as the safe fallback task only
        # when the action is unmistakable; vague turns still get a reply.
        if _looks_like_explicit_software_task(text):
            return CallTurn(action="dispatch", reply=reply, task=text)
        return CallTurn(reply=reply or "我在听。你想先聊聊哪一部分？")
    except Exception as exc:
        _log("PLAN", f"error: {exc}")
        if _looks_like_explicit_software_task(text):
            _log("PLAN", "using conservative explicit-task fallback after error")
            return CallTurn(action="dispatch", task=text)
        return CallTurn(reply="我刚刚没有接稳这句话，可以再说一遍吗？")


async def plan_call_opening() -> str:
    """Generate, rather than hard-code, the first spoken turn of a call.

    Reasoning models can occasionally consume their whole first completion on
    hidden reasoning and return an empty ``content`` field.  Retry that case
    once with more room; both attempts remain model-authored and neither falls
    back to a prerecorded or literal greeting.
    """
    if not STEPFUN_API_KEY:
        return ""
    attempt_prompts = (
        "The voice call has connected. Open the conversation now.",
        "The call is still connected. Say the actual one-sentence spoken greeting now; do not explain it.",
    )
    for max_tokens, user_prompt in zip((512, 1024), attempt_prompts):
        payload = {
            "model": CS_BRAIN_MODEL,
            "messages": [
                {"role": "system", "content": CALL_OPENING_INSTRUCTIONS},
                {"role": "user", "content": user_prompt},
            ],
            # ``step-3.5-flash`` spends part of this budget on reasoning.  The
            # first attempt is normally sufficient; a larger second attempt
            # prevents an empty spoken turn when reasoning exhausts it.
            "max_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                response = await client.post(
                    f"{STEPFUN_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {STEPFUN_API_KEY}"},
                    json=payload,
                )
            if response.status_code != 200:
                _log("OPENING", f"brain non-200: {response.status_code} {response.text[:120]}")
                return ""
            choice = (response.json().get("choices") or [{}])[0]
            opening = ((choice.get("message") or {}).get("content") or "").strip()
            if opening:
                return opening
            _log("OPENING", f"empty content (finish={choice.get('finish_reason', 'unknown')})")
        except Exception as exc:
            _log("OPENING", f"error: {exc}")
            return ""
    return ""

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
    from receptionist.state import load_state, save_state

    # The active company is the authority for the CEO prompt, specialist roster,
    # persistent Qoder session and safe permission profile.  If this optional
    # layer is unavailable, retain the original configured backend as a graceful
    # compatibility path for older deployments.
    company_context: dict[str, Any] | None = None
    backend = _CALL_BACKEND
    try:
        from qoder_company.company_state import active_dispatch_context  # noqa: PLC0415

        company_context = active_dispatch_context()
        backend = str(company_context.get("backend") or backend)
    except Exception as exc:
        _log("DISPATCH", f"company preset unavailable; using {backend}: {exc}")

    task_hash = hashlib.sha256(task.encode()).hexdigest()[:8]
    _log("DISPATCH", f"task#{task_hash} backend={backend}")

    try:
        Path(_CALL_REPO).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

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
        if backend == "qoder" and company_context is not None:
            # The company route owns the observer as well as Qoder.  Starting
            # it here gives the board actual tool/log events from this same
            # CEO execution instead of launching a duplicate demo task.
            from web.qoder_company_routes import _runs, start_company_run  # noqa: PLC0415

            run = await start_company_run(task, repo_path=_CALL_REPO)
            tid = run["run_id"]

            async def _wait_for_company_run() -> None:
                while _runs.get(tid, {}).get("status") == "running":
                    await asyncio.sleep(0.15)
                completed = _runs.get(tid, {})
                observer = completed.get("observer")
                messages = []
                if observer is not None:
                    messages = [event.get("subtitle", "") for event in observer.emitted[-3:]]
                summary = completed.get("error") or next((m for m in reversed(messages) if m), "Qoder task complete")
                await _on_complete(SimpleNamespace(summary=summary))

            asyncio.create_task(_wait_for_company_run())
        else:
            from receptionist.core import Receptionist  # noqa: PLC0415

            receptionist = Receptionist()
            tid = await receptionist.dispatch_async(
                task,
                backend=backend,
                repo_path=_CALL_REPO,
                context=company_context,
                on_complete=_on_complete,
            )
    except Exception as exc:
        _log("DISPATCH", f"dispatch failed: {exc}")
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

    # Legacy non-Qoder backends have no observer, so keep the former best-effort
    # board trigger for them.  The Qoder branch above already drives the board.
    if backend != "qoder":
        asyncio.create_task(_notify_company_board(task))

    ack: dict[str, Any] = {"status": "dispatched", "task_id": tid, "backend": backend}
    if company_context is not None:
        ack.update(
            {
                "company_id": company_context.get("company_id"),
                "company_name": company_context.get("company_name"),
                "company_preset_id": company_context.get("company_preset_id"),
                "team_preset_id": company_context.get("team_preset_id"),
                "team_name": company_context.get("team_name"),
                "roles": list((company_context.get("roles") or {}).keys()),
            }
        )
    return ack


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
    if _is_status_or_social_turn(text):
        _log("CLASSIFY", "conversation/status turn — no engineering handoff")
        return

    payload = {
        "model": CS_BRAIN_MODEL,
        "messages": [
            {
                "role": "system",
                "content": _routing_instructions(CS_TRIAGE_INSTRUCTIONS),
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
                        # The dispatch acknowledgement contains the task id and
                        # backend, but the browser needs the human-readable task
                        # to show the CS → CEO handoff in its transcript panel.
                        result = on_dispatched({**info, "task": task})
                        if asyncio.isfuture(result):
                            await result
                    except Exception as exc:
                        _log("CLASSIFY", f"on_dispatched error: {exc}")
                return
    except Exception as exc:
        _log("CLASSIFY", f"error: {exc}")
