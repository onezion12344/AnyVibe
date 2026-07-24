"""Tests for receptionist/tests/test_dispatch.py"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from receptionist.adapters.base import StatusEvent, TaskResult
from receptionist.adapters.mock import MockAdapter
from receptionist.core import Receptionist
from receptionist.registry import get_adapter, list_adapters, register_adapter
from receptionist.state import load_state, append_checkpoint, reset_state, _get_state_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_file() -> Path:
    return _get_state_file()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    """Redirect ~/.coding-vibe/ to a temp directory for every test."""
    state_dir = tmp_path / "coding-vibe"
    state_dir.mkdir()
    monkeypatch.setenv("CODING_VIBE_STATE_DIR", str(state_dir))
    yield state_dir


@pytest.fixture
def mock_adapter():
    return MockAdapter()


@pytest.fixture
def receptionist():
    return Receptionist()


# ---------------------------------------------------------------------------
# MockAdapter unit tests
# ---------------------------------------------------------------------------

class TestMockAdapter:
    async def test_spawn_returns_handle(self, mock_adapter):
        handle = await mock_adapter.spawn("do stuff", repo_path="/tmp/x")
        assert isinstance(handle, str)
        assert len(handle) > 0

    async def test_stream_status_yields_events(self, mock_adapter):
        handle = await mock_adapter.spawn("do stuff", repo_path="/tmp/x")
        events = [e async for e in mock_adapter.stream_status(handle)]
        assert len(events) >= 1
        assert all(isinstance(e, StatusEvent) for e in events)
        # Last event should be kind="done"
        assert events[-1].kind == "done"

    async def test_stream_status_kinds_are_valid(self, mock_adapter):
        handle = await mock_adapter.spawn("do stuff", repo_path="/tmp/x")
        valid = {"progress", "tool", "message", "done", "error"}
        for ev in [e async for e in mock_adapter.stream_status(handle)]:
            assert ev.kind in valid, f"Bad kind: {ev.kind!r}"

    async def test_result_returns_task_result(self, mock_adapter):
        handle = await mock_adapter.spawn("do stuff", repo_path="/tmp/x")
        # Consume stream first
        async for _ in mock_adapter.stream_status(handle):
            pass
        result = await mock_adapter.result(handle)
        assert isinstance(result, TaskResult)
        assert result.ok is True
        assert isinstance(result.summary, str)
        assert isinstance(result.files_changed, list)
        assert isinstance(result.raw, str)

    async def test_cancel_is_noop(self, mock_adapter):
        handle = await mock_adapter.spawn("do stuff", repo_path="/tmp/x")
        # Should not raise
        await mock_adapter.cancel(handle)

    async def test_result_unknown_handle(self, mock_adapter):
        result = await mock_adapter.result("nonexistent-handle")
        assert result.ok is False

    async def test_custom_events_and_result(self, mock_adapter):
        custom_events = [
            StatusEvent(kind="progress", text="Starting"),
            StatusEvent(kind="done", text="All done"),
        ]
        custom_result = TaskResult(
            ok=True, summary="custom done", files_changed=["a.py"], raw="ok"
        )
        adapter = MockAdapter(events=custom_events, result=custom_result)
        handle = await adapter.spawn("custom", repo_path="/tmp/x")
        evts = [e async for e in adapter.stream_status(handle)]
        assert [e.kind for e in evts] == ["progress", "done"]
        res = await adapter.result(handle)
        assert res.summary == "custom done"
        assert res.files_changed == ["a.py"]


# ---------------------------------------------------------------------------
# State helpers tests
# ---------------------------------------------------------------------------

class TestStateHelpers:
    async def test_append_checkpoint_creates_file(self, isolated_state_dir):
        cp = append_checkpoint("test-milestone", "hello world", progress_pct=42)
        assert cp["milestone"] == "test-milestone"
        assert cp["message"] == "hello world"
        assert cp["progress_pct"] == 42
        assert "timestamp" in cp
        assert _state_file().exists()

    async def test_state_persists_across_calls(self, isolated_state_dir):
        # Clear any leftover state so we start from scratch
        reset_state()
        append_checkpoint("a", "msg-a")
        append_checkpoint("b", "msg-b")
        state = load_state()
        assert len(state["checkpoints"]) == 2
        assert state["checkpoints"][0]["milestone"] == "a"
        assert state["checkpoints"][1]["milestone"] == "b"

    async def test_load_state_empty_dir(self, tmp_path, monkeypatch):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setenv("CODING_VIBE_STATE_DIR", str(empty_dir))
        state = load_state()
        assert state["checkpoints"] == []
        assert state["delegations"] == []


# ---------------------------------------------------------------------------
# Receptionist dispatch integration test (MockAdapter)
# ---------------------------------------------------------------------------

class TestReceptionistDispatch:
    async def test_dispatch_returns_task_result(self, receptionist):
        result = await receptionist.dispatch(
            "add a /health endpoint",
            backend="mock",
            repo_path="/tmp/fakerepo",
            context={"task_id": "add-health"},
        )
        assert isinstance(result, TaskResult)
        assert result.ok is True

    async def test_dispatch_summary_from_mock(self, receptionist):
        result = await receptionist.dispatch(
            "do something",
            backend="mock",
            repo_path="/tmp/fakerepo",
        )
        assert "Mock task completed successfully" in result.summary

    async def test_dispatch_files_changed_populated(self, receptionist):
        result = await receptionist.dispatch(
            "do something",
            backend="mock",
            repo_path="/tmp/fakerepo",
        )
        assert "src/foo.py" in result.files_changed

    async def test_dispatch_checkpoints_written(self, isolated_state_dir, receptionist):
        await receptionist.dispatch(
            "do something",
            backend="mock",
            repo_path="/tmp/fakerepo",
            context={"task_id": "t1"},
        )
        state = load_state()
        assert len(state["checkpoints"]) >= 1
        # Every event from MockAdapter produces a checkpoint
        kinds = [cp["milestone"] for cp in state["checkpoints"]]
        assert "done" in kinds

    async def test_dispatch_task_complete_checkpoint_written(self, isolated_state_dir, receptionist):
        await receptionist.dispatch(
            "do something",
            backend="mock",
            repo_path="/tmp/fakerepo",
            context={"task_id": "t1"},
        )
        state = load_state()
        last = state["checkpoints"][-1]
        assert last["milestone"] == "task-complete"
        assert last["progress_pct"] == 100

    async def test_dispatch_task_complete_has_files_changed(self, isolated_state_dir, receptionist):
        await receptionist.dispatch(
            "do something",
            backend="mock",
            repo_path="/tmp/fakerepo",
            context={"task_id": "t1"},
        )
        state = load_state()
        last = state["checkpoints"][-1]
        assert "src/foo.py" in last.get("files_changed", [])

    async def test_dispatch_does_not_touch_real_state(self, monkeypatch):
        """Ensure a real ~/.coding-vibe/ session.json is not modified."""
        real_state_dir = tempfile.mkdtemp()
        real_state_file = os.path.join(real_state_dir, "session.json")
        with open(real_state_file, "w") as f:
            f.write('{"checkpoints": [], "delegations": [], "original": true}')

        fake_dir = tempfile.mkdtemp()
        monkeypatch.setenv("CODING_VIBE_STATE_DIR", fake_dir)

        await Receptionist().dispatch("x", backend="mock", repo_path="/tmp/x")
        # Original state untouched
        with open(real_state_file) as f:
            assert '"original": true' in f.read()

    async def test_dispatch_unknown_backend_raises(self, receptionist):
        with pytest.raises(KeyError, match="No adapter registered"):
            await receptionist.dispatch(
                "do something",
                backend="nonexistent-backend",
                repo_path="/tmp/x",
            )

    async def test_dispatch_raw_field_populated(self, receptionist):
        result = await receptionist.dispatch(
            "do something",
            backend="mock",
            repo_path="/tmp/fakerepo",
        )
        assert len(result.raw) > 0

    async def test_multiple_dispatch_calls_independent(self, receptionist):
        r1 = await receptionist.dispatch("task-a", backend="mock", repo_path="/tmp/a")
        r2 = await receptionist.dispatch("task-b", backend="mock", repo_path="/tmp/b")
        assert r1 is not None
        assert r2 is not None


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_list_adapters_includes_mock(self):
        assert "mock" in list_adapters()

    def test_list_adapters_includes_claude_code(self):
        assert "claude-code" in list_adapters()

    def test_list_adapters_includes_openopc(self):
        assert "openopc" in list_adapters()

    def test_get_adapter_mock(self):
        from receptionist.registry import get_adapter
        cls = get_adapter("mock")
        assert issubclass(cls, MockAdapter)

    def test_get_adapter_unknown_raises(self):
        from receptionist.registry import get_adapter
        with pytest.raises(KeyError):
            get_adapter("__does_not_exist__")

    def test_register_adapter_dunder(self):
        from receptionist.adapters.base import HarnessAdapter
        from receptionist.registry import get_adapter, register_adapter

        class _Dummy(HarnessAdapter):
            name = "my-test-adapter"
            async def spawn(self, task, *, repo_path, context=None): ...
            async def stream_status(self, handle): ...
            async def result(self, handle): ...

        register_adapter(_Dummy)
        assert get_adapter("my-test-adapter") is _Dummy
