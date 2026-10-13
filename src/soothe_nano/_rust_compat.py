"""Conditional import layer for Rust-backed implementations.

Exposes the compiled PyO3 extension (``soothe_nano._rust``) to Python modules.

**Full-parity functions (no Python fallback):**
- ``generate_thread_id`` — UUID v4 generation
- ``expand_env_vars`` — ``$VAR``/``${VAR}`` expansion
- ``truncate_output`` — byte-safe truncation
- ``repair_json`` — JSON repair/extraction with dict-only contract
- ``count_tokens`` — tiktoken-rs with model-aware encoding + estimation mode
- ``text_preview`` / ``preview_full`` — 3-mode truncation with markers
- ``validate_url`` — URL validation with query/fragment preservation
- ``resolve_workspace`` — workspace resolution with expanduser + canonicalize
- ``build_context_xml`` — file-list context XML (pure Rust)
- ``build_environment_section`` — ENVIRONMENT XML (Rust assembly + PyO3 round-trip
  for ``is_rg_available()`` and ``get_knowledge_cutoff()``)
- ``build_workspace_section`` — WORKSPACE XML (pure Rust filesystem I/O)

**Partial-parity (permanent gaps):**
- ``custom_event`` — returns the tuple, but the event catalog (Pydantic models,
  ``soothe_nano`` registry) stays Python-only
- ``load_project_instructions`` — Rust does file discovery, Python does
  headline extraction, paragraph boundaries, and progressive disclosure
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
# Full-parity functions (no Python fallback)
# ---------------------------------------------------------------------------


def generate_thread_id() -> str:
    """Generate a UUID v4 thread ID (Rust-backed, no fallback)."""
    return _rust_module.generate_thread_id()


def repair_json(raw: str) -> Any:
    """Repair/extract JSON from LLM output (Rust-backed, no fallback).

    Enforces dict-only contract: returns ``None`` for non-dict or unparseable
    results.
    """
    return _rust_module.repair_json(raw)


def text_preview_rust(text: str, max_chars: int) -> str:
    """Single-line text preview truncated to *max_chars* (Rust-backed, no fallback)."""
    return _rust_module.text_preview(text, max_chars)


def preview_full_rust(
    text: str,
    mode: str = "chars",
    first: int | None = None,
    last: int | None = None,
    marker: str | None = None,
) -> str:
    """Full preview() API with 3 modes, head+tail, custom markers (Rust-backed, no fallback)."""
    return _rust_module.preview_full(text, mode, first, last, marker)


def validate_url_rust(url: str) -> tuple[str, str | None]:
    """Validate and sanitize URL (Rust-backed, no fallback).

    Returns ``(sanitized_url, error_message_or_None)``.
    """
    return _rust_module.validate_url_py(url)


def truncate_output_rust(output: str, max_bytes: int) -> str:
    """Truncate output to max bytes (Rust-backed, no fallback)."""
    return _rust_module.truncate_output(output, max_bytes)


def count_tokens_rust(text: str, model: str | None = None, use_tiktoken: bool = True) -> int:
    """Count tokens via tiktoken-rs with model-aware encoding (Rust-backed, no fallback).

    When ``use_tiktoken=False``, returns ``len(text) // 4`` estimation.
    """
    return _rust_module.count_tokens(text, model, use_tiktoken)


def resolve_workspace_rust(
    explicit: str | None = None,
    thread_workspace: str | None = None,
    installation_default: str | None = None,
) -> Any:
    """Resolve workspace for stream (Rust-backed, no fallback).

    Performs ``expanduser()`` + ``canonicalize()`` (symlink resolution).
    """
    return _rust_module.resolve_workspace(explicit, thread_workspace, installation_default)


def expand_env_vars_rust(s: str) -> str:
    """Expand ``$VAR``/``${VAR}`` in a string (Rust-backed, no fallback)."""
    return _rust_module.expand_env_vars(s)


# ---------------------------------------------------------------------------
# Full-parity functions (no Python fallback) — prompts
# ---------------------------------------------------------------------------


def build_context_xml_rust(workspace: str, files: list[tuple[str, int, int]]) -> str:
    """Build file-list context XML (Rust-backed, no fallback)."""
    return _rust_module.build_context_xml(workspace, files)


def build_environment_section_rust(model: str) -> str:
    """Build ENVIRONMENT XML block (Rust-backed, no fallback).

    Round-trips into Python for ``is_rg_available()`` and
    ``get_knowledge_cutoff(model)``; all XML assembly and platform
    introspection is done in Rust.
    """
    return _rust_module.build_environment_section(model)


def build_workspace_section_rust(
    workspace_path: str | None,
    *,
    include_layout_preview: bool = False,
    max_layout_entries: int = 40,
    include_readme_excerpt: bool = False,
    readme_max_chars: int = 500,
) -> str:
    """Build WORKSPACE XML block (Rust-backed, no fallback)."""
    return _rust_module.build_workspace_section(
        workspace_path,
        include_layout_preview,
        max_layout_entries,
        include_readme_excerpt,
        readme_max_chars,
    )


# ---------------------------------------------------------------------------
# Partial-parity functions (permanent gaps — Python fallback retained)
# ---------------------------------------------------------------------------


def load_project_instructions_rust(workspace: str) -> str | None:
    """Load project instructions via Rust file discovery (or None if unavailable).

    Used as a fast-path for file existence checking. The Python path handles
    headline extraction, paragraph boundaries, and progressive disclosure.
    """
    if _rust_available:
        return _rust_module.load_project_instructions(workspace)
    return None


def custom_event_rust(data: dict[str, Any]) -> Any:
    """Build a custom event chunk via Rust (returns tuple or None if unavailable)."""
    if _rust_available:
        return _rust_module.custom_event(json.dumps(data))
    return None
