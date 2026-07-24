# receptionist — Harness-Agnostic Orchestration Layer for coding-vibe

```
receptionist/
├── adapters/
│   ├── base.py        # HarnessAdapter ABC + StatusEvent + TaskResult
│   ├── mock.py        # MockAdapter  (name="mock")
│   ├── claude_code.py # ClaudeCodeAdapter  (name="claude-code")
│   └── openopc.py     # OpenOPCAdapter  (name="openopc")
├── core.py            # Receptionist dispatch loop
├── registry.py        # register_adapter / get_adapter / list_adapters
├── state.py           # ~/.coding-vibe/session.json helpers
└── tests/
    └── test_dispatch.py   # 26 tests, pytest + asyncio
```

## The Adapter Contract

```python
from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

class MyAdapter(HarnessAdapter):
    name = "my-harness"          # registry key

    async def spawn(self, task: str, *, repo_path: str, context=None) -> str: ...
    async def stream_status(self, handle: str): ...   # -> AsyncIterator[StatusEvent]
    async def result(self, handle: str) -> TaskResult: ...
    async def cancel(self, handle: str) -> None: ...   # default no-op
```

**`StatusEvent`**
```
kind  ∈ {"progress" | "tool" | "message" | "done" | "error"}
text  : str
```

**`TaskResult`**
```
ok          : bool
summary     : str
files_changed : list[str]
raw         : str   # full harness output
```

## Registering a new adapter

```python
from receptionist.registry import register_adapter
from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult

@register_adapter
class AiderAdapter(HarnessAdapter):
    name = "aider"
    # ... implement spawn / stream_status / result
```

Or place the class in `receptionist/adapters/` and add it to `receptionist/adapters/__init__.py` alongside the existing imports.

## Dispatch flow

```
Receptionist.dispatch(task, backend="mock", repo_path="/path/to/project")
  │
  ├─ spawn(task) ────────────────────────────────────────────────────────── handle
  │
  ├─ stream_status(handle)
  │     └─ each StatusEvent → append_checkpoint() to ~/.coding-vibe/session.json
  │
  ├─ result(handle) ────────────────────────────────────────────────────── TaskResult
  │
  └─ append_checkpoint(milestone="task-complete", …)   ← MCP/hooks can read this
```

The `~/.coding-vibe/session.json` store is shared with `cv_mcp/server.py` — the
existing MCP tooling picks up progress checkpoints transparently.

## Currently registered adapters

| Key | Backend | Notes |
|-----|---------|-------|
| `mock` | In-memory | All tests use this by default |
| `claude-code` | `claude -p --output-format stream-json` | Needs `claude` on PATH |
| `openopc` | `uv run opc exec … --stream-json` | Needs `opc` + `uv` on PATH |

## Running tests

```bash
# Install dev deps
pip install pytest pytest-asyncio

# Run
pytest receptionist/tests/test_dispatch.py -v   # 26 tests
```

## State reuse

`receptionist/state.py` reads/writes the same `~/.coding-vibe/session.json` as
`cv_mcp/server.py`. The Receptionist writes one checkpoint per `StatusEvent` and
a final `"task-complete"` checkpoint — the MCP hook reads exactly this file.

Do **not** import or depend on `cv_mcp` inside receptionist. The state helpers
stand alone.

## Upgrade path

When any harness ships a production A2A adapter, the stdio transport inside
`claude_code.py` / `openopc.py` is the natural seam to swap. The
`HarnessAdapter` interface and the Receptionist dispatch loop remain unchanged.
