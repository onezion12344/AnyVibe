"""receptionist/adapters/__init__.py — Re-export base classes + register built-ins.

Built-in adapters self-register via ``@register_adapter`` (a late import is used
to avoid circular imports, since ``adapters.base`` is imported by ``registry``).

Drop-in plugins (``~/.coding-vibe/plugins/*.py``) follow the same pattern: define
a ``HarnessAdapter`` subclass with ``@register_adapter`` and drop the file in place.
No edit to this file or ``registry.py`` is required.
"""

from __future__ import annotations

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult


def _register_builtins() -> None:
    """Lazily import each built-in adapter and register it.

    Late import prevents the circular chain: registry → adapters → registry.
    """
    from receptionist.registry import register_adapter  # noqa: PLC0415

    from receptionist.adapters.claude_code import ClaudeCodeAdapter
    from receptionist.adapters.mock import MockAdapter
    from receptionist.adapters.openopc import OpenOPCAdapter
    from receptionist.adapters.qoder import QoderAdapter

    register_adapter(MockAdapter)
    register_adapter(ClaudeCodeAdapter)
    register_adapter(OpenOPCAdapter)
    register_adapter(QoderAdapter)


# Side-effect: register built-ins at package import time.
# _discover_directory imports `receptionist.adapters` as a package first,
# which triggers this block, then falls back to per-file imports for plugins.
_register_builtins()

__all__ = ["HarnessAdapter", "StatusEvent", "TaskResult"]
