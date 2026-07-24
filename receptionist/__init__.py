"""receptionist/__init__.py — public surface."""

from receptionist.adapters.base import HarnessAdapter, StatusEvent, TaskResult
from receptionist.core import Receptionist
from receptionist.registry import get_adapter, list_adapters, register_adapter

__all__ = [
    "HarnessAdapter",
    "StatusEvent",
    "TaskResult",
    "Receptionist",
    "register_adapter",
    "get_adapter",
    "list_adapters",
]
