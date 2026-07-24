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
pytest receptionist/tests/test_dispatch.py -v   # 61 tests
```

## State reuse

`receptionist/state.py` reads/writes the same `~/.coding-vibe/session.json` as
`cv_mcp/server.py`. The Receptionist writes one checkpoint per `StatusEvent` and
a final `"task-complete"` checkpoint — the MCP hook reads exactly this file.

Do **not** import or depend on `cv_mcp` inside receptionist. The state helpers
stand alone.

## Engineer directive (default fan-out)

By default the Receptionist prepends a **fan-out directive** to every task
before it reaches the adapter. The directive instructs the engineer (the CEO)
to, by default, decompose the work into independent parallel workstreams and
deploy **multiple subagents concurrently** (using its harness's parallel-agent
/ Task-tool capability), then converge and verify the combined result — rather
than doing a single sequential pass.

The composed task is:

```
<directive>

---

<original task>
```

This is pure string composition inside `core.py` — the Receptionist still only
ever calls the `HarnessAdapter` interface. No CLI/subprocess logic lives in
core.

### Configuring / overriding / disabling

Precedence (highest first): per-dispatch arg → instance default → env var →
built-in default.

```python
from receptionist.core import Receptionist, DEFAULT_ENGINEER_DIRECTIVE

# 1. Built-in default (fan-out) — nothing to configure
await Receptionist().dispatch(task, backend="claude-code", repo_path=repo)

# 2. Instance-level custom directive
r = Receptionist(engineer_directive="Focus on a single careful pass.")

# 3. Disable entirely — task passes through verbatim
r = Receptionist(engineer_directive="")

# 4. Per-dispatch override (falls back to the instance default when omitted)
await r.dispatch(task, backend="mock", repo_path=repo,
                 engineer_directive="one-off directive")
await r.dispatch(task, backend="mock", repo_path=repo,
                 engineer_directive="")   # disable for this call only
```

- Constructor param `engineer_directive`: `None` (default) resolves at dispatch
  time; `""` disables; any other string is used verbatim.
- Env override `CV_ENGINEER_DIRECTIVE`: used when the instance directive is
  `None`. An explicit constructor value beats the env var.
- Both `dispatch()` and `dispatch_async()` apply the directive identically.

## Upgrade path

When any harness ships a production A2A adapter, the stdio transport inside
`claude_code.py` / `openopc.py` is the natural seam to swap. The
`HarnessAdapter` interface and the Receptionist dispatch loop remain unchanged.
