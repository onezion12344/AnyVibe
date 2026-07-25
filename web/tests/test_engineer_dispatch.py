from __future__ import annotations

import asyncio

import pytest

import web.engineer_dispatch as engineer_dispatch


class _ClassificationResponse:
    status_code = 200
    text = ""

    @staticmethod
    def json() -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "dispatch_to_engineer",
                                    "arguments": '{"task":"Build a timer app"}',
                                }
                            }
                        ]
                    }
                }
            ]
        }


class _ClassificationClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return _ClassificationResponse()


class _UnexpectedClassificationClient:
    """Makes an accidental model call fail the test immediately."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise AssertionError("a status conversation must not reach the dispatch model")


class _CallPlanningResponse:
    status_code = 200
    text = ""

    @staticmethod
    def json() -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "我已经把需求交给团队了。",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "dispatch_to_engineer",
                                    "arguments": '{"task":"给网站添加登录功能"}',
                                }
                            }
                        ],
                    }
                }
            ]
        }


class _CallPlanningClient:
    def __init__(self) -> None:
        self.payload: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **kwargs):
        self.payload = kwargs["json"]
        return _CallPlanningResponse()


class _RateLimitedResponse:
    status_code = 429
    text = '{"error":{"message":"request limited"}}'


class _RateLimitedPlanningClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return _RateLimitedResponse()


class _OpeningResponse:
    status_code = 200
    text = ""

    @staticmethod
    def json() -> dict:
        return {"choices": [{"message": {"content": "你好，我是黄羊。今天想一起推进什么？"}}]}


class _OpeningClient:
    def __init__(self) -> None:
        self.payload: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **kwargs):
        self.payload = kwargs["json"]
        return _OpeningResponse()


class _EmptyOpeningThenGreetingClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **kwargs):
        self.payloads.append(kwargs["json"])
        content = "" if len(self.payloads) == 1 else "嗨，今天想聊点什么？"
        return type(
            "OpeningResponse",
            (),
            {
                "status_code": 200,
                "text": "",
                "json": staticmethod(
                    lambda: {"choices": [{"finish_reason": "length", "message": {"content": content}}]}
                ),
            },
        )()


@pytest.mark.asyncio
async def test_voice_dispatch_callback_receives_the_task_text(monkeypatch):
    """The voice UI needs the routed task, not only the opaque task id."""
    monkeypatch.setattr(engineer_dispatch, "STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(engineer_dispatch.httpx, "AsyncClient", lambda **_kwargs: _ClassificationClient())

    async def fake_dispatch(task: str) -> dict:
        assert task == "Build a timer app"
        return {"status": "dispatched", "task_id": "task-123", "backend": "mock"}

    monkeypatch.setattr(engineer_dispatch, "dispatch_to_engineer", fake_dispatch)
    received: list[dict] = []

    await engineer_dispatch.classify_and_dispatch("please make a timer", received.append)

    assert received == [
        {
            "status": "dispatched",
            "task_id": "task-123",
            "backend": "mock",
            "task": "Build a timer app",
        }
    ]


@pytest.mark.asyncio
async def test_status_report_is_not_sent_to_triage_or_engineers(monkeypatch):
    """A friendly check-in must never silently create a coding ticket."""
    monkeypatch.setattr(engineer_dispatch, "STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(
        engineer_dispatch.httpx,
        "AsyncClient",
        _UnexpectedClassificationClient,
    )
    received: list[dict] = []

    await engineer_dispatch.classify_and_dispatch(
        "诶，你最近怎么样了？然后你给我报告一下。",
        received.append,
    )

    assert received == []


@pytest.mark.asyncio
async def test_call_planner_uses_explicit_text_tool_for_software_work(monkeypatch):
    """The cascaded call brain receives both its tool schema and reply text."""
    monkeypatch.setattr(engineer_dispatch, "STEPFUN_API_KEY", "test-key")
    client = _CallPlanningClient()
    monkeypatch.setattr(
        engineer_dispatch.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    decision = await engineer_dispatch.plan_call_turn(
        "请给网站添加登录功能", caller_name="Harry"
    )

    assert decision.action == "dispatch"
    assert decision.task == "给网站添加登录功能"
    assert decision.reply == "我已经把需求交给团队了。"
    assert client.payload is not None
    assert "preferred name is 'Harry'" in client.payload["messages"][0]["content"]


@pytest.mark.asyncio
async def test_rate_limited_planner_keeps_only_clear_software_dispatches(monkeypatch):
    """A 429 must not turn an explicit feature request into lost work."""
    monkeypatch.setattr(engineer_dispatch, "STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(
        engineer_dispatch.httpx,
        "AsyncClient",
        lambda **_kwargs: _RateLimitedPlanningClient(),
    )

    feature = await engineer_dispatch.plan_call_turn("请给网站新增导出任务列表按钮")
    social = await engineer_dispatch.plan_call_turn("你最近怎么样了？")

    assert feature.action == "dispatch"
    assert feature.task == "请给网站新增导出任务列表按钮"
    assert social.action == "reply"
    assert not social.task


@pytest.mark.asyncio
async def test_clear_goodbye_ends_without_waiting_for_model(monkeypatch):
    """Goodbyes are an intentional, deterministic call-control action."""
    monkeypatch.setattr(engineer_dispatch, "STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(
        engineer_dispatch.httpx,
        "AsyncClient",
        _UnexpectedClassificationClient,
    )

    decision = await engineer_dispatch.plan_call_turn("再见，拜拜")

    assert decision.action == "end_call"
    assert "挂" in decision.reply


@pytest.mark.asyncio
async def test_call_opening_is_generated_from_fresh_call_context(monkeypatch):
    """The first spoken turn comes from the LLM, not a canned audio script."""
    client = _OpeningClient()
    monkeypatch.setattr(engineer_dispatch, "STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(
        engineer_dispatch.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    opening = await engineer_dispatch.plan_call_opening(caller_name="Harry")

    assert opening == "你好，我是黄羊。今天想一起推进什么？"
    assert client.payload is not None
    instructions = client.payload["messages"][0]["content"]
    assert "new voice call" in instructions
    assert "Never list capabilities" in instructions
    assert "preferred name is 'Harry'" in instructions
    assert client.payload["max_tokens"] == 512
    assert "tools" not in client.payload


@pytest.mark.asyncio
async def test_empty_reasoning_completion_retries_with_a_model_only_opening(monkeypatch):
    client = _EmptyOpeningThenGreetingClient()
    monkeypatch.setattr(engineer_dispatch, "STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(engineer_dispatch.httpx, "AsyncClient", lambda **_kwargs: client)

    opening = await engineer_dispatch.plan_call_opening()

    assert opening == "嗨，今天想聊点什么？"
    assert [payload["max_tokens"] for payload in client.payloads] == [512, 1024]
    assert "actual one-sentence spoken greeting" in client.payloads[1]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_dispatch_runs_the_active_company_once_and_does_not_trigger_a_second_board_job(tmp_path, monkeypatch):
    """Voice dispatch must use the observer-owned Qoder run, not duplicate it."""
    import qoder_company.company_state as company_state
    import web.qoder_company_routes as company_routes
    import web.signaling as signaling
    import receptionist.state as receptionist_state

    calls: list[tuple[str, str]] = []
    saved_states: list[dict] = []
    state = {"delegations": []}
    run_id = "qoder-123"
    monkeypatch.setattr(engineer_dispatch, "_CALL_REPO", str(tmp_path))
    monkeypatch.setattr(
        company_state,
        "active_dispatch_context",
        lambda: {"backend": "qoder", "company_id": "rapid-startup"},
    )

    async def fake_start(task: str, *, repo_path: str, body=None):
        calls.append((task, repo_path))
        return {"run_id": run_id}

    async def fake_ring(**_kwargs):
        return None

    monkeypatch.setattr(company_routes, "start_company_run", fake_start)
    monkeypatch.setattr(company_routes, "_runs", {run_id: {"status": "done", "observer": None}})
    monkeypatch.setattr(signaling, "ring", fake_ring)
    monkeypatch.setattr(receptionist_state, "load_state", lambda: state)
    monkeypatch.setattr(receptionist_state, "save_state", lambda state: saved_states.append(state))

    result = await engineer_dispatch.dispatch_to_engineer("Build a concise landing page")
    await asyncio.sleep(0.05)

    assert result == {"status": "dispatched", "task_id": run_id, "backend": "qoder"}
    assert calls == [("Build a concise landing page", str(tmp_path))]
    assert state["delegations"][-1]["status"] == "completed"
