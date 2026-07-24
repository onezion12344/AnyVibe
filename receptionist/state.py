"""receptionist/state.py — Minimal state helpers for the ~/.coding-vibe/ session store.

Matches the JSON schema in cv_mcp/server.py without pulling in the whole MCP stack.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _get_state_dir() -> Path:
    """Read CODING_VIBE_STATE_DIR at call time so monkeypatch works."""
    return Path(os.environ.get("CODING_VIBE_STATE_DIR", Path.home() / ".coding-vibe"))


def _get_state_file() -> Path:
    return _get_state_dir() / "session.json"


def load_state() -> dict[str, Any]:
    """Return the current session dict, or a fresh skeleton."""
    state_file = _get_state_file()
    _get_state_dir().mkdir(parents=True, exist_ok=True)
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {"checkpoints": [], "delegations": [], "created_at": time.time()}


def save_state(state: dict[str, Any]) -> None:
    """Persist session dict to disk."""
    _get_state_file().write_text(json.dumps(state, indent=2, ensure_ascii=False))


def append_checkpoint(
    milestone: str,
    message: str,
    *,
    progress_pct: int = 50,
    task_id: str | None = None,
    files_changed: list[str] | None = None,
) -> dict[str, Any]:
    """Load state, append a checkpoint, save, and return the checkpoint dict.

    Mirrors the checkpoint shape written by ``coding_vibe_checkpoint`` and
    ``coding_vibe_complete_delegation`` in ``cv_mcp/server.py``.
    """
    state = load_state()
    checkpoint: dict[str, Any] = {
        "milestone": milestone,
        "message": message,
        "progress_pct": progress_pct,
        "timestamp": time.time(),
    }
    if task_id is not None:
        checkpoint["task_id"] = task_id
    if files_changed is not None:
        checkpoint["files_changed"] = files_changed

    state["checkpoints"].append(checkpoint)
    state["last_checkpoint"] = checkpoint
    save_state(state)
    return checkpoint


def reset_state() -> None:
    """Delete the current session.json — useful in tests."""
    _get_state_file().unlink(missing_ok=True)
