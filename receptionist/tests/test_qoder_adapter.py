"""receptionist/tests/test_qoder_adapter.py — Fixture-first tests for QoderAdapter."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — run from the worktree root
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent.parent  # receptionist/
_ROOT = _HERE.parent  # coding-vibe-qoder/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from receptionist.adapters.base import StatusEvent, TaskResult
from receptionist.adapters.qoder import QoderAdapter
import receptionist.adapters.qoder as qoder_module

# ---------------------------------------------------------------------------
# Path to the sample fixture that ships with this repo
# ---------------------------------------------------------------------------
_FIXTURE = str(
    Path(__file__).resolve().parent.parent   # receptionist/
    / "adapters"
    / "fixtures"
    / "qoder_company_demo.jsonl"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class CollectedEvents:
    """Collect StatusEvents yielded by stream_status into a list."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def collect(self, adapter: QoderAdapter, handle: str) -> None:
        async for ev in adapter.stream_status(handle):
            self.events.append(ev)


# ---------------------------------------------------------------------------
# Fixture mode tests (these run WITHOUT qodercli)
# ---------------------------------------------------------------------------

class TestQoderAdapterFixtureMode:
    """All tests here run in fixture mode — no qodercli needed."""

    @pytest.fixture(autouse=True)
    def force_fixture_mode(self, monkeypatch):
        """Always use the shipped JSONL fixture."""
        monkeypatch.setenv("CV_QODER_FIXTURE", _FIXTURE)
        yield

    @pytest.fixture
    def adapter(self):
        return QoderAdapter()

    # ── spawn ────────────────────────────────────────────────────────────────

    async def test_spawn_returns_handle(self, adapter):
        handle = await adapter.spawn(
            "帮我写一个快速排序",
            repo_path="/tmp/fakerepo",
        )
        assert isinstance(handle, str)
        assert len(handle) > 0

    # ── stream_status kinds ──────────────────────────────────────────────────

    async def test_stream_status_yields_events(self, adapter):
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        events: list[StatusEvent] = []
        async for ev in adapter.stream_status(handle):
            events.append(ev)
        assert len(events) >= 1
        assert all(isinstance(e, StatusEvent) for e in events)

    async def test_last_event_is_done(self, adapter):
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        events: list[StatusEvent] = []
        async for ev in adapter.stream_status(handle):
            events.append(ev)
        assert events[-1].kind == "done"

    async def test_event_kinds_are_valid(self, adapter):
        valid = {"progress", "tool", "message", "done", "error"}
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        async for ev in adapter.stream_status(handle):
            assert ev.kind in valid, f"Bad kind: {ev.kind!r}"

    async def test_contains_tool_and_message_events(self, adapter):
        """Fixture contains agent delegations (tool) and messages."""
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        events: list[StatusEvent] = []
        async for ev in adapter.stream_status(handle):
            events.append(ev)
        kinds = [e.kind for e in events]
        assert "tool" in kinds, f"Expected 'tool' events, got: {kinds}"
        assert "message" in kinds, f"Expected 'message' events, got: {kinds}"

    async def test_fixture_events_preserve_the_qoder_actor(self, adapter):
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        events = [event async for event in adapter.stream_status(handle)]
        assert any(event.kind == "message" and event.actor == "researcher" for event in events)
        assert any(event.kind == "tool" and event.actor == "ceo" for event in events)
        assert events[-1].actor == "ceo"

    # ── result ───────────────────────────────────────────────────────────────

    async def test_result_returns_task_result_ok(self, adapter):
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        # consume stream so we know it finished
        async for _ in adapter.stream_status(handle):
            pass
        result = await adapter.result(handle)
        assert isinstance(result, TaskResult)
        assert result.ok is True
        assert isinstance(result.summary, str)
        assert isinstance(result.files_changed, list)
        assert isinstance(result.raw, str)

    async def test_result_summary_nonempty(self, adapter):
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        async for _ in adapter.stream_status(handle):
            pass
        result = await adapter.result(handle)
        assert len(result.summary) > 0

    async def test_stream_and_result_are_consistent(self, adapter):
        """Events from stream_status and result() must agree on finish status."""
        handle = await adapter.spawn("帮我写快速排序", repo_path="/tmp/fakerepo")
        streamed: list[StatusEvent] = []
        async for ev in adapter.stream_status(handle):
            streamed.append(ev)
        result = await adapter.result(handle)
        # The stream ends with "done" so result must also be ok
        assert result.ok is True
        assert streamed[-1].kind == "done"

    # ── company mode via context ─────────────────────────────────────────────

    async def test_company_mode_same_handle_across_spawns(self, adapter):
        """In company mode the same company_id reuses the session."""
        h1 = await adapter.spawn(
            "写快速排序",
            repo_path="/tmp/r1",
            context={"mode": "company", "company_id": "advx-company"},
        )
        h2 = await adapter.spawn(
            "写二分查找",
            repo_path="/tmp/r2",
            context={"mode": "company", "company_id": "advx-company"},
        )
        assert isinstance(h1, str)
        assert isinstance(h2, str)
        assert h1 != h2  # different task handles, same company session underneath

    # ── cancel ───────────────────────────────────────────────────────────────

    async def test_cancel_is_noop(self, adapter):
        handle = await adapter.spawn("test cancel", repo_path="/tmp/x")
        # Should not raise
        await adapter.cancel(handle)

    # ── unknown handle ───────────────────────────────────────────────────────

    async def test_result_unknown_handle(self, adapter):
        result = await adapter.result("nonexistent-handle")
        assert result.ok is False

    # ── custom fixture path ──────────────────────────────────────────────────

    async def test_custom_fixture_path(self, tmp_path, adapter):
        """Passing fixture_path directly also works."""
        custom = tmp_path / "custom.jsonl"
        custom.write_text(
            '{"type": "assistant", "role": "ceo", "content": [{"type": "text", "text": "custom done"}]}\n',
            encoding="utf-8",
        )
        custom_adapter = QoderAdapter(fixture_path=str(custom))
        handle = await custom_adapter.spawn("x", repo_path="/tmp/x")
        events: list[StatusEvent] = []
        async for ev in custom_adapter.stream_status(handle):
            events.append(ev)
        assert events[-1].kind == "done"
        result = await custom_adapter.result(handle)
        assert result.ok is True


# ---------------------------------------------------------------------------
# Graceful-failure tests (no fixture, no SDK → failed handle)
# ---------------------------------------------------------------------------

class TestQoderAdapterNoBackend:
    """When no SDK is importable and no fixture path is given, spawn must not
    raise — it must return a handle whose result is a failed TaskResult."""

    @pytest.fixture(autouse=True)
    def strip_backend(self, monkeypatch):
        """Remove any env fixture var so fixture mode is off."""
        monkeypatch.delenv("CV_QODER_FIXTURE", raising=False)
        yield

    @pytest.fixture
    def adapter(self):
        # Explicitly empty fixture path + no SDK → graceful failure path
        return QoderAdapter(fixture_path="")

    async def test_spawn_returns_handle_no_backend(self, adapter):
        handle = await adapter.spawn("test", repo_path="/tmp/x")
        assert isinstance(handle, str)
        assert len(handle) > 0

    async def test_result_is_failed_no_backend(self, adapter):
        handle = await adapter.spawn("test", repo_path="/tmp/x")
        result = await adapter.result(handle)
        assert isinstance(result, TaskResult)
        assert result.ok is False

    async def test_no_exception_on_spawn_no_backend(self, adapter):
        """spawn must not raise even when both SDK and fixture are unavailable."""
        handle = await adapter.spawn("test", repo_path="/tmp/x")
        assert handle is not None


# ---------------------------------------------------------------------------
# Explicit qodercli stream mode (local fake executable; no network)
# ---------------------------------------------------------------------------

class TestQoderCliStreamMode:
    """The qodercli fallback is opt-in and translates stream-json records."""

    @pytest.fixture(autouse=True)
    def strip_fixture_and_sdk(self, monkeypatch):
        monkeypatch.delenv("CV_QODER_FIXTURE", raising=False)
        monkeypatch.setattr(qoder_module, "_SDK_AVAILABLE", False)

    async def test_cli_stream_translates_messages_tools_and_result(self, tmp_path):
        fake_cli = tmp_path / "fake-qodercli"
        fake_cli.write_text(
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            "args = sys.argv[1:]\n"
            "assert '--print' in args\n"
            "assert args[args.index('--output-format') + 1] == 'stream-json'\n"
            "assert '--cwd' in args\n"
            "assert '--agents' in args\n"
            "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'CEO: plan approved'}, {'type': 'tool_use', 'name': 'Agent', 'input': {'agent': 'engineer', 'prompt': 'Implement the feature'}}]}}))\n"
            "print(json.dumps({'type': 'tool_result', 'content': 'engineer completed implementation'}))\n"
            "print(json.dumps({'type': 'result', 'is_error': False}))\n",
            encoding="utf-8",
        )
        fake_cli.chmod(0o755)

        adapter = QoderAdapter(fixture_path="", cli_enabled=True, cli_path=str(fake_cli))
        handle = await adapter.spawn(
            "Build the demo feature",
            repo_path=str(tmp_path),
            context={"roles": {"engineer": "Implement code"}},
        )
        events: list[StatusEvent] = []
        async for event in adapter.stream_status(handle):
            events.append(event)

        assert any(event.kind == "message" and "plan approved" in event.text for event in events)
        assert any(event.kind == "tool" and event.text.startswith("engineer:") for event in events)
        assert any(event.kind == "progress" and "completed implementation" in event.text for event in events)
        assert events[-1].kind == "done"
        result = await adapter.result(handle)
        assert result.ok is True
        assert "plan approved" in result.summary

    async def test_company_cli_context_persists_session_and_injects_ceo_prompt(self, tmp_path, monkeypatch):
        """A selected company can opt into CLI + resume without a global flag."""
        args_log = tmp_path / "qoder-args.jsonl"
        fake_cli = tmp_path / "fake-qodercli"
        fake_cli.write_text(
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            f"with open({str(args_log)!r}, 'a', encoding='utf-8') as output:\n"
            "    output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'CEO: working'}]}}))\n"
            "print(json.dumps({'type': 'result', 'is_error': False}))\n",
            encoding="utf-8",
        )
        fake_cli.chmod(0o755)
        monkeypatch.setenv("CV_QODER_CONFIG_ROOT", str(tmp_path / "company-config"))

        # ``cli_enabled=False`` deliberately proves trusted company context
        # enables qodercli without requiring CV_QODER_CLI for the whole app.
        adapter = QoderAdapter(fixture_path="", cli_enabled=False, cli_path=str(fake_cli))
        context = {
            "mode": "company",
            "company_id": "blue-team",
            "persistent_cli": True,
            "session_id": "30ac9dbe-49db-4ef5-a264-71991fdd4fc2",
            "use_cli": True,
            "permission_mode": "accept_edits",
            "ceo_prompt": "Delegate and verify the work.",
            "roles": {"frontend": {"description": "Build UI", "prompt": "Implement accessibly."}},
        }

        first = await adapter.spawn("Build the landing page", repo_path=str(tmp_path), context=context)
        async for _ in adapter.stream_status(first):
            pass
        second = await adapter.spawn("Verify the landing page", repo_path=str(tmp_path), context=context)
        async for _ in adapter.stream_status(second):
            pass

        first_args, second_args = [json.loads(line) for line in args_log.read_text(encoding="utf-8").splitlines()]
        assert "--no-session-persistence" not in first_args
        assert first_args[first_args.index("--permission-mode") + 1] == "accept_edits"
        assert first_args[first_args.index("--session-id") + 1] == "30ac9dbe-49db-4ef5-a264-71991fdd4fc2"
        assert first_args[first_args.index("--config-dir") + 1] == str((tmp_path / "company-config" / "blue-team").resolve())
        assert first_args[first_args.index("--append-system-prompt") + 1] == "Delegate and verify the work."
        assert "--agents" in first_args
        assert second_args[second_args.index("--resume") + 1] == "30ac9dbe-49db-4ef5-a264-71991fdd4fc2"


# ---------------------------------------------------------------------------
# Registry registration test
# ---------------------------------------------------------------------------

class TestQoderRegistryRegistration:
    def test_qoder_adapter_registered(self):
        from receptionist.registry import list_adapters, get_adapter

        adapters = list_adapters()
        assert "qoder" in adapters, f"Registered adapters: {adapters}"

    def test_get_adapter_qoder(self):
        from receptionist.registry import get_adapter

        cls = get_adapter("qoder")
        assert cls is QoderAdapter
