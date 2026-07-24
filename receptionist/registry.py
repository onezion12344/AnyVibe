"""receptionist/registry.py — Adapter registry."""

from __future__ import annotations

from receptionist.adapters.base import HarnessAdapter

_REGISTRY: dict[str, type[HarnessAdapter]] = {}


def register_adapter(cls: type[HarnessAdapter]) -> type[HarnessAdapter]:
    """Decorator / direct call: register a HarnessAdapter subclass.

    The class must have a non-empty ``name`` attribute.
    """
    key = cls.name
    if not key:
        raise ValueError(f"Adapter class {cls!r} has an empty 'name' attribute")
    _REGISTRY[key] = cls
    return cls


def get_adapter(name: str) -> type[HarnessAdapter]:
    """Return the adapter class registered under *name*.

    Raises ``KeyError`` if not registered.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"No adapter registered as {name!r}. "
            f"Registered adapters: {list(_REGISTRY)}"
        )


def list_adapters() -> list[str]:
    """Return all registered adapter names."""
    return sorted(_REGISTRY)
