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
- ``format_cli_error`` — exception type+msg formatting with 500-char truncation
- ``log_preview`` — single-line text preview with ellipsis truncation
- ``convert_and_abbreviate_path`` — home/base-dir path abbreviation

**Partial-parity (permanent gaps):**
- ``custom_event`` — returns the tuple, but the event catalog (Pydantic models,
  ``soothe_nano`` registry) stays Python-only
- ``load_project_instructions`` — Rust does file discovery, Python does
  headline extraction, paragraph boundaries, and progressive disclosure
- ``format_skills_within_budget`` — Rust does the budgeted listing; Python
  fallback retained for when the extension is unavailable
- ``prompt_clock`` (6 date/time formatters) — Rust does all formatting via
  chrono; no Python fallback. ``now_local()`` stays Python-only (it
  returns a ``datetime`` object)
- ``compact`` / ``direct_substring_index`` / ``compact_substring_index`` /
  ``compact_index_to_corpus_index`` / ``match_variants_for_token`` /
  ``earliest_corpus_match`` — Rust does pure string matching for skill
  name/tag prefetch; no Python fallback
- ``dangerous_command_rule_id`` / ``rule_family`` — Rust banned-command
  regex matching and rule-family lookup; no Python fallback

**Security fast paths (reject-only short-circuits):**
- ``rust_path_validator_new`` / ``rust_path_validator_validate`` — Rust
  ``PathValidator`` does basic traversal/absolute/null-byte checks; used as a
  pre-check that short-circuits the richer Python validator on the common
  reject case. The valid branch is NOT authoritative (Python still runs).
- ``rust_rate_limiter_new`` / ``rust_rate_limiter_try_consume`` — Rust
  token-bucket ``RateLimiter``; drop-in for per-key rate-limiting gates.
- ``rust_circuit_breaker_new`` / ``rust_circuit_breaker_is_open`` /
  ``rust_circuit_breaker_state`` — Rust ``CircuitBreaker`` state machine;
  used as a reject-only pre-check: when Rust says OPEN, Python short-circuits.
  The CLOSED/HALF_OPEN branch is NOT authoritative (Python still runs).
- ``dangerous_command_rule_id_rust`` — Rust banned-command regex matching
  (first-match-wins over ~20 compiled patterns); no Python fallback.
- ``rule_family_rust`` — Rust rule-family lookup (rm/dd families);
  no Python fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
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


def format_cli_error_rust(error_type: str, error_msg: str) -> str:
    """Format an exception for CLI display (Rust-backed, no fallback).

    Mirrors ``format_cli_error(error)`` — callers pass ``type(e).__name__``
    and ``str(e)`` separately.
    """
    return _rust_module.format_cli_error(error_type, error_msg)


def log_preview_rust(text: str, max_length: int) -> str:
    """Create a truncated preview of text for logging (Rust-backed, no fallback)."""
    return _rust_module.log_preview(text, max_length)


def convert_and_abbreviate_path_rust(path: str, base_dir: str | None = None) -> str:
    """Convert and abbreviate a path for display (Rust-backed, no fallback)."""
    return _rust_module.convert_and_abbreviate_path(path, base_dir)


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


# --- prompt_clock (date/time formatting) ------------------------------------
#
# The Rust ``prompt_clock`` module implements all 7 formatters. ``now_local()``
# stays Python-only (returns a ``datetime`` object); the 6 string formatters
# are full-parity Rust-backed with no Python fallback.


def now_local_iso_rust(tz: str | None = None) -> str:
    """Current local time as ISO-8601 string (Rust-backed, no fallback).

    Python ``now_local()`` returns a ``datetime`` and is NOT delegated; this
    helper exists so the other 6 formatters can share the Rust code path.
    """
    return _rust_module.prompt_clock_now_local(tz)


def local_date_str_rust(timestamp: float | None = None, tz: str | None = None) -> str:
    """Local date YYYY-MM-DD for *timestamp* (Rust-backed, no fallback).

    When *timestamp* is None the current time is used.
    """
    ts = float(timestamp) if timestamp is not None else _current_timestamp()
    return _rust_module.prompt_clock_local_date_str(ts, tz)


def local_time_str_rust(timestamp: float | None = None, tz: str | None = None) -> str:
    """Local time HH:MM:SS for *timestamp* (Rust-backed, no fallback)."""
    ts = float(timestamp) if timestamp is not None else _current_timestamp()
    return _rust_module.prompt_clock_local_time_str(ts, tz)


def local_timestamp_iso_rust(timestamp: float | None = None, tz: str | None = None) -> str:
    """ISO-8601 timestamp for *timestamp* (Rust-backed, no fallback)."""
    ts = float(timestamp) if timestamp is not None else _current_timestamp()
    return _rust_module.prompt_clock_local_timestamp_iso(ts, tz)


def local_timezone_label_rust(tz: str | None = None) -> str:
    """IANA timezone name or fallback label (Rust-backed, no fallback)."""
    return _rust_module.prompt_clock_local_timezone_label(tz)


def prompt_datetime_context_rust(tz: str | None = None) -> dict[str, str]:
    """Date/time fields for prompt templates (Rust-backed, no fallback).

    Rust returns a JSON string; this wrapper parses it into a dict.
    """
    raw = _rust_module.prompt_clock_prompt_datetime_context(tz)
    return json.loads(raw)


def format_friendly_local_date_rust(timestamp: float | None = None, tz: str | None = None) -> str:
    """User-facing local date (e.g. ``October 14, 2026``) (Rust-backed, no fallback)."""
    ts = float(timestamp) if timestamp is not None else _current_timestamp()
    return _rust_module.prompt_clock_format_friendly_local_date(ts, tz)


def _current_timestamp() -> float:
    """Current Unix timestamp (seconds, f64)."""
    from datetime import UTC, datetime

    return datetime.now(UTC).timestamp()


# ---------------------------------------------------------------------------
# Project instructions (partial-parity — Python fallback retained)
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


# ---------------------------------------------------------------------------
# Skills budget formatting (partial-parity — Python fallback retained)
# ---------------------------------------------------------------------------


def format_skills_within_budget_rust(
    entries: list[tuple[str, str, str, str]],
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, dict[str, Any]] | None:
    """Format a skill listing within a character budget (Rust-backed).

    Returns ``(formatted_text, telemetry_dict)`` or ``None`` if the Rust
    extension is unavailable. Telemetry dict has: included_count,
    truncated_count, mode, budget_chars, actual_chars.

    Each entry tuple is ``(name, description, when_to_use, source)`` where
    ``source`` is ``"builtin"`` or any other string.
    """
    if _rust_available:
        return _rust_module.format_skills_within_budget(
            entries, budget_chars, per_entry_cap_chars, min_per_entry_chars
        )
    return None


# ---------------------------------------------------------------------------
# Corpus string matching (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def compact_rust(text: str) -> str:
    """Collapse whitespace, hyphens, underscores; lowercase (Rust-backed, no fallback)."""
    return _rust_module.compact(text)


def direct_substring_index_rust(corpus: str, variant: str) -> int | None:
    """Find ``variant`` in ``corpus`` with word-boundary enforcement for short tokens.

    Returns the character index or ``None`` if no match is found.
    """
    return _rust_module.direct_substring_index(corpus, variant)


def compact_substring_index_rust(corpus: str, token: str) -> int | None:
    """Match ``token`` against ``corpus`` after compacting both sides.

    Returns the original-corpus character index or ``None`` if no match is found.
    """
    return _rust_module.compact_substring_index(corpus, token)


def compact_index_to_corpus_index_rust(corpus: str, compact_index: int) -> int:
    """Map an index in ``compact(corpus)`` back to an index in ``corpus`` (Rust-backed, no fallback)."""
    return _rust_module.compact_index_to_corpus_index(corpus, compact_index)


def match_variants_for_token_rust(token: str, skill_name: str | None = None) -> tuple[str, ...]:
    """Return lowercase variants for matching a skill name or tag (Rust-backed, no fallback)."""
    return tuple(_rust_module.match_variants_for_token(token, skill_name))


def earliest_corpus_match_rust(
    corpus: str, token: str, skill_name: str | None = None
) -> int | None:
    """Return the earliest start index where ``token`` matches ``corpus`` (Rust-backed, no fallback)."""
    return _rust_module.earliest_corpus_match(corpus, token, skill_name)


# ---------------------------------------------------------------------------
# Security fast paths (PathValidator + RateLimiter)
# ---------------------------------------------------------------------------
#
# The Rust ``PathValidator`` does basic traversal / absolute / null-byte
# checks (compiled regex, zero per-call compile cost). The Python
# ``PathValidator`` in ``security/path_security.py`` is much richer
# (suspicious patterns, symlink detection, severity levels). These wrappers
# expose the Rust validator as a *fast pre-check*: if Rust says invalid, the
# Python side short-circuits before compiling/matching its own regexes.
#
# The Rust ``RateLimiter`` is a token bucket (``try_consume(key) -> bool``)
# and is a drop-in for any per-key rate-limiting need.

# Maps the Rust ``ViolationType`` string to the Python ``ValidationResult``
# fields. Keys are the strings emitted by ``PyValidationResult.violation``.
_RUST_VIOLATION_MAP: dict[str, dict[str, Any]] = {
    "path_traversal": {
        "violation_type": "path_traversal_rust",
        "message": "Path traversal pattern detected (Rust fast-path)",
        "severity": "CRITICAL",
    },
    "absolute_path": {
        "violation_type": "absolute_path_blocked",
        "message": "Absolute paths not allowed (Rust fast-path)",
        "severity": "HIGH",
    },
    "null_byte": {
        "violation_type": "suspicious_null_byte",
        "message": "Suspicious pattern detected: null_byte (Rust fast-path)",
        "severity": "CRITICAL",
    },
}


def rust_path_validator_new(workspace: Path | str) -> Any:
    """Construct a Rust-backed ``PathValidator`` bound to *workspace*.

    Returns the raw PyO3 ``PathValidator`` instance, or ``None`` if the
    Rust extension is unavailable. The instance is stateless beyond the
    workspace root and safe to cache on the Python ``PathValidator``.
    """
    if not _rust_available:
        return None
    return _rust_module.PathValidator(str(workspace))


def rust_path_validator_validate(path: str) -> tuple[bool, str, str] | None:
    """Run the Rust path validator fast pre-check on *path*.

    Returns ``(is_valid, violation_type, message)`` where ``violation_type``
    and ``message`` are the Python-side strings to surface when the Rust
    check rejects the path. Returns ``None`` when the Rust extension is
    unavailable (caller falls back to the full Python validation).

    Only the *reject* branch is authoritative for short-circuiting: when
    Rust reports the path as valid, the caller MUST still run the full
    Python validation (the Rust check is deliberately minimal — it does
    not cover suspicious patterns, symlinks, blocked paths, etc.).
    """
    if not _rust_available:
        return None
    # Use a process-rooted validator; the Rust check only inspects the raw
    # path string for traversal/absolute/null-byte, so the workspace root
    # only affects the (unused) normalized_path field on the valid branch.
    validator = _rust_module.PathValidator(".")
    result = validator.validate(path)
    if result.is_valid:
        return True, "none", ""
    mapping = _RUST_VIOLATION_MAP.get(
        result.violation,
        {
            "violation_type": f"rust_{result.violation}",
            "message": result.message or "Rust validation failed",
            "severity": "HIGH",
        },
    )
    return False, mapping["violation_type"], mapping["message"]


def rust_rate_limiter_new(capacity: int = 60, refill_per_minute: int = 60) -> Any:
    """Construct a Rust-backed token-bucket ``RateLimiter``.

    Returns the raw PyO3 ``RateLimiter`` instance, or ``None`` if the Rust
    extension is unavailable. ``capacity`` is the bucket size;
    ``refill_per_minute`` is the steady-state refill rate.
    """
    if not _rust_available:
        return None
    return _rust_module.RateLimiter(int(capacity), int(refill_per_minute))


def rust_rate_limiter_try_consume(
    key: str,
    limiter: Any = None,
) -> bool | None:
    """Try to consume one token for *key* from a Rust limiter.

    Returns ``True``/``False`` when the Rust extension is available, or
    ``None`` when it is not (caller falls back to its Python limiter).

    If *limiter* is a Rust ``RateLimiter`` instance (from
    :func:`rust_rate_limiter_new`), consume from it. Otherwise fall back to a
    lazily-created process-wide limiter with default capacity so callers that
    only need a boolean gate can delegate without managing their own instance.
    """
    if not _rust_available:
        return None
    if limiter is not None:
        return limiter.try_consume(key)
    global _process_rate_limiter
    if _process_rate_limiter is None:
        _process_rate_limiter = _rust_module.RateLimiter(60, 60)
    return _process_rate_limiter.try_consume(key)


_process_rate_limiter: Any = None


# ---------------------------------------------------------------------------
# Circuit breaker (fast-path state checks — Python fallback retained)
# ---------------------------------------------------------------------------
#
# The Rust ``CircuitBreaker`` is a lightweight failure-counter state machine
# (CLOSED/OPEN/HALF_OPEN). Python delegates ``is_open()`` / ``state()`` checks
# to it as a reject-only fast-path: when Rust says OPEN, Python short-circuits
# immediately. When Rust says CLOSED or HALF_OPEN, Python continues with its
# own richer state machine (success-threshold recovery, logging, decorators).
# The Rust instance is NOT authoritative for the valid branch.


def rust_circuit_breaker_new(
    failure_threshold: int = 5,
    success_threshold: int = 3,
    timeout_seconds: float = 60.0,
) -> Any:
    """Construct a Rust-backed ``CircuitBreaker`` for fast-path state checks.

    Args:
        failure_threshold: Failures before the circuit opens.
        success_threshold: Accepted but unused by the Rust state machine
            (recovery is time-based, not success-counted); kept for API
            symmetry with the Python constructor.
        timeout_seconds: Seconds before OPEN transitions to HALF_OPEN.

    Returns the raw PyO3 ``CircuitBreaker`` instance, or ``None`` if the Rust
    extension is unavailable.
    """
    if not _rust_available:
        return None
    return _rust_module.CircuitBreaker(int(failure_threshold), float(timeout_seconds))


def rust_circuit_breaker_is_open(breaker: Any) -> bool | None:
    """Check whether a Rust ``CircuitBreaker`` is open.

    Returns ``True``/``False`` when the Rust extension is available and
    *breaker* is a Rust ``CircuitBreaker`` instance, or ``None`` when the
    extension is unavailable (caller falls back to its Python state machine).
    """
    if not _rust_available or breaker is None:
        return None
    return breaker.is_open()


def rust_circuit_breaker_state(breaker: Any) -> str | None:
    """Return the state of a Rust ``CircuitBreaker`` as a lowercase string.

    Returns ``"closed"`` / ``"open"`` / ``"half_open"`` when the Rust extension
    is available and *breaker* is a Rust ``CircuitBreaker`` instance, or
    ``None`` when the extension is unavailable (caller falls back to its
    Python state machine).
    """
    if not _rust_available or breaker is None:
        return None
    return breaker.state()


# ---------------------------------------------------------------------------
# Banned-command matching (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def dangerous_command_rule_id_rust(command: str) -> str | None:
    """Return the rule_id of the first banned pattern ``command`` matches (Rust-backed, no fallback)."""
    return _rust_module.dangerous_command_rule_id(command)


def rule_family_rust(rule_id: str) -> frozenset[str]:
    """Return all rule ids in the same family as *rule_id* (inclusive, Rust-backed, no fallback)."""
    return frozenset(_rust_module.rule_family(rule_id))


# ---------------------------------------------------------------------------
# Rust class constructors (fast-path delegation targets)
# ---------------------------------------------------------------------------
#
# These wrappers construct the five Rust PyO3 classes that serve as
# fast-path delegation targets for Python modules. Each returns the raw
# PyO3 instance, or ``None`` when the extension is unavailable so callers
# can fall back to the pure-Python implementation.


def rust_corpus_matcher_new(embeddings: list[float], dims: int) -> Any:
    """Construct a Rust-backed ``CorpusMatcher`` from a flattened embedding matrix.

    Args:
        embeddings: Flattened embedding matrix (n_skills × dims).
        dims: Embedding dimensionality.

    Returns the raw PyO3 ``CorpusMatcher`` instance, or ``None`` if the Rust
    extension is unavailable.
    """
    if not _rust_available:
        return None
    return _rust_module.corpus_matcher_new(embeddings, dims)


def rust_skill_discovery_new(workspace: Path | str | list[str]) -> Any:
    """Construct a Rust-backed ``SkillDiscovery`` for filesystem scanning.

    Args:
        workspace: A single root path or a list of root directories to scan
            for ``.md`` skill files.

    Returns the raw PyO3 ``SkillDiscovery`` instance, or ``None`` if the Rust
    extension is unavailable.
    """
    if not _rust_available:
        return None
    if isinstance(workspace, (list, tuple)):
        roots = [str(p) for p in workspace]
    else:
        roots = [str(workspace)]
    return _rust_module.skill_discovery_new(roots)


def rust_sqlite_store_new(db_path: Path | str) -> Any:
    """Construct a Rust-backed ``SqliteStoreRuntime`` for simple KV operations.

    Args:
        db_path: Path to the SQLite database file.

    Returns the raw PyO3 ``SqliteStoreRuntime`` instance, or ``None`` if the
    Rust extension is unavailable or the database cannot be opened.
    """
    if not _rust_available:
        return None
    try:
        return _rust_module.SqliteStoreRuntime(str(db_path))
    except Exception:
        return None


def rust_local_filesystem_new(root: Path | str) -> Any:
    """Construct a Rust-backed ``LocalFilesystem`` for read/glob/grep fast paths.

    Args:
        root: Workspace root directory.

    Returns the raw PyO3 ``LocalFilesystem`` instance, or ``None`` if the Rust
    extension is unavailable.
    """
    if not _rust_available:
        return None
    return _rust_module.LocalFilesystem(str(root))


def rust_workspace_policy_new(policy: Path | str | None = None) -> Any:
    """Construct a Rust-backed ``WorkspacePolicy`` for path containment checks.

    Args:
        policy: Workspace root path. Defaults to the current working directory.

    Returns the raw PyO3 ``WorkspacePolicy`` instance, or ``None`` if the Rust
    extension is unavailable.
    """
    if not _rust_available:
        return None
    root = str(policy) if policy is not None else "."
    return _rust_module.workspace_policy_new(root)
