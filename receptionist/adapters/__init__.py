"""receptionist/adapters/__init__.py — Auto-register built-in adapters."""

from receptionist.adapters.base import HarnessAdapter
from receptionist.adapters.claude_code import ClaudeCodeAdapter
from receptionist.adapters.mock import MockAdapter
from receptionist.adapters.openopc import OpenOPCAdapter
from receptionist.registry import register_adapter

register_adapter(MockAdapter)
register_adapter(ClaudeCodeAdapter)
register_adapter(OpenOPCAdapter)
