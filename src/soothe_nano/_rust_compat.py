"""Conditional import layer for Rust-backed implementations.

Centralizes the ``try: from _rust import ... except ImportError: ...`` pattern
so that each Python module can delegate to the compiled PyO3 extension when
available, and fall back to the pure-Python implementation when it is not.

During Phase 1 migration, the Rust extension (``soothe_nano._rust``) is
optional.  When built via maturin, it is importable as a CPython extension
module.  When absent (e.g. during development without ``maturin develop``),
every function transparently falls back to the Python original.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------

_rust_module: Any = None
_rust_available = False

try:  # pragma: no cover - exercised only when the extension is compiled
    from soothe_nano import _rust as _rust_module  # type: ignore[import-not-found]

    _rust_available = True
except ImportError:
    _rust_available = False


def is_rust_available() -> bool:
    """Return True when the compiled Rust extension is importable."""
    return _rust_available


def get_rust_module() -> Any:
    """Return the raw ``_rust`` module, or ``None`` if unavailable."""
    return _rust_module


# ---------------------------------------------------------------------------
# Utils: thread_id
# ---------------------------------------------------------------------------


def generate_thread_id() -> str:
    """Generate a UUID v4 thread ID (Rust-accelerated when available)."""
    if _rust_available:
        return _rust_module.generate_thread_id()
    # Python fallback
    import uuid

    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Utils: json_parsing / repair_json
# ---------------------------------------------------------------------------


def repair_json(raw: str) -> Any:
    """Repair/extract JSON from LLM output (Rust-accelerated when available).

    Returns a Python object (dict/list/None) matching the Python implementation.
    """
    if _rust_available:
        result = _rust_module.repair_json(raw)
        return result  # PyO3 already converts to Python dict/list/None
    # Python fallback — use the full implementation
    from soothe_nano.utils.json_parsing import _load_llm_json_dict

    try:
        return _load_llm_json_dict(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Utils: text_preview (simple truncation)
# ---------------------------------------------------------------------------


def text_preview_rust(text: str, max_chars: int) -> str:
    """Single-line text preview truncated to *max_chars* (Rust when available).

    This is the *simple* variant used by the Rust binding.  The full Python
    ``preview()`` function supports modes, markers, and first/last — those
    stay Python-only until the Rust crate gains feature parity.
    """
    if _rust_available:
        return _rust_module.text_preview(text, max_chars)
    # Python fallback — delegate to the full implementation in "chars" mode
    from soothe_nano.utils.text_preview import preview

    return preview(text, mode="chars", first=max_chars)


# ---------------------------------------------------------------------------
# Tokens: count_tokens
# ---------------------------------------------------------------------------


def count_tokens_rust(text: str, model: str | None = None) -> int:
    """Count tokens via tiktoken-rs (Rust) when available.

    Falls back to the Python ``count_tokens`` when the extension is absent.
    """
    if _rust_available:
        return _rust_module.count_tokens(text, model)
    # Python fallback
    from soothe_nano.utils.token_counting import count_tokens

    return count_tokens(text, model=model, use_tiktoken=True)


def get_token_counter() -> Any:
    """Return a Rust ``TokenCounter`` when available, else ``None``."""
    if _rust_available:
        return _rust_module.TokenCounter()
    return None


# ---------------------------------------------------------------------------
# Security: PathValidator
# ---------------------------------------------------------------------------


def get_path_validator(workspace: str = ".") -> Any:
    """Return a Rust ``PathValidator`` when available, else ``None``."""
    if _rust_available:
        return _rust_module.PathValidator(workspace)
    return None


# ---------------------------------------------------------------------------
# Filesystem: LocalFilesystem
# ---------------------------------------------------------------------------


def get_local_filesystem(workspace: str) -> Any:
    """Return a Rust ``LocalFilesystem`` when available, else ``None``."""
    if _rust_available:
        return _rust_module.LocalFilesystem(workspace)
    return None


# ---------------------------------------------------------------------------
# Workspace: resolve_workspace
# ---------------------------------------------------------------------------


def resolve_workspace_rust(
    explicit: str | None = None,
    thread_workspace: str | None = None,
    installation_default: str | None = None,
) -> Any:
    """Resolve workspace for stream (Rust when available, else ``None``)."""
    if _rust_available:
        return _rust_module.resolve_workspace(explicit, thread_workspace, installation_default)
    return None


# ---------------------------------------------------------------------------
# Config: expand_env_vars
# ---------------------------------------------------------------------------


def expand_env_vars_rust(s: str) -> str:
    """Expand ``$VAR``/``${VAR}`` in a string (Rust when available)."""
    if _rust_available:
        return _rust_module.expand_env_vars(s)
    # Python fallback
    import os

    return os.path.expandvars(s)


# ---------------------------------------------------------------------------
# Persist: SqliteStoreRuntime
# ---------------------------------------------------------------------------


def get_sqlite_store_runtime(path: str) -> Any:
    """Return a Rust ``SqliteStoreRuntime`` when available, else ``None``."""
    if _rust_available:
        return _rust_module.SqliteStoreRuntime.open(path)
    return None


# ---------------------------------------------------------------------------
# Skills: SkillDiscovery, SkillBudget
# ---------------------------------------------------------------------------


def get_skill_discovery(roots: list[str]) -> Any:
    """Return a Rust ``SkillDiscovery`` when available, else ``None``."""
    if _rust_available:
        return _rust_module.SkillDiscovery(roots)
    return None


def get_skill_budget(initial: int) -> Any:
    """Return a Rust ``SkillBudget`` when available, else ``None``."""
    if _rust_available:
        return _rust_module.SkillBudget(initial)
    return None


# ---------------------------------------------------------------------------
# Prompts: build_context_xml
# ---------------------------------------------------------------------------


def build_context_xml_rust(workspace: str, files: list[tuple[str, int, int]]) -> str:
    """Build context XML from file list (Rust when available)."""
    if _rust_available:
        return _rust_module.build_context_xml(workspace, files)
    return ""


# ---------------------------------------------------------------------------
# Events: custom_event
# ---------------------------------------------------------------------------


def custom_event_rust(data: dict[str, Any]) -> Any:
    """Build a soothe protocol custom event chunk (Rust when available)."""
    if _rust_available:
        return _rust_module.custom_event(json.dumps(data))
    # Python fallback
    return ((), "custom", data)
