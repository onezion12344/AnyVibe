"""Tests for receptionist/tests/test_dispatch.py"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

from receptionist.adapters.base import StatusEvent, TaskResult
from receptionist.adapters.mock import MockAdapter
from receptionist.core import Receptionist, DEFAULT_ENGINEER_DIRECTIVE
from receptionist.registry import get_adapter, list_adapters, register_adapter, discover_adapters
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


# ---------------------------------------------------------------------------
# dispatch_async tests
# ---------------------------------------------------------------------------

class TestDispatchAsync:
    """Tests for Receptionist.dispatch_async()."""

    async def test_returns_handle_immediately(
        self, isolated_state_dir, receptionist, mock_adapter
    ):
        """dispatch_async returns before the mock's work is done."""
        slow_adapter = MockAdapter(delay=0.1)
        # Patch get_adapter to return the slow adapter
        import receptionist.registry as reg
        original = reg._REGISTRY["mock"]
        reg._REGISTRY["mock"] = type(slow_adapter)

        handle = await receptionist.dispatch_async(
            "slow task", backend="mock", repo_path="/tmp/slow"
        )
        assert isinstance(handle, str)
        assert len(handle) == 8  # 8-char uuid fragment

        reg._REGISTRY["mock"] = original
        # Give background task time to finish to avoid un-awaited-task warnings
        await asyncio.sleep(0.3)

    async def test_handle_returned_before_on_complete_fires(
        self, isolated_state_dir, receptionist
    ):
        """The task_id is returned before on_complete is called."""
        on_complete_order: list[str] = []

        # Use a fast MockAdapter (no delay), but track ordering carefully
        handle = await receptionist.dispatch_async(
            "task",
            backend="mock",
            repo_path="/tmp/x",
            on_complete=lambda result: on_complete_order.append("complete"),
        )
        # handle must be set before on_complete fires
        assert len(handle) > 0

        # Allow the background task to complete
        await asyncio.sleep(0.2)
        assert "complete" in on_complete_order

    async def test_on_status_fires_per_event(
        self, isolated_state_dir, receptionist
    ):
        """on_status is called once per StatusEvent emitted by the adapter."""
        events_seen: list[str] = []

        def on_status(event: StatusEvent) -> None:
            events_seen.append(event.kind)

        handle = await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", on_status=on_status
        )

        await asyncio.sleep(0.2)

        # MockAdapter emits 6 events by default
        assert len(events_seen) == 6
        assert events_seen[-1] == "done"

    async def test_on_complete_fires_once_with_result(
        self, isolated_state_dir, receptionist
    ):
        """on_complete receives the final TaskResult exactly once."""
        results: list[TaskResult] = []

        def on_complete(result: TaskResult) -> None:
            results.append(result)

        await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", on_complete=on_complete
        )
        await asyncio.sleep(0.2)

        assert len(results) == 1
        assert isinstance(results[0], TaskResult)
        assert results[0].ok is True
        assert "Mock task completed successfully" in results[0].summary

    async def test_async_on_status_callback_awaited(
        self, isolated_state_dir, receptionist
    ):
        """on_status coroutine functions are awaited, not just called."""
        seen: list[str] = []

        async def on_status(event: StatusEvent) -> None:
            # Verify we are truly async
            await asyncio.sleep(0)
            seen.append(event.kind)

        await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", on_status=on_status
        )
        await asyncio.sleep(0.2)

        assert len(seen) == 6
        assert seen[-1] == "done"

    async def test_async_on_complete_callback_awaited(
        self, isolated_state_dir, receptionist
    ):
        """on_complete coroutine functions are awaited."""
        results: list[TaskResult] = []

        async def on_complete(result: TaskResult) -> None:
            await asyncio.sleep(0)
            results.append(result)

        await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", on_complete=on_complete
        )
        await asyncio.sleep(0.2)

        assert len(results) == 1
        assert isinstance(results[0], TaskResult)

    async def test_raising_on_status_does_not_crash(
        self, isolated_state_dir, receptionist
    ):
        """If on_status raises, the dispatch still completes and checkpoints are written."""
        def bad_on_status(event: StatusEvent) -> None:
            raise RuntimeError("callback broken")

        handle = await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", on_status=bad_on_status
        )
        await asyncio.sleep(0.2)

        # task-complete checkpoint must still be written
        state = load_state()
        milestones = [cp["milestone"] for cp in state["checkpoints"]]
        assert "task-complete" in milestones

    async def test_raising_on_complete_does_not_crash(
        self, isolated_state_dir, receptionist
    ):
        """If on_complete raises, the dispatch still finishes cleanly."""
        def bad_on_complete(result: TaskResult) -> None:
            raise RuntimeError("oops in callback")

        handle = await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", on_complete=bad_on_complete
        )
        await asyncio.sleep(0.2)

        # checkpoints still written
        state = load_state()
        milestones = [cp["milestone"] for cp in state["checkpoints"]]
        assert "task-complete" in milestones

    async def test_checkpoints_written_by_async_dispatch(
        self, isolated_state_dir, receptionist
    ):
        """dispatch_async writes the same progress + task-complete checkpoints as dispatch."""
        task_id = await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", context={"task_id": "async1"}
        )
        await asyncio.sleep(0.2)

        state = load_state()
        kinds = [cp["milestone"] for cp in state["checkpoints"]]
        assert "done" in kinds
        assert "task-complete" in kinds

        # task-complete must have the right fields
        tc = state["checkpoints"][-1]
        assert tc["milestone"] == "task-complete"
        assert tc["progress_pct"] == 100
        # dispatch_async always stores its own generated task_id (UUID fragment)
        # in the checkpoint, overriding any user-supplied context["task_id"]
        assert tc["task_id"] == task_id
        assert "src/foo.py" in tc.get("files_changed", [])

    async def test_result_method_returns_none_for_unknown_id(self, receptionist):
        """result() returns None for an unknown task_id."""
        res = await receptionist.result("nonexistent-id")
        assert res is None

    async def test_result_method_tracks_task(self, isolated_state_dir, receptionist):
        """result(task_id) blocks until the background task finishes."""
        await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x"
        )
        # After awaiting the specific task result, checkpoints are present
        await asyncio.sleep(0.2)

    async def test_no_callbacks_no_crash(self, isolated_state_dir, receptionist):
        """dispatch_async with no callbacks works fine."""
        handle = await receptionist.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x"
        )
        assert isinstance(handle, str)
        await asyncio.sleep(0.2)

        state = load_state()
        assert state["checkpoints"][-1]["milestone"] == "task-complete"

    async def test_dispatch_async_returns_before_on_complete(self, isolated_state_dir):
        """Assert ordering: handle returned first, on_complete fires later."""
        ordering: list[str] = []

        def on_complete(_: TaskResult) -> None:
            ordering.append("on_complete")

        r = Receptionist()
        handle = await r.dispatch_async(
            "task", backend="mock", repo_path="/tmp/x", on_complete=on_complete
        )
        ordering.append("handle")

        # At this exact moment on_complete should NOT have fired yet
        assert ordering == ["handle"]

        await asyncio.sleep(0.2)
        assert "on_complete" in ordering


# ---------------------------------------------------------------------------
# Auto-discovery tests
# ---------------------------------------------------------------------------

class TestAdapterDiscovery:
    """Tests for directory auto-discovery and entry-point discovery."""

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _fresh_registry(monkeypatch=None):
        """Return a fully-reset registry; optionally monkeypatch _EXTERNAL_PLUGINS_DIR."""
        import receptionist.registry as reg
        reg.reset_registry()
        if monkeypatch is not None:
            monkeypatch.setattr(reg, "_EXTERNAL_PLUGINS_DIR", reg._EXTERNAL_PLUGINS_DIR)
        return reg

    # ---- built-in adapters discoverable via list_adapters ------------------

    def test_builtins_auto_discovered_via_list(self):
        """Built-in adapters are discoverable without any explicit imports."""
        adapters = list_adapters()
        assert "mock" in adapters
        assert "claude-code" in adapters
        assert "openopc" in adapters

    def test_builtins_auto_discovered_via_get(self):
        """get_adapter() returns built-in classes after auto-discovery."""
        from receptionist.adapters.mock import MockAdapter
        from receptionist.adapters.claude_code import ClaudeCodeAdapter
        from receptionist.adapters.openopc import OpenOPCAdapter

        assert get_adapter("mock") is MockAdapter
        assert get_adapter("claude-code") is ClaudeCodeAdapter
        assert get_adapter("openopc") is OpenOPCAdapter

    # ---- drop-in directory plugin -----------------------------------------

    def test_dropin_plugin_discovered(self, tmp_path, monkeypatch):
        """A ``*.py`` file dropped in the plugins dir is auto-imported and registered."""
        reg = self._fresh_registry(monkeypatch)

        # Write a minimal adapter into a temp plugins directory.
        # Because plugins/ has no __init__.py, Strategy 2 (sys.path injection) is used.
        plugins_dir = tmp_path / "my-plugins"
        plugins_dir.mkdir()
        adapter_code = """\
from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult
from receptionist.registry import register_adapter


class MyDropinAdapter(HarnessAdapter):
    name = "my-dropin"
    async def spawn(self, task, *, repo_path, context=None):
        return "handle-1"
    async def stream_status(self, handle):
        yield StatusEvent(kind="done", text="done")
        return
        yield
    async def result(self, handle):
        return TaskResult(ok=True, summary="ok", files_changed=[], raw="ok")


register_adapter(MyDropinAdapter)
"""
        (plugins_dir / "my_adapter.py").write_text(adapter_code)

        # Override the external plugins dir and add it to sys.path so the
        # drop-in module can import receptionist.adapters.base successfully.
        monkeypatch.setattr(reg, "_EXTERNAL_PLUGINS_DIR", plugins_dir)
        import sys as _sys
        _sys.path.insert(0, str(plugins_dir))

        # Run discovery only for the external plugins dir.
        # _discovered_dirs already contains the built-ins path from reset_registry(),
        # so calling _discover_directory on the overridden path is safe.
        reg._discover_directory(plugins_dir)

        assert "my-dropin" in reg.list_adapters()
        cls = reg.get_adapter("my-dropin")
        assert cls.__name__ == "MyDropinAdapter"

        _sys.path.remove(str(plugins_dir))

    def test_dropin_plugin_get_adapter_works(self, tmp_path, monkeypatch):
        """get_adapter / dispatch works with a drop-in plugin adapter."""
        reg = self._fresh_registry(monkeypatch)

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        adapter_code = """\
from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult
from receptionist.registry import register_adapter


class QuickAdapter(HarnessAdapter):
    name = "quick"
    async def spawn(self, task, *, repo_path, context=None):
        return "h"
    async def stream_status(self, handle):
        yield StatusEvent(kind="done", text="quick done")
        return
        yield
    async def result(self, handle):
        return TaskResult(ok=True, summary="quick", files_changed=[], raw="quick")


register_adapter(QuickAdapter)
"""
        (plugins_dir / "quick_adapter.py").write_text(adapter_code)

        monkeypatch.setattr(reg, "_EXTERNAL_PLUGINS_DIR", plugins_dir)
        import sys as _sys
        _sys.path.insert(0, str(plugins_dir))
        reg._discover_directory(plugins_dir)

        cls = reg.get_adapter("quick")
        assert cls.__name__ == "QuickAdapter"
        _sys.path.remove(str(plugins_dir))

    # ---- entry-point discovery --------------------------------------------

    def test_entry_point_discovery_registers_adapter(self, monkeypatch):
        """An entry point resolved to a HarnessAdapter subclass is registered."""
        reg = self._fresh_registry(monkeypatch)

        from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

        class _EPAdapter(HarnessAdapter):
            name = "ep-adapter"
            async def spawn(self, task, *, repo_path, context=None): ...
            async def stream_status(self, handle): ...
            async def result(self, handle): ...

        # Build a fake entry-point object that matches importlib.metadata.EntryPoint
        class _FakeEP:
            def __init__(self, name, obj):
                self.name = name
                self._obj = obj

            def load(self):
                return self._obj

        fake_ep = _FakeEP("ep-adapter", _EPAdapter)

        # Monkey-patch importlib.metadata.entry_points to return our fake EP
        import importlib.metadata as _im

        def _fake_eps(group=None):
            if group == "coding_vibe.adapters":
                return [fake_ep]
            if group is None:
                return {"coding_vibe.adapters": [fake_ep]}
            return []

        monkeypatch.setattr(_im, "entry_points", _fake_eps)

        reg.discover_adapters()
        assert "ep-adapter" in reg.list_adapters()
        assert reg.get_adapter("ep-adapter") is _EPAdapter

    def test_entry_point_module_load(self, monkeypatch):
        """An entry point that loads a module triggers _scan_module_for_adapters."""
        import sys as _sys
        reg = self._fresh_registry(monkeypatch)

        from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

        class ModAdapter(HarnessAdapter):
            name = "mod-ep-adapter"
            async def spawn(self, task, *, repo_path, context=None): ...
            async def stream_status(self, handle): ...
            async def result(self, handle): ...

        # Build a fake module with ModAdapter as an attribute
        fake_module = type(sys)("fake_pkg.adapter")
        fake_module.ModAdapter = ModAdapter

        class _FakeEP:
            def __init__(self, name):
                self.name = name

            def load(self):
                return fake_module

        fake_ep = _FakeEP("mod-ep-adapter")

        import importlib.metadata as _im

        def _fake_eps(group=None):
            if group == "coding_vibe.adapters":
                return [fake_ep]
            if group is None:
                return {"coding_vibe.adapters": [fake_ep]}
            return []

        monkeypatch.setattr(_im, "entry_points", _fake_eps)

        reg.discover_adapters()
        assert "mod-ep-adapter" in reg.list_adapters()

    # ---- idempotency ------------------------------------------------------

    def test_discover_adapters_idempotent(self):
        """Calling discover_adapters() twice does not duplicate or crash."""
        first = discover_adapters()
        second = discover_adapters()
        assert list(first) == list(second)
        # All built-ins present
        assert "mock" in first
        assert "claude-code" in first
        assert "openopc" in first

    def test_discover_idempotent_no_duplicate_registration(self, monkeypatch):
        """Second discovery pass must not change the registry contents."""
        reg = self._fresh_registry(monkeypatch)
        # Run once
        reg.discover_adapters()
        names_after_first = sorted(reg._REGISTRY)
        # Run again
        reg.discover_adapters()
        names_after_second = sorted(reg._REGISTRY)
        assert names_after_first == names_after_second

    # ---- name collision handling ------------------------------------------

    def test_name_collision_logged_last_wins(self, tmp_path, monkeypatch, caplog):
        """If two adapters share a name, last-wins wins and a warning is logged."""
        reg = self._fresh_registry(monkeypatch)

        # Use _register_loaded_adapter directly (the entry-point discovery path)
        # rather than scanning plugin files, which call register_adapter directly.
        from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

        class _FirstAdapter(HarnessAdapter):
            name = "same-name"
            async def spawn(self, t, *, r, c=None): ...
            async def stream_status(self, h): ...
            async def result(self, h):
                return TaskResult(ok=True, summary="first", files_changed=[], raw="first")

        class _SecondAdapter(HarnessAdapter):
            name = "same-name"
            async def spawn(self, t, *, r, c=None): ...
            async def stream_status(self, h): ...
            async def result(self, h):
                return TaskResult(ok=True, summary="second", files_changed=[], raw="second")

        with caplog.at_level("WARNING", logger="receptionist.registry"):
            reg._register_loaded_adapter(_FirstAdapter)
            reg._register_loaded_adapter(_SecondAdapter)

        # Second wins (last-wins semantics)
        assert reg.get_adapter("same-name") is _SecondAdapter
        # A collision warning was logged on the second registration
        assert any(
            "collision" in record.getMessage().lower() for record in caplog.records
        )

    # ---- external plugins dir does not need to exist -----------------------

    def test_external_plugins_dir_missing_is_ok(self, monkeypatch):
        """If ~/.coding-vibe/plugins/ does not exist, discovery still works."""
        import receptionist.registry
        # Point to a non-existent directory
        monkeypatch.setattr(
            receptionist.registry,
            "_EXTERNAL_PLUGINS_DIR",
            Path("/tmp/definitely-does-not-exist-xyzzy"),
        )
        # Should not raise; reset so adapters dir isn't already marked discovered
        reg = self._fresh_registry(monkeypatch)
        reg.discover_adapters()
        # Built-ins still work
        assert "mock" in reg.list_adapters()

    # ---- built-ins still in registry after discover ------------------------

    def test_adapters_dir_module_init_does_not_register(self):
        """__init__.py in adapters/ no longer calls register_adapter directly."""
        # The __init__ should only re-export; the actual registration happens
        # via _register_builtins() called lazily.
        from receptionist.registry import _REGISTRY
        import receptionist.adapters as adapters_pkg
        # The package itself must not be a registered adapter name
        assert adapters_pkg.__name__ not in _REGISTRY


# ---------------------------------------------------------------------------
# Engineer directive (fan-out) tests
# ---------------------------------------------------------------------------

class _SpyAdapter(MockAdapter):
    """MockAdapter that records the exact task string handed to spawn().

    ``core`` instantiates adapters via ``get_adapter(backend)()`` (no args), so
    the receptionist creates a *fresh* instance we cannot reach directly.  We
    record onto a class-level list so the test can inspect what spawn() saw.
    """

    name = "spy"
    received_tasks: list[str] = []

    async def spawn(self, task: str, *, repo_path: str, context: dict | None = None) -> str:
        type(self).received_tasks.append(task)
        return await super().spawn(task, repo_path=repo_path, context=context)


@pytest.fixture
def spy_backend():
    """Register the spy adapter under "spy" and clear its recording buffer."""
    register_adapter(_SpyAdapter)
    _SpyAdapter.received_tasks = []
    yield _SpyAdapter
    _SpyAdapter.received_tasks = []


class TestEngineerDirective:
    """The receptionist prepends a fan-out directive to the task by default."""

    async def test_default_directive_prepended(self, isolated_state_dir, spy_backend):
        """By default, the task handed to the adapter includes the fan-out directive."""
        await Receptionist().dispatch(
            "add a /health endpoint", backend="spy", repo_path="/tmp/x"
        )
        assert len(spy_backend.received_tasks) == 1
        sent = spy_backend.received_tasks[0]
        assert sent.startswith(DEFAULT_ENGINEER_DIRECTIVE)
        assert sent.endswith("add a /health endpoint")
        assert "add a /health endpoint" in sent
        # The directive is separated from the task by the "---" fence.
        assert "\n\n---\n\n" in sent

    async def test_directive_mentions_parallel_subagents(self):
        """Sanity: the built-in directive actually pushes for parallel subagents."""
        low = DEFAULT_ENGINEER_DIRECTIVE.lower()
        assert "subagent" in low
        assert "parallel" in low or "concurrent" in low or "concurrently" in low

    async def test_disable_with_empty_string(self, isolated_state_dir, spy_backend):
        """An empty-string directive disables augmentation — task passes unchanged."""
        await Receptionist(engineer_directive="").dispatch(
            "verbatim task", backend="spy", repo_path="/tmp/x"
        )
        assert spy_backend.received_tasks == ["verbatim task"]

    async def test_constructor_override(self, isolated_state_dir, spy_backend):
        """A custom instance directive is used verbatim."""
        await Receptionist(engineer_directive="CUSTOM PREAMBLE").dispatch(
            "the task", backend="spy", repo_path="/tmp/x"
        )
        assert spy_backend.received_tasks == ["CUSTOM PREAMBLE\n\n---\n\nthe task"]

    async def test_per_dispatch_override(self, isolated_state_dir, spy_backend):
        """A per-dispatch directive overrides the instance default."""
        r = Receptionist(engineer_directive="INSTANCE")
        await r.dispatch(
            "t", backend="spy", repo_path="/tmp/x", engineer_directive="PERCALL"
        )
        assert spy_backend.received_tasks == ["PERCALL\n\n---\n\nt"]

    async def test_per_dispatch_disable(self, isolated_state_dir, spy_backend):
        """Passing engineer_directive="" to dispatch disables for that call only."""
        r = Receptionist()  # default directive active
        await r.dispatch("t", backend="spy", repo_path="/tmp/x", engineer_directive="")
        assert spy_backend.received_tasks == ["t"]

    async def test_env_override(self, isolated_state_dir, spy_backend, monkeypatch):
        """CV_ENGINEER_DIRECTIVE overrides the built-in default when instance dir is None."""
        monkeypatch.setenv("CV_ENGINEER_DIRECTIVE", "ENV DIRECTIVE")
        await Receptionist().dispatch("t", backend="spy", repo_path="/tmp/x")
        assert spy_backend.received_tasks == ["ENV DIRECTIVE\n\n---\n\nt"]

    async def test_constructor_beats_env(self, isolated_state_dir, spy_backend, monkeypatch):
        """An explicit constructor directive wins over the env var."""
        monkeypatch.setenv("CV_ENGINEER_DIRECTIVE", "ENV DIRECTIVE")
        await Receptionist(engineer_directive="CTOR").dispatch(
            "t", backend="spy", repo_path="/tmp/x"
        )
        assert spy_backend.received_tasks == ["CTOR\n\n---\n\nt"]

    async def test_dispatch_async_applies_directive(self, isolated_state_dir, spy_backend):
        """dispatch_async augments the task exactly like dispatch."""
        await Receptionist(engineer_directive="ASYNC PREAMBLE").dispatch_async(
            "async task", backend="spy", repo_path="/tmp/x"
        )
        await asyncio.sleep(0.2)
        assert spy_backend.received_tasks == ["ASYNC PREAMBLE\n\n---\n\nasync task"]

    async def test_dispatch_async_default_directive(self, isolated_state_dir, spy_backend):
        """dispatch_async uses the built-in default when none is configured."""
        await Receptionist().dispatch_async(
            "async default", backend="spy", repo_path="/tmp/x"
        )
        await asyncio.sleep(0.2)
        assert len(spy_backend.received_tasks) == 1
        assert spy_backend.received_tasks[0].startswith(DEFAULT_ENGINEER_DIRECTIVE)
        assert spy_backend.received_tasks[0].endswith("async default")

    async def test_dispatch_async_per_call_disable(self, isolated_state_dir, spy_backend):
        """dispatch_async honours a per-call empty-string disable."""
        await Receptionist().dispatch_async(
            "raw", backend="spy", repo_path="/tmp/x", engineer_directive=""
        )
        await asyncio.sleep(0.2)
        assert spy_backend.received_tasks == ["raw"]
