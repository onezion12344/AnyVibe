"""receptionist/registry.py — Adapter registry with auto-discovery."""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import sys
from pathlib import Path
from types import ModuleType

from receptionist.adapters.base import HarnessAdapter

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[HarnessAdapter]] = {}

# ---------------------------------------------------------------------------
# Discovery bookkeeping (idempotency guard)
# ---------------------------------------------------------------------------
_discovered_dirs: set[str] = set()   # dir paths already scanned
_discovered_eps: set[str] = set()    # entry-point names already loaded

# ---------------------------------------------------------------------------
# Built-in & external plugin directories
# ---------------------------------------------------------------------------
_BUILTIN_ADAPTERS_DIR: Path = Path(__file__).parent / "adapters"
_EXTERNAL_PLUGINS_DIR: Path = Path.home() / ".coding-vibe" / "plugins"
_ENTRY_POINT_GROUP = "coding_vibe.adapters"


# ---------------------------------------------------------------------------
# Public decorator / direct-call API (unchanged contract)
# ---------------------------------------------------------------------------

def register_adapter(cls: type[HarnessAdapter]) -> type[HarnessAdapter]:
    """Decorator / direct call: register a HarnessAdapter subclass.

    The class must have a non-empty ``name`` attribute.
    """
    key = cls.name
    if not key:
        raise ValueError(f"Adapter class {cls!r} has an empty 'name' attribute")
    _REGISTRY[key] = cls
    return cls


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _register_builtins() -> None:
    """Lazily import each built-in adapter and register it.

    Late import prevents the circular chain: registry → adapters → registry.
    """
    from receptionist.registry import register_adapter  # noqa: PLC0415 — intentional late import

    from receptionist.adapters.claude_code import ClaudeCodeAdapter
    from receptionist.adapters.mock import MockAdapter
    from receptionist.adapters.openopc import OpenOPCAdapter
    from receptionist.adapters.qoder import QoderAdapter

    register_adapter(MockAdapter)
    register_adapter(ClaudeCodeAdapter)
    register_adapter(OpenOPCAdapter)
    register_adapter(QoderAdapter)


def _ensure_discovered() -> None:
    """Run discovery once (idempotent). Called lazily on first registry access."""
    _discover_directory(_BUILTIN_ADAPTERS_DIR)
    _discover_directory(_EXTERNAL_PLUGINS_DIR)
    _discover_entry_points()


def reset_registry() -> None:
    """Full reset of all registry state.

    Clears the adapter registry, all discovery bookkeeping, and re-runs
    ``_register_builtins()`` so built-in adapters are immediately available
    again.  Intended for testing only.
    """
    _REGISTRY.clear()
    _discovered_dirs.clear()
    _discovered_eps.clear()
    _register_builtins()


def discover_adapters() -> dict[str, type[HarnessAdapter]]:
    """Explicitly run both discovery mechanisms and return the full registry.

    Idempotent: safe to call multiple times; already-seen dirs and
    entry-point names are skipped on subsequent calls.

    Mechanisms
    ----------
    1. **Directory auto-discovery** — imports every ``*.py`` module (except
       ``__init__``) in ``receptionist/adapters/`` and
       ``~/.coding-vibe/plugins/`` so that any ``@register_adapter``-decorated
       class inside fires at import time.
    2. **Entry-point discovery** — loads Python packages that declare
       ``[project.entry-points."coding_vibe.adapters"]`` in their
       ``pyproject.toml``.

    Returns
    -------
    dict[str, type[HarnessAdapter]]
        Snapshot of the full registry after discovery.
    """
    _ensure_discovered()
    return dict(_REGISTRY)


def _discover_directory(dir_path: Path) -> None:
    """Import every ``*.py`` module in *dir_path* (except ``__init__``).

    Strategy:
    1. If the dir has an ``__init__.py``, import it as a package
       (triggers ``__init__.py`` self-registration of built-in adapters).
    2. For directories without ``__init__.py`` (e.g. ``~/.coding-vibe/plugins/``):
       add the directory itself to ``sys.path`` and import each ``*.py`` file
       by its bare module name (stem).  This means drop-in plugin modules must
       use absolute imports (e.g. ``from receptionist.adapters.base import …``),
       which works because the project root is already on ``sys.path``.

    Safe to call with a non-existent directory; the call is a no-op.
    Skips directories already scanned (idempotent guard).
    """
    dir_str = str(dir_path)
    if dir_str in _discovered_dirs:
        return

    if not dir_path.is_dir():
        _discovered_dirs.add(dir_str)
        return

    # Try Strategy 1: package import (dir has __init__.py)
    has_init = (dir_path / "__init__.py").exists()
    pkg_imported = False
    if has_init:
        try:
            pkg_root = _find_package_root(dir_path)
            if pkg_root and str(pkg_root) not in sys.path:
                sys.path.insert(0, str(pkg_root))
            prefix = _dotted_prefix(dir_path)
            if prefix:
                importlib.import_module(prefix)
                pkg_imported = True
        except Exception as exc:
            logger.debug("Package import of %r failed (%s); falling back to per-file.", dir_path.name, exc)

    # Strategy 2: bare-file import via sys.path injection (for non-package dirs)
    if not pkg_imported:
        try:
            dir_str_sys = str(dir_path)
            if dir_str_sys not in sys.path:
                sys.path.insert(0, dir_str_sys)
            for py_file in sorted(dir_path.glob("*.py")):
                if py_file.name == "__init__.py":
                    continue
                module_name = py_file.stem
                if module_name in sys.modules:
                    continue
                try:
                    importlib.import_module(module_name)
                except Exception as exc:
                    logger.warning("Failed to import adapter module %s: %s", module_name, exc)
        except Exception as exc:
            logger.warning("Failed to scan directory %s: %s", dir_path, exc)

    _discovered_dirs.add(dir_str)


def _find_package_root(dir_path: Path) -> Path | None:
    """Walk up from *dir_path* to find the directory that is the ``receptionist``
    package root itself (i.e. the directory that contains ``receptionist/__init__.py``).

    For ``…/receptionist/adapters`` the answer is ``…/`` (the parent of receptionist/).

    If the package is already importable on ``sys.path``, falls back to the
    directory of the already-loaded ``receptionist`` package (robust for test
    environments and editable installs).
    """
    # Fast path: receptionist is already importable — derive root from it
    if "receptionist" in sys.modules:
        rec_mod = sys.modules["receptionist"]
        rec_file = getattr(rec_mod, "__file__", None)
        if rec_file:
            rec_dir = Path(rec_file).parent   # receptionist/
            return rec_dir.parent              # parent of receptionist/

    # Walk up: return the first ancestor that directly contains a
    # ``receptionist/`` sub-directory (i.e. the parent of receptionist/).
    candidate = dir_path
    while candidate != candidate.parent:
        if (candidate / "receptionist").is_dir():
            return candidate
        candidate = candidate.parent
    return None


def _dotted_prefix(dir_path: Path) -> str:
    """Return the dotted package prefix for *dir_path*, e.g.
    ``receptionist.adapters`` for ``…/receptionist/adapters``.

    Returns an empty string if the dir is not inside the package root
    (caller should then use Strategy 2: sys.path injection).
    """
    try:
        pkg_root = _find_package_root(dir_path)
    except Exception:
        return ""
    if pkg_root is None:
        return ""
    try:
        rel = dir_path.relative_to(pkg_root)
    except ValueError:
        return ""
    parts = list(rel.parts)
    return ".".join(parts) if parts else ""


def _discover_entry_points() -> None:
    """Load all adapters registered via the ``coding_vibe.adapters`` entry-point group."""
    try:
        raw_eps = importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP)
    except Exception:
        # importlib.metadata < 3.10 uses .get(); try that path too
        try:
            raw_eps = importlib.metadata.entry_points().get(_ENTRY_POINT_GROUP, [])
        except Exception:
            raw_eps = []

    for ep in raw_eps:
        ep_name = ep.name
        if ep_name in _discovered_eps:
            continue

        try:
            obj = ep.load()
            # Accept either the class itself or a module that contains it
            if isinstance(obj, type) and issubclass(obj, HarnessAdapter):
                _register_loaded_adapter(obj)
            elif isinstance(obj, ModuleType):
                _scan_module_for_adapters(obj)
            else:
                logger.warning(
                    "Entry point %r loaded unexpected type %r; skipping.",
                    ep_name, type(obj),
                )
        except Exception as exc:
            logger.warning("Failed to load entry point %r: %s", ep_name, exc)

        _discovered_eps.add(ep_name)


def _scan_module_for_adapters(module: ModuleType) -> None:
    """Walk *module*'s attributes looking for HarnessAdapter subclasses and register them."""
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        obj = getattr(module, attr_name)
        if isinstance(obj, type) and issubclass(obj, HarnessAdapter) and obj is not HarnessAdapter:
            _register_loaded_adapter(obj)


def _register_loaded_adapter(cls: type[HarnessAdapter]) -> None:
    """Register *cls*, logging a warning on name collision (last-wins semantics)."""
    key = cls.name
    if not key:
        logger.warning("Discovered adapter class %r has empty 'name'; skipping.", cls)
        return
    if key in _REGISTRY and _REGISTRY[key] is not cls:
        logger.warning(
            "Adapter name %r collision: previously %r, now %r. "
            "Last-wins: %r takes effect.",
            key, _REGISTRY[key], cls, cls,
        )
    register_adapter(cls)


# ---------------------------------------------------------------------------
# Accessors (lazy discovery on first call)
# ---------------------------------------------------------------------------

def get_adapter(name: str) -> type[HarnessAdapter]:
    """Return the adapter class registered under *name*.

    Runs discovery on first call if it has not been run yet.
    Raises ``KeyError`` if not registered.
    """
    _ensure_discovered()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"No adapter registered as {name!r}. "
            f"Registered adapters: {list(_REGISTRY)}"
        )


def reset_registry() -> None:
    """Full reset of all registry state.

    Clears the adapter registry, all discovery bookkeeping, and re-runs
    ``_register_builtins()`` so built-in adapters are immediately available
    again.  Intended for testing only.
    """
    _REGISTRY.clear()
    _discovered_dirs.clear()
    _discovered_eps.clear()
    _register_builtins()


def list_adapters() -> list[str]:
    """Return all registered adapter names.

    Runs discovery on first call if it has not been run yet.
    """
    _ensure_discovered()
    return sorted(_REGISTRY)
