"""Rust-backed implementation layer for soothe-nano.

Exposes the compiled PyO3 extension (``soothe_nano._rust``) to Python modules.
The extension is compiled and shipped with the package; all functions delegate
directly to Rust with no Python fallback.

**Utility functions:**
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
- ``task_namespace`` (9 functions) — unified ``tool_call_id`` parsing
- ``short_level_letter`` / ``abbreviate_logger_name`` — logging formatter helpers
- ``count_str_chars`` / ``coerce_total_tokens_used`` — token counting helpers
- ``format_event_compact`` — compact progress-event formatting
- Error simplification (``is_unexpected_keyword_error``, ``unexpected_kwarg_name``,
  ``missing_required_count``, ``is_llm_argument_error``, ``is_warning_level_error``,
  ``simplify_error``)
- Chrome/Electron process detection (``exe_name_is_chrome_like``,
  ``extract_exe_path_from_args``, ``is_chrome_like_process``,
  ``extract_user_data_dir``, ``extract_debug_port``, ``parse_singleton_owner_pid``)

**Prompt clock (6 date/time formatters):**
Rust does all formatting via chrono. ``now_local()`` stays Python-only (returns
a ``datetime`` object).

**Events / wire protocol:**
- ``custom_event`` — returns the tuple; the event catalog (Pydantic models,
  registry) stays Python-only
- ``is_curated_subagent_wire_event_type`` / ``parse_subagent_wire_agent`` —
  wire event type validation and agent-segment extraction
- ``truncate_wire_str`` / ``clip_wire_event_payload`` — wire-safe string truncation

**Skills:**
- ``format_skills_within_budget`` — budgeted skill listing
- ``compact`` / ``direct_substring_index`` / ``compact_substring_index`` /
  ``compact_index_to_corpus_index`` / ``match_variants_for_token`` /
  ``earliest_corpus_match`` — skill name/tag string matching
- ``rust_corpus_matcher_new`` / ``rust_skill_discovery_new`` — Rust class constructors

**Security:**
- ``rust_path_validator_new`` / ``rust_path_validator_validate`` — Rust
  ``PathValidator`` for basic traversal/absolute/null-byte checks (pre-check)
- ``rust_rate_limiter_new`` / ``rust_rate_limiter_try_consume`` — Rust
  token-bucket ``RateLimiter``
- ``rust_circuit_breaker_new`` / ``rust_circuit_breaker_is_open`` /
  ``rust_circuit_breaker_state`` — Rust ``CircuitBreaker`` state machine
- ``dangerous_command_rule_id`` / ``rule_family`` — banned-command regex matching
- ``rust_path_is_under`` / ``rust_path_policy_is_denied`` /
  ``rust_path_policy_should_log`` / ``rust_path_policy_merge`` — policy-models logic
- ``rust_find_dangerous_path_component`` / ``rust_matches_sensitive_system_path`` —
  path security checks
- ``rust_kill_invocation_pids`` / ``rust_pids_from_kill_args`` — kill PID extraction
- ``rust_command_approved_by_allowlist`` / ``rust_glob_match`` — command approval
- ``rust_sliding_window_rate_limiter_new`` — sliding-window rate limiter

**Core domain models:**
- ``should_show`` / ``classify_domain`` / ``domain_default_tier`` /
  ``get_verbosity_for_type`` / ``split_domain`` / ``parse_verbosity_alias`` /
  ``event_priority_value`` — verbosity tier and event priority logic.
  Pydantic models and ``EventRegistry`` stay Python-only.

**Diagnose health-check models:**
- ``check_status_str`` / ``check_status_severity`` / ``aggregate_status`` /
  ``compare_status`` / ``check_result_to_dict`` / ``category_result_to_dict``
  and category-specific builders.

**Protocol pure-logic delegation:**
- ``planner_outcome_text_preview`` / ``step_result_to_evidence_string`` /
  ``permission_matches`` / ``is_valid_*`` predicates / ``strip_legacy_claude_sessions``
  / ``vector_record_new`` / ``aksk_pair_status`` / ``token_claims_is_expired`` /
  ``token_info_status`` — protocol data-model pure logic. Pydantic models stay
  in Python for ``model_dump`` / ``model_validate`` compatibility.

**Subagent helpers (Phase 4):**
- Topic attachment stripping, search-query compaction, effort parsing, report
  summaries, reference formatting, loop termination, scenario fallback
  classification. Python modules retain Pydantic models, async LLM calls, and
  config attribute access.

**Persistence / observability / logging (Phase 5):**
- ``split_sql_statements`` / ``is_duplicate_schema_error`` /
  ``is_recoverable_connection_error`` / ``advisory_lock_key`` /
  ``postgres_admin_dsn`` / ``postgres_target_dsn`` / ``is_valid_db_name`` /
  ``parse_migration_filename`` / ``backoff_delay`` — SQL/persistence helpers
- ``cosine_similarity`` / ``l2_distance`` / ``ip_similarity`` /
  ``pack_vector_f32`` — vector math
- ``loop_graph_langfuse_run_display_name`` /
  ``execute_step_langfuse_run_display_name`` — Langfuse display names
- ``resolve_str`` / ``resolve_env_vars`` / ``normalize_tags`` — config resolution
- ``short_thread_id_for_log`` — compact log tags
- ``strip_thinking_rust`` / ``rust_thinking_stream_filter_new`` — thinking-token
  filter (regex-based stripping + stateful stream filter)
- ``strip_json_text_rust`` / ``parse_json_object_rust`` — LLM response text
  JSON extraction (fence stripping, brace-depth matching)
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


# ---------------------------------------------------------------------------
# Workspace path helpers (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def should_use_virtual_path_resolution_rust(file_path: str, workspace_root: str) -> bool:
    """True when a leading-`/` path should use virtual sandbox resolution."""
    return _rust_module.should_use_virtual_path_resolution_py(file_path, workspace_root)


def join_workspace_normalized_path_rust(workspace: str, normalized: str) -> str:
    """Join a workspace root with a relative/absolute path (Rust-backed, no fallback).

    Returns the canonical absolute path. Raises ``RuntimeError`` on path-escape.
    """
    return _rust_module.join_workspace_normalized_path_py(workspace, normalized)


def soothe_home_rust() -> str:
    """Resolve ``SOOTHE_HOME`` directory (env var > ``~/.soothe``)."""
    return _rust_module.soothe_home_py()


def soothe_data_dir_rust() -> str:
    """Resolve ``$SOOTHE_DATA_DIR`` (env var > ``$SOOTHE_HOME/data``)."""
    return _rust_module.soothe_data_dir_py()


def resolve_databases_dir_rust() -> str:
    """Return ``$SOOTHE_DATA_DIR/databases`` (creates nothing)."""
    return _rust_module.resolve_databases_dir_py()


def resolve_sqlite_db_path_rust(purpose: str) -> str:
    """Return ``$SOOTHE_DATA_DIR/databases/{purpose}.db``."""
    return _rust_module.resolve_sqlite_db_path_py(purpose)


def resolve_checkpoints_db_path_rust() -> str:
    """StrangeLoop / loop checkpoints SQLite path."""
    return _rust_module.resolve_checkpoints_db_path_py()


def resolve_context_db_path_rust() -> str:
    """Context Engine SQLite path."""
    return _rust_module.resolve_context_db_path_py()


def resolve_display_db_path_rust() -> str:
    """Display card ledger SQLite path."""
    return _rust_module.resolve_display_db_path_py()


def resolve_cron_db_path_rust() -> str:
    """Cron job store SQLite path."""
    return _rust_module.resolve_cron_db_path_py()


def resolve_identity_db_path_rust() -> str:
    """Identity service SQLite path."""
    return _rust_module.resolve_identity_db_path_py()


def resolve_metadata_db_path_rust() -> str:
    """ThreadInfo / durability metadata SQLite path."""
    return _rust_module.resolve_metadata_db_path_py()


def resolve_persist_db_path_rust() -> str:
    """Persist KV SQLite path."""
    return _rust_module.resolve_persist_db_path_py()


def resolve_vectors_db_path_rust() -> str:
    """Vector store (sqlite-vec) SQLite path."""
    return _rust_module.resolve_vectors_db_path_py()


def workspace_backup_dir_rust() -> str:
    """Product layout under the workspace (``.soothe/backups``)."""
    return _rust_module.workspace_backup_dir_py()


def sqlite_databases_subdir_rust() -> str:
    """SQLite purpose databases subdirectory name (``databases``)."""
    return _rust_module.sqlite_databases_subdir_py()


def expand_env_vars_rust(s: str) -> str:
    """Expand ``$VAR``/``${VAR}`` in a string (Rust-backed, no fallback)."""
    return _rust_module.expand_env_vars(s)


def clamp_execute_timeout_rust(seconds: int) -> int:
    """Clamp run_command timeout to ``MAX_EXECUTE_TIMEOUT`` (Rust-backed, no fallback)."""
    return _rust_module.clamp_execute_timeout(int(seconds))


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
# Logging formatter helpers (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def short_level_letter_rust(levelno: int) -> str:
    """Return one-letter code for a logging level number (Rust-backed, no fallback)."""
    return _rust_module.short_level_letter(levelno)


def abbreviate_logger_name_rust(name: str) -> str:
    """Abbreviate a dotted logger path (Rust-backed, no fallback)."""
    return _rust_module.abbreviate_logger_name(name)


# ---------------------------------------------------------------------------
# Full-parity functions (no Python fallback) — filesystem discovery hints
# ---------------------------------------------------------------------------


def glob_discovery_fallback_hint_rust() -> str:
    """Return the glob discovery fallback hint string (Rust-backed, no fallback)."""
    return _rust_module.get_glob_discovery_fallback_hint()


def grep_discovery_fallback_hint_rust() -> str:
    """Return the grep discovery fallback hint string (Rust-backed, no fallback)."""
    return _rust_module.get_grep_discovery_fallback_hint()


def format_glob_timeout_error_rust(timeout_seconds: float) -> str:
    """Build a glob timeout error with discovery fallback guidance (Rust-backed, no fallback)."""
    return _rust_module.format_glob_timeout_error_py(float(timeout_seconds))


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
    """Load project instructions via Rust file discovery.

    Used as a fast-path for file existence checking. The Python path handles
    headline extraction, paragraph boundaries, and progressive disclosure.
    """
    return _rust_module.load_project_instructions(workspace)


def custom_event_rust(data: dict[str, Any]) -> Any:
    """Build a custom event chunk via Rust (returns tuple or None)."""
    return _rust_module.custom_event(json.dumps(data))


def is_curated_subagent_wire_event_type_rust(event_type: str) -> bool:
    """Check if *event_type* is a valid curated ``soothe.subagent.*`` wire type."""
    return _rust_module.is_curated_subagent_wire_event_type(event_type)


def parse_subagent_wire_agent_rust(event_type: str) -> str | None:
    """Extract the agent segment from a ``soothe.subagent.<agent>.…`` event type."""
    return _rust_module.parse_subagent_wire_agent(event_type)


def truncate_wire_str_rust(value: str, max_len: int) -> str:
    """Truncate *value* to *max_len* chars with an ellipsis suffix."""
    return _rust_module.truncate_wire_str(value, max_len)


def clip_wire_event_payload_rust(data: dict[str, Any]) -> dict[str, Any]:
    """Copy *data* and truncate known string fields for wire safety."""
    return _rust_module.clip_wire_event_payload(data)


# ---------------------------------------------------------------------------
# Skills budget formatting (partial-parity — Python fallback retained)
# ---------------------------------------------------------------------------


def format_skills_within_budget_rust(
    entries: list[tuple[str, str, str, str]],
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, dict[str, Any]]:
    """Format a skill listing within a character budget (Rust-backed).

    Returns ``(formatted_text, telemetry_dict)``. Telemetry dict has:
    included_count, truncated_count, mode, budget_chars, actual_chars.

    Each entry tuple is ``(name, description, when_to_use, source)`` where
    ``source`` is ``"builtin"`` or any other string.
    """
    return _rust_module.format_skills_within_budget(
        entries, budget_chars, per_entry_cap_chars, min_per_entry_chars
    )


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
    "absolute_path_blocked": {
        "violation_type": "absolute_path_blocked",
        "message": "Absolute paths not allowed (Rust fast-path)",
        "severity": "HIGH",
    },
    "suspicious_null_byte": {
        "violation_type": "suspicious_null_byte",
        "message": "Suspicious pattern detected: null_byte (Rust fast-path)",
        "severity": "CRITICAL",
    },
}


def rust_path_validator_new(workspace: Path | str) -> Any:
    """Construct a Rust-backed ``PathValidator`` bound to *workspace*.

    Returns the raw PyO3 ``PathValidator`` instance. The instance is stateless
    beyond the workspace root and safe to cache on the Python ``PathValidator``.
    """
    return _rust_module.PathValidator(str(workspace))


def rust_path_validator_validate(path: str) -> tuple[bool, str, str] | None:
    """Run the Rust path validator fast pre-check on *path*.

    Returns ``(is_valid, violation_type, message)`` where ``violation_type``
    and ``message`` are the Python-side strings to surface when the Rust
    check rejects the path. Returns ``None`` when the Rust extension is
    Only the *reject* branch is authoritative for short-circuiting: when
    Rust reports the path as valid, the caller MUST still run the full
    Python validation (the Rust check is deliberately minimal — it does
    not cover suspicious patterns, symlinks, blocked paths, etc.).

    Only the *reject* branch is authoritative for short-circuiting: when
    Rust reports the path as valid, the caller MUST still run the full
    Python validation (the Rust check is deliberately minimal — it does
    not cover suspicious patterns, symlinks, blocked paths, etc.).
    """
    # Use a process-rooted validator; the Rust check only inspects the raw
    # path string for traversal/absolute/null-byte, so the workspace root
    # only affects the (unused) normalized_path field on the valid branch.
    validator = _rust_module.PathValidator(".")
    result = validator.fast_check(path)
    if result is None:
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

    ``capacity`` is the bucket size; ``refill_per_minute`` is the steady-state
    refill rate.
    """
    return _rust_module.RateLimiter(int(capacity), int(refill_per_minute))


def rust_rate_limiter_try_consume(
    key: str,
    limiter: Any = None,
) -> bool:
    """Try to consume one token for *key* from a Rust limiter.

    If *limiter* is a Rust ``RateLimiter`` instance (from
    :func:`rust_rate_limiter_new`), consume from it. Otherwise fall back to a
    lazily-created process-wide limiter with default capacity so callers that
    only need a boolean gate can delegate without managing their own instance.
    """
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
    """
    return _rust_module.CircuitBreaker(int(failure_threshold), float(timeout_seconds))


def rust_circuit_breaker_is_open(breaker: Any) -> bool:
    """Check whether a Rust ``CircuitBreaker`` is open."""
    if breaker is None:
        return False
    return breaker.is_open()


def rust_circuit_breaker_state(breaker: Any) -> str:
    """Return the state of a Rust ``CircuitBreaker`` as a lowercase string."""
    if breaker is None:
        return "closed"
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
# Policy-models pure logic (full-parity — Python fallback retained)
# ---------------------------------------------------------------------------
#
# The Rust ``policy_models`` crate implements the pure logic for
# ``_path_is_under``, ``PathPolicyDecision.is_denied`` / ``should_log`` /
# ``merge``. Python delegates to these fast-path functions when the extension
# is available and falls back to the pure-Python implementation otherwise.


def rust_path_is_under(path: str, prefix: str) -> bool:
    """Delegate ``_path_is_under`` to the Rust ``path_is_under`` implementation."""
    return _rust_module.path_is_under_rust(path, prefix)


def rust_path_policy_is_denied(allowed: bool, action: str) -> bool:
    """Delegate ``PathPolicyDecision.is_denied`` to Rust."""
    return _rust_module.path_policy_is_denied(allowed, action)


def rust_path_policy_should_log(action: str) -> bool:
    """Delegate ``PathPolicyDecision.should_log`` to Rust."""
    return _rust_module.path_policy_should_log(action)


def rust_path_policy_merge(
    self_allowed: bool,
    self_action: str,
    self_reason: str | None,
    self_sanitized_path: str | None,
    other_allowed: bool,
    other_action: str,
    other_reason: str | None,
    other_sanitized_path: str | None,
) -> tuple[bool, str, str | None, str | None]:
    """Delegate ``PathPolicyDecision.merge`` decision logic to Rust.

    Violations and metadata are combined on the Python side (plain
    concatenation / overlay).
    """
    return _rust_module.path_policy_merge(
        self_allowed,
        self_action,
        self_reason,
        self_sanitized_path,
        other_allowed,
        other_action,
        other_reason,
        other_sanitized_path,
    )


# ---------------------------------------------------------------------------
# Task namespace — unified tool_call_id parsing (full-parity — no fallback)
# ---------------------------------------------------------------------------
#
# The Rust ``task_namespace`` module implements the pure string parsing for the
# unified tool_call_id format ``{step_wire}:{type}:{tool}:{idx}``. All 9
# functions are full-parity with no Python fallback.


def step_id_to_unified_fragment_rust(step_id: str) -> str:
    """Map execute step ids (``GHT-01``) to unified wire fragment (``GHT_01``)."""
    return _rust_module.step_id_to_unified_fragment(step_id)


def step_id_from_unified_fragment_rust(fragment: str) -> str:
    """Map unified wire step fragment back to canonical execute step id."""
    return _rust_module.step_id_from_unified_fragment(fragment)


def is_wire_step_fragment_rust(fragment: str) -> bool:
    """True when the first segment uses underscore wire form (``GHT_01``)."""
    return _rust_module.is_wire_step_fragment(fragment)


def provider_tool_fragment_rust(tid: str) -> str:
    """Parse provider ``tool:idx`` into unified ``tool:idx`` fragment."""
    return _rust_module.provider_tool_fragment(tid)


def tool_info_from_unified_parts_rust(parts: list[str]) -> str:
    """Extract tool_info from colon segments after the type segment."""
    return _rust_module.tool_info_from_unified_parts(parts)


def format_unified_tool_call_id_rust(step_id: str, type_part: str, tool_fragment: str) -> str:
    """Build canonical unified id: ``{step_wire}:{type}:{tool}:{idx}``."""
    return _rust_module.format_unified_tool_call_id(step_id, type_part, tool_fragment)


def parse_unified_tool_call_id_rust(tool_call_id: str) -> Any:
    """Parse unified tool_call_id format into components (Rust-backed, no fallback).

    Returns a ``ParsedUnifiedToolCallId`` PyO3 instance with ``step_id``,
    ``type_code``, ``task_idx``, and ``tool_info`` attributes, plus tuple-style
    positional access (``[0]``..``[3]``) matching the Python ``NamedTuple``.
    """
    return _rust_module.parse_unified_tool_call_id(tool_call_id)


def is_unified_tool_call_id_rust(tool_call_id: str) -> bool:
    """Return True when ``tool_call_id`` matches the canonical unified wire format."""
    return _rust_module.is_unified_tool_call_id(tool_call_id)


def shorten_tool_call_id_rust(raw_tid: str) -> str:
    """Shorten provider tool_call_id to ``tool:idx`` for unified id assembly."""
    return _rust_module.shorten_tool_call_id(raw_tid)


# ---------------------------------------------------------------------------
# Stream tool wire helpers (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def unified_tool_update_allowed_without_args_rust(tool_call_id: str) -> bool:
    """True when a wire update may omit kwargs (unified main or subgraph tool rows)."""
    return _rust_module.unified_tool_update_allowed_without_args_rust(tool_call_id)


def extract_tool_call_updates_from_wire_message_rust(msg: Any) -> list[dict[str, Any]]:
    """Extract ``soothe.stream.tool_call.update`` payloads from a wire AI message dict."""
    return _rust_module.extract_tool_call_updates_from_wire_message_rust(msg)


# ---------------------------------------------------------------------------
# Security pure-logic helpers (full-parity — no Python fallback)
# ---------------------------------------------------------------------------
#
# The Rust ``security`` crate implements the pure logic for path-component
# checks, sensitive-system-path matching, kill-invocation PID extraction,
# command-allowlist approval, glob matching, and the sliding-window rate
# limiter. These are full-parity with no Python fallback.


def rust_find_dangerous_path_component(path: str) -> str | None:
    """Return the first dangerous path component in *path*, or ``None``.

    Mirrors the bypass-immune check in
    ``WorkspaceToolOperationSecurity._check_filesystem``.
    """
    return _rust_module.find_dangerous_path_component(path)


def rust_matches_sensitive_system_path(path: str) -> str | None:
    """Return the first sensitive system path pattern *path* matches, or ``None``.

    Mirrors the ``_SENSITIVE_SYSTEM_PATH_PATTERNS`` check in
    ``WorkspaceToolOperationSecurity._check_filesystem``.
    """
    return _rust_module.matches_sensitive_system_path(path)


def rust_kill_invocation_pids(command: str) -> list[int]:
    """Return all PIDs targeted by ``kill`` invocations in *command*.

    Mirrors the matching loop in ``_protected_kill_in_shell``.
    """
    return _rust_module.kill_invocation_pids(command)


def rust_pids_from_kill_args(args: str) -> list[int]:
    """Parse numeric PIDs from ``kill`` argument text (skip signal tokens).

    Mirrors ``WorkspaceToolOperationSecurity._pids_from_kill_args``.
    """
    return _rust_module.pids_from_kill_args(args)


def rust_command_approved_by_allowlist(
    command: str,
    rule_id: str | None = None,
    allowlist: list[Any] | None = None,
) -> bool:
    """True when *command* is approved by an allowlist entry.

    Mirrors ``command_approved_by_allowlist``.
    """
    # Convert Python allowlist records to the (tool, signature, rule) tuples
    # the Rust function expects. Each record is a Mapping with ``tool``,
    # ``signature``, and ``rule`` keys (any may be missing).
    converted: list[tuple[str, str | None, str | None]] = []
    if allowlist:
        for rec in allowlist:
            if isinstance(rec, dict):
                tool = str(rec.get("tool") or "")
                sig = rec.get("signature")
                rule = rec.get("rule")
                converted.append(
                    (
                        tool,
                        str(sig) if sig is not None else None,
                        str(rule) if rule is not None else None,
                    )
                )
            else:
                # Skip non-dict records.
                continue
    return _rust_module.command_approved_by_allowlist(
        command, rule_id, converted if converted else None
    )


def rust_glob_match(pattern: str, text: str) -> bool:
    """fnmatch-style glob matching (case-sensitive on Unix).

    Mirrors ``WorkspaceToolOperationSecurity._path_matches_pattern``.
    """
    return _rust_module.glob_match(pattern, text)


def rust_sliding_window_rate_limiter_new(window_seconds: int = 60) -> Any:
    """Construct a Rust-backed sliding-window ``SlidingWindowRateLimiter``."""
    return _rust_module.SlidingWindowRateLimiter(int(window_seconds))


# ---------------------------------------------------------------------------
# Rust class constructors (fast-path delegation targets)
# ---------------------------------------------------------------------------
#
# These wrappers construct the five Rust PyO3 classes that serve as
# fast-path delegation targets for Python modules. Each returns the raw
# PyO3 instance.


def rust_corpus_matcher_new(embeddings: list[float], dims: int) -> Any:
    """Construct a Rust-backed ``CorpusMatcher`` from a flattened embedding matrix.

    Args:
        embeddings: Flattened embedding matrix (n_skills × dims).
        dims: Embedding dimensionality.

    Returns the raw PyO3 ``CorpusMatcher`` instance
    """
    return _rust_module.corpus_matcher_new(embeddings, dims)


def rust_skill_discovery_new(workspace: Path | str | list[str]) -> Any:
    """Construct a Rust-backed ``SkillDiscovery`` for filesystem scanning.

    Args:
        workspace: A single root path or a list of root directories to scan
            for ``.md`` skill files.

    Returns the raw PyO3 ``SkillDiscovery`` instance
    """
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
    or the database cannot be opened.
    """
    try:
        return _rust_module.SqliteStoreRuntime(str(db_path))
    except Exception:
        return None


def rust_local_filesystem_new(root: Path | str) -> Any:
    """Construct a Rust-backed ``LocalFilesystem`` for read/glob/grep fast paths.

    Args:
        root: Workspace root directory.

    Returns the raw PyO3 ``LocalFilesystem`` instance
    """
    return _rust_module.LocalFilesystem(str(root))


def rust_workspace_policy_new(policy: Path | str | None = None) -> Any:
    """Construct a Rust-backed ``WorkspacePolicy`` for path containment checks.

    Args:
        policy: Workspace root path. Defaults to the current working directory.

    Returns the raw PyO3 ``WorkspacePolicy`` instance
    """
    root = str(policy) if policy is not None else "."
    return _rust_module.workspace_policy_new(root)


# ---------------------------------------------------------------------------
# Content character counting + token coercion (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def coerce_total_tokens_used_rust(value: Any) -> int:
    """Coerce a value into a non-negative token count (Rust-backed, no fallback).

    Mirrors ``max(0, int(value or 0))``: ``None``, non-numeric, and negative
    values yield ``0``; positive integers pass through.
    """
    try:
        return _rust_module.coerce_total_tokens_used_rust(int(value) if value is not None else None)
    except (TypeError, ValueError):
        return 0


def count_str_chars_rust(s: str) -> int:
    """Count Unicode characters in a string (Rust-backed, no fallback)."""
    return _rust_module.count_str_chars_rust(s)


# ---------------------------------------------------------------------------
# Error simplification (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def is_unexpected_keyword_error_rust(error_msg: str) -> bool:
    """Return True for TypeError about an unexpected keyword argument."""
    return _rust_module.is_unexpected_keyword_error_rust(error_msg)


def unexpected_kwarg_name_rust(error_msg: str) -> str | None:
    """Extract the unexpected keyword name from a TypeError message."""
    return _rust_module.unexpected_kwarg_name_rust(error_msg)


def missing_required_count_rust(error_msg: str) -> str | None:
    """Extract the count from a 'missing N required positional argument' message."""
    return _rust_module.missing_required_count_rust(error_msg)


def is_llm_argument_error_rust(error_type: str, error_msg: str) -> bool:
    """Return True for recoverable LLM tool-argument TypeErrors."""
    return _rust_module.is_llm_argument_error_rust(error_type, error_msg)


def is_warning_level_error_rust(error_type: str, error_msg: str, status: int | None = None) -> bool:
    """Check if error should be logged as warning (non-critical/recoverable)."""
    return _rust_module.is_warning_level_error_rust(error_type, error_msg, status)


def simplify_error_rust(error_type: str, error_msg: str, status: int | None = None) -> str:
    """Convert an error into a user-friendly message (Rust-backed, no fallback)."""
    return _rust_module.simplify_error_rust(error_type, error_msg, status)


# ---------------------------------------------------------------------------
# Chrome/Electron process detection (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def exe_name_is_chrome_like_rust(exe_name: str) -> bool:
    """Return True if an executable basename is a known Chrome/Electron name."""
    return _rust_module.exe_name_is_chrome_like_rust(exe_name)


def extract_exe_path_from_args_rust(args: str) -> str:
    """Extract the executable path from a ps cmdline string."""
    return _rust_module.extract_exe_path_from_args_rust(args)


def is_chrome_like_process_rust(args: str, exe_name: str) -> bool:
    """Return True if the process looks like Chrome/Electron."""
    return _rust_module.is_chrome_like_process_rust(args, exe_name)


def extract_user_data_dir_rust(args: str) -> str | None:
    """Extract the ``--user-data-dir`` value from a command-line args string."""
    return _rust_module.extract_user_data_dir_rust(args)


def extract_debug_port_rust(args: str) -> str | None:
    """Extract the ``--remote-debugging-port`` value from a command-line args string."""
    return _rust_module.extract_debug_port_rust(args)


def parse_singleton_owner_pid_rust(symlink_target: str) -> int | None:
    """Extract the owning PID from a Chromium SingletonLock symlink target."""
    return _rust_module.parse_singleton_owner_pid_rust(symlink_target)


# ---------------------------------------------------------------------------
# Event format compact (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def format_event_compact_rust(event: dict[str, Any]) -> str:
    """Format an event dict into a compact, readable string (Rust-backed, no fallback)."""
    return _rust_module.format_event_compact_rust(event)


# ---------------------------------------------------------------------------
# Diagnose health-check models (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def check_status_str_rust(status: str) -> str | None:
    """Return the canonical string value of a CheckStatus (Rust-backed, no fallback)."""
    return _rust_module.check_status_str(status)


def check_status_severity_rust(status: str) -> int | None:
    """Return the numeric severity of a CheckStatus string (Rust-backed, no fallback)."""
    return _rust_module.check_status_severity(status)


def aggregate_status_rust(statuses: list[str]) -> str:
    """Aggregate multiple status strings into one (worst wins, Rust-backed, no fallback)."""
    return _rust_module.aggregate_status_rust(statuses)


def compare_status_rust(a: str, b: str) -> int | None:
    """Compare two status strings by severity (Rust-backed, no fallback)."""
    return _rust_module.compare_status(a, b)


def check_result_to_dict_rust(
    name: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a CheckResult dict (Rust-backed, no fallback)."""
    return _rust_module.check_result_to_dict(name, status, message, details)


def category_result_to_dict_rust(
    category: str,
    status: str,
    check_dicts: list[dict[str, Any]],
    message: str | None = None,
) -> dict[str, Any]:
    """Build a CategoryResult dict (Rust-backed, no fallback)."""
    return _rust_module.category_result_to_dict(category, status, check_dicts, message)


def check_tool_deps_rust(
    rg_path: str | None = None,
    fd_path: str | None = None,
    git_path: str | None = None,
) -> dict[str, Any]:
    """Build the tool_deps category result dict (Rust-backed, no fallback)."""
    return _rust_module.check_tool_deps_rust(rg_path, fd_path, git_path)


def check_protocols_from_results_rust(
    results: list[tuple[str, str, bool, str]],
) -> dict[str, Any]:
    """Build the protocols category result from import-check results (Rust-backed, no fallback)."""
    return _rust_module.check_protocols_from_results_rust(results)


def check_vector_stores_from_results_rust(
    check_dicts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the vector_stores category result from pre-built check dicts (Rust-backed, no fallback)."""
    return _rust_module.check_vector_stores_from_results_rust(check_dicts)


def check_models_no_config_rust() -> dict[str, Any]:
    """Build the models category result when no config is loaded (Rust-backed, no fallback)."""
    return _rust_module.check_models_no_config_rust()


def check_models_no_profile_rust(
    resolved: str | None = None,
    skillify_model_role: str = "embedding",
    skillify_resolved: str | None = None,
    embedding_dims: int | None = None,
) -> dict[str, Any]:
    """Build the models category result when embedding_profile is unset (Rust-backed, no fallback)."""
    return _rust_module.check_models_no_profile_rust(
        resolved, skillify_model_role, skillify_resolved, embedding_dims
    )


def check_models_ok_rust(
    resolved: str,
    skillify_model_role: str = "embedding",
    skillify_resolved: str | None = None,
    embedding_dims: int | None = None,
) -> dict[str, Any]:
    """Build the models category result when embedding_profile is configured (Rust-backed, no fallback)."""
    return _rust_module.check_models_ok_rust(
        resolved, skillify_model_role, skillify_resolved, embedding_dims
    )


def check_observability_from_results_rust(
    check_dicts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the observability category result from pre-built check dicts (Rust-backed, no fallback)."""
    return _rust_module.check_observability_from_results_rust(check_dicts)


def check_provider_credentials_rust(
    provider_name: str,
    api_key: str | None = None,
    provider_type: str = "openai",
) -> dict[str, Any]:
    """Validate provider credentials (Rust-backed, no fallback)."""
    return _rust_module.check_provider_credentials_rust(provider_name, api_key, provider_type)


def demote_inactive_provider_check_rust(
    check_dict: dict[str, Any],
    active: list[str],
    profile_name: str | None = None,
) -> dict[str, Any]:
    """Downgrade credential failures for inactive providers (Rust-backed, no fallback)."""
    return _rust_module.demote_inactive_provider_check_rust(check_dict, active, profile_name)


def missing_active_provider_rust(
    name: str,
    profile_name: str | None = None,
) -> dict[str, Any]:
    """Build a missing-active-provider check result dict (Rust-backed, no fallback)."""
    return _rust_module.missing_active_provider_rust(name, profile_name)


def check_providers_from_results_rust(
    check_dicts: list[dict[str, Any]],
    status_check_dicts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the providers category result from pre-built check dicts (Rust-backed, no fallback)."""
    return _rust_module.check_providers_from_results_rust(check_dicts, status_check_dicts)


def provider_from_spec_rust(spec: str | None) -> str | None:
    """Extract provider name from a `provider:model` spec (Rust-backed, no fallback)."""
    return _rust_module.provider_from_spec_rust(spec)


def unresolved_env_ref_rust(value: str | None) -> bool:
    """True if value contains an unresolved `${ENV}` reference (Rust-backed, no fallback)."""
    return _rust_module.unresolved_env_ref_rust(value)


def active_provider_names_rust(
    router_specs: list[str | None],
    embedding_model: str | None = None,
    embedding_profile_model_role: str | None = None,
) -> list[str]:
    """Collect active provider names from router specs and embedding config (Rust-backed, no fallback)."""
    # Pad to 5 elements (default, think, fast, image, ocr)
    padded: list[str | None] = list(router_specs[:5])
    while len(padded) < 5:
        padded.append(None)
    return _rust_module.active_provider_names_rust(
        padded, embedding_model, embedding_profile_model_role
    )


def check_mcp_configs_rust(
    server_specs: list[tuple[str, str, str | None, str | None]],
) -> dict[str, Any]:
    """Check MCP server configs from spec data (Rust-backed, no fallback)."""
    return _rust_module.check_mcp_configs_rust(server_specs)


def check_mcp_availability_rust(
    availability_data: list[tuple[str, str, str | None, bool, bool]],
) -> dict[str, Any]:
    """Check MCP server availability from availability data (Rust-backed, no fallback)."""
    return _rust_module.check_mcp_availability_rust(availability_data)


def check_mcp_servers_from_results_rust(
    check_dicts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the mcp_servers category result from pre-built check dicts (Rust-backed, no fallback)."""
    return _rust_module.check_mcp_servers_from_results_rust(check_dicts)


# ---------------------------------------------------------------------------
# Protocol pure-logic delegation (full-parity — no Python fallback)
#
# The Pydantic data models stay in Python (for model_dump / model_validate
# compatibility), but their pure logic — validation predicates, matching,
# evidence-string formatting, outcome-preview resolution — is Rust-backed.
# ---------------------------------------------------------------------------


def planner_outcome_text_preview_rust(outcome: dict[str, Any]) -> str | None:
    """Resolve bounded planner-facing text from an outcome dict (Rust-backed, no fallback)."""
    return _rust_module.planner_outcome_text_preview(json.dumps(outcome))


def step_result_to_evidence_string_rust(
    step_result: dict[str, Any],
    truncate: bool = True,
) -> str:
    """Build an evidence string for a StepResult from its dict (Rust-backed, no fallback)."""
    return _rust_module.step_result_to_evidence_string(json.dumps(step_result), truncate)


def is_valid_execution_hint_rust(hint: str) -> bool:
    """True when *hint* is a valid execution hint (Rust-backed, no fallback)."""
    return _rust_module.is_valid_execution_hint(hint)


def is_valid_step_status_rust(status: str) -> bool:
    """True when *status* is a valid step status (Rust-backed, no fallback)."""
    return _rust_module.is_valid_step_status(status)


def is_valid_plan_status_rust(status: str) -> bool:
    """True when *status* is a valid plan status (Rust-backed, no fallback)."""
    return _rust_module.is_valid_plan_status(status)


def is_valid_goal_directive_action_rust(action: str) -> bool:
    """True when *action* is a valid goal directive action (Rust-backed, no fallback)."""
    return _rust_module.is_valid_goal_directive_action(action)


def permission_matches_rust(
    category: str,
    action: str,
    scope: str,
    req_category: str,
    req_action: str,
    req_scope: str,
) -> bool:
    """Check if a granted permission covers a requested permission (Rust-backed, no fallback)."""
    return _rust_module.permission_matches(
        category, action, scope, req_category, req_action, req_scope
    )


def glob_match_rust(pattern: str, text: str) -> bool:
    """fnmatch-style glob match (Rust-backed, no fallback)."""
    return _rust_module.glob_match(pattern, text)


def is_valid_permission_category_rust(category: str) -> bool:
    """True when *category* is a valid permission category (Rust-backed, no fallback)."""
    return _rust_module.is_valid_permission_category(category)


def is_valid_action_rust(action: str) -> bool:
    """True when *action* is a valid permission action (Rust-backed, no fallback)."""
    return _rust_module.is_valid_permission_action(action)


def is_valid_policy_verdict_rust(verdict: str) -> bool:
    """True when *verdict* is a valid policy decision verdict (Rust-backed, no fallback)."""
    return _rust_module.is_valid_policy_verdict(verdict)


def is_valid_token_type_rust(token_type: str) -> bool:
    """True when *token_type* is a valid token type (Rust-backed, no fallback)."""
    return _rust_module.is_valid_token_type(token_type)


def aksk_pair_status_rust(
    aksk: dict[str, Any],
    now_iso: str,
) -> tuple[bool, bool, bool]:
    """Check AKSK pair status: ``(is_revoked, is_expired, is_active)`` (Rust-backed, no fallback)."""
    return _rust_module.aksk_pair_status(json.dumps(aksk), now_iso)


def token_claims_is_expired_rust(
    claims: dict[str, Any],
    now_iso: str,
) -> bool | None:
    """Check if token claims are expired (Rust-backed, no fallback; None on parse error)."""
    return _rust_module.token_claims_is_expired(json.dumps(claims), now_iso)


def token_info_status_rust(
    token_info: dict[str, Any],
    now_iso: str,
) -> tuple[bool, bool, bool]:
    """Check token info status: ``(is_revoked, is_expired, is_active)`` (Rust-backed, no fallback)."""
    return _rust_module.token_info_status(json.dumps(token_info), now_iso)


def is_valid_step_parallelism_rust(parallelism: str) -> bool:
    """True when *parallelism* is a valid step_parallelism value (Rust-backed, no fallback)."""
    return _rust_module.is_valid_step_parallelism(parallelism)


def is_unlimited_rust(max_parallel: int) -> bool:
    """True when *max_parallel* value means unlimited (0) (Rust-backed, no fallback)."""
    return _rust_module.is_unlimited(max_parallel)


def is_valid_importance_rust(importance: float) -> bool:
    """True when *importance* is within [0.0, 1.0] (Rust-backed, no fallback)."""
    return _rust_module.is_valid_importance(importance)


def is_valid_operation_kind_rust(kind: str) -> bool:
    """True when *kind* is a valid operation kind (Rust-backed, no fallback)."""
    return _rust_module.is_valid_operation_kind(kind)


def is_valid_operation_security_verdict_rust(verdict: str) -> bool:
    """True when *verdict* is a valid operation security decision verdict (Rust-backed, no fallback)."""
    return _rust_module.is_valid_operation_security_verdict(verdict)


def is_valid_thread_status_rust(status: str) -> bool:
    """True when *status* is a valid thread status (Rust-backed, no fallback)."""
    return _rust_module.is_valid_thread_status(status)


def is_valid_thread_priority_rust(priority: str) -> bool:
    """True when *priority* is a valid thread priority (Rust-backed, no fallback)."""
    return _rust_module.is_valid_thread_priority(priority)


def strip_legacy_claude_sessions_rust(metadata: dict[str, Any]) -> dict[str, Any]:
    """Strip the legacy ``claude_sessions`` key from a metadata dict (Rust-backed, no fallback)."""
    raw = _rust_module.strip_legacy_claude_sessions(json.dumps(metadata))
    return json.loads(raw)


def vector_record_new_rust(id: str) -> dict[str, Any]:
    """Create a new VectorRecord as a dict (Rust-backed, no fallback)."""
    raw = _rust_module.vector_record_new(id)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Core domain models (partial-parity — Python fallback retained)
# ---------------------------------------------------------------------------
#
# The Rust ``core`` crate implements the pure-logic portions of ``core/``:
# verbosity tier values, event priority values, domain classification,
# event type constants, and the ``_split_domain`` / ``_DOMAIN_DEFAULT_TIER``
# logic. The Python side retains Pydantic models (``SootheEvent`` and
# subclasses), the ``EventRegistry`` singleton, and Pydantic-driven
# ``register_event`` — those are framework-coupled and stay in Python.
# These wrappers expose the Rust pure-logic functions as delegation targets;
# callers fall back to the pure-Python implementation when the extension is
#


def should_show_rust(tier_value: int) -> bool | None:
    """Return True when a verbosity tier value is client-visible (NORMAL=1)."""
    tier = _rust_module.VerbosityTier(int(tier_value))
    return _rust_module.should_show(tier)


def classify_domain_rust(event_type: str) -> str | None:
    """Return the domain from an event type string via ``split('.')[1]``."""
    return _rust_module.classify_domain(event_type)


def domain_default_tier_rust(domain: str) -> int | None:
    """Return the default verbosity tier integer for a top-level domain."""
    tier = _rust_module.domain_default_tier(domain)
    return int(tier)


def get_verbosity_for_type_rust(event_type: str) -> int | None:
    """Return the verbosity tier integer for an event type (domain-default fallback)."""
    tier = _rust_module.get_verbosity_for_type(event_type)
    return int(tier)


def split_domain_rust(
    type_string: str,
) -> tuple[str, str, str, int] | None:
    """Split a type string into ``(domain, component, action, default_tier)``."""
    domain, component, action, tier = _rust_module.split_domain(type_string)
    return domain, component, action, int(tier)


def parse_verbosity_alias_rust(alias: str) -> int | None:
    """Parse a legacy verbosity string alias into a tier integer.

    ``quiet``/``normal`` → 1 (NORMAL); ``detailed``/``debug``/``internal`` → 99
    (INTERNAL); unknown strings default to 1 (NORMAL). Matching is
    case-insensitive.


    """
    tier = _rust_module.parse_verbosity_alias(alias)
    return int(tier)


def event_priority_value_rust(name: str) -> int | None:
    """Return the integer value of an ``EventPriority`` by name.

    Returns the priority value (0=CRITICAL, 1=HIGH, 2=NORMAL, 3=LOW),
    or ``None`` if *name* is invalid.
    """
    priority_map = {
        "CRITICAL": _rust_module.EventPriority.CRITICAL,
        "HIGH": _rust_module.EventPriority.HIGH,
        "NORMAL": _rust_module.EventPriority.NORMAL,
        "LOW": _rust_module.EventPriority.LOW,
    }
    p = priority_map.get(name.upper())
    if p is None:
        return None
    return int(p)


# ---------------------------------------------------------------------------
# Subagent pure-logic delegation (Phase 4: subagent helpers)
# ---------------------------------------------------------------------------
#
# The Rust ``subagents`` module in ``soothe-nano-utils`` implements the
# pure-logic portions of subagent helper modules: topic attachment stripping,
# search-query compaction, effort parsing, report summaries, reference
# formatting, loop termination, and scenario fallback classification.
# Python modules delegate to these and retain Pydantic models, async LLM
# calls, and config attribute access.


def subagents_ui_language_suffix_rust(topic: str) -> str | None:
    """Return the ``--- Triarch UI language ---`` block from *topic*.

    Returns the suffix string
    """
    return _rust_module.subagents_ui_language_suffix(topic)


def subagents_topic_without_attachments_rust(topic: str) -> str | None:
    """Return the user ask without file bodies.

    Returns the cleaned topic
    """
    return _rust_module.subagents_topic_without_attachments(topic)


def subagents_planned_research_topic_rust(parsed: Any, raw_topic: str) -> str | None:
    """Prefer LLM-extracted topic; else strip attachments.

    Returns the planned topic
    """
    return _rust_module.subagents_planned_research_topic(parsed, raw_topic)


def subagents_compact_search_query_rust(raw: str, max_len: int = 120) -> str | None:
    """Reduce a long task prompt to a short search-engine query.

    Returns the compacted query
    """
    return _rust_module.subagents_compact_search_query(raw, max_len)


def subagents_fallback_sub_questions_rust(topic: str) -> list[dict[str, str]] | None:
    """Single sub-question derived from the research topic.

    Returns a list of dicts
    """
    return _rust_module.subagents_fallback_sub_questions(topic)


def subagents_fallback_queries_rust(
    topic: str, sub_questions: list[Any] | None = None
) -> list[dict[str, str]] | None:
    """Build search queries from sub-questions or the topic.

    Returns a list of query dicts
    """
    return _rust_module.subagents_fallback_queries(topic, sub_questions or [])


def subagents_normalize_effort_rust(raw: str | None) -> str | None:
    """Coerce config/context value to a valid effort level (``normal``/``thorough``).

    Returns the effort level
    """
    return _rust_module.subagents_normalize_effort(raw)


def subagents_parse_effort_from_text_rust(text: str) -> str | None:
    """Parse ``effort: thorough`` from topic text.

    Returns the effort level
    """
    return _rust_module.subagents_parse_effort_from_text(text)


def subagents_profile_for_effort_rust(effort: str) -> tuple[str, int, int, int, int, int] | None:
    """Return the profile tuple for a validated effort level.

    Returns ``(effort, max_sub_questions, max_initial_queries,
    max_follow_up_queries, max_loops, crawl_top_n)``
    """
    return _rust_module.subagents_profile_for_effort(effort)


def subagents_effort_plan_hint_rust(effort: str) -> str | None:
    """Return the plan hint string for the effort level.

    Returns the hint
    """
    return _rust_module.subagents_effort_plan_hint(effort)


def subagents_effort_follow_up_hint_rust(effort: str) -> str | None:
    """Return the follow-up hint string for the effort level.

    Returns the hint
    """
    return _rust_module.subagents_effort_follow_up_hint(effort)


def subagents_preview_first_rust(text: str, chars: int = 200) -> str | None:
    """Return a single-line preview of *text* up to *chars* characters.

    Returns the preview
    """
    return _rust_module.subagents_preview_first(text, chars)


def subagents_result_summary_for_display_rust(result: str, max_len: int = 160) -> str | None:
    """First non-empty line from result text, truncated to *max_len*.

    Returns the summary
    """
    return _rust_module.subagents_result_summary_for_display(result, max_len)


def subagents_derive_report_title_rust(report: str, topic: str, fallback_prefix: str) -> str | None:
    """Pick a human title from report headings, falling back to the topic.

    Returns the title
    """
    return _rust_module.subagents_derive_report_title(report, topic, fallback_prefix)


def subagents_brief_summary_for_display_rust(
    report: str, preferred_sections: list[str], max_len: int = 320
) -> str | None:
    """Return a short summary skipping boilerplate Scope headings.

    Returns the summary
    """
    return _rust_module.subagents_brief_summary_for_display(report, preferred_sections, max_len)


def subagents_reference_key_rust(url: str | None, source_name: str, source_ref: str) -> str | None:
    """Compute a deduplication key for a reference.

    Returns the key
    """
    return _rust_module.subagents_reference_key(url, source_name, source_ref)


def subagents_format_references_section_rust(
    refs: list[dict[str, Any]], accessed_date: str | None = None
) -> str | None:
    """Format a markdown bibliography section.

    Returns the formatted section
    """
    return _rust_module.subagents_format_references_section(refs, accessed_date)


def subagents_merge_reference_indices_rust(refs: list[dict[str, Any]]) -> list[int] | None:
    """Return indices of deduplicated references (first-seen order).

    Returns a list of indices into *refs*
    """
    return _rust_module.subagents_merge_reference_indices(refs)


def subagents_check_termination_rust(
    min_results: int,
    min_source_diversity: int,
    max_duplicate_ratio: float,
    min_content_length: int,
    accumulated_source_names: list[str],
    current_contents: list[str],
    current_source_names: list[str],
    iteration: int,
) -> Any | None:
    """Check whether a research loop has gathered enough to stop early.

    Returns a ``TerminationDecision`` PyO3 object with ``should_terminate``,
    ``reason``, and ``confidence`` attributes
    """
    return _rust_module.subagents_check_termination(
        min_results,
        min_source_diversity,
        max_duplicate_ratio,
        min_content_length,
        accumulated_source_names,
        current_contents,
        current_source_names,
        iteration,
    )


def subagents_academic_fallback_classification_rust(
    topic: str,
) -> tuple[str, list[str], list[str]] | None:
    """Heuristic fallback scenario classification for academic research.

    Returns ``(scenario, sections, contextual_focus)``
    """
    return _rust_module.subagents_academic_fallback_classification(topic)


def subagents_deep_fallback_classification_rust(
    topic: str,
) -> tuple[str, list[str], list[str]] | None:
    """Heuristic fallback scenario classification for deep research.

    Returns ``(scenario, sections, contextual_focus)``
    """
    return _rust_module.subagents_deep_fallback_classification(topic)


def subagents_parse_json_from_llm_rust(content: str) -> dict[str, Any] | None:
    """Parse JSON from LLM output, stripping code fences.

    Returns the parsed dict
    """
    return _rust_module.subagents_parse_json_from_llm(content)


def subagents_effective_source_timeout_rust(
    configured: float, wizsearch_timeout: float, slack_sec: float = 5.0
) -> float | None:
    """Return gather wait_for timeout that will not cancel wizsearch early.

    Returns the effective timeout
    """
    return _rust_module.subagents_effective_source_timeout(configured, wizsearch_timeout, slack_sec)


def subagents_default_wizsearch_timeout_rust() -> float | None:
    """Return the default wizsearch timeout (30.0 seconds).

    Returns the timeout
    """
    return _rust_module.subagents_default_wizsearch_timeout()


# ---------------------------------------------------------------------------
# Persistence / observability / logging pure-logic delegation (Phase 5)
# ---------------------------------------------------------------------------


def split_sql_statements_rust(sql: str) -> list[str] | None:
    """Split an SQL script into individual statements (Rust-backed).

    Returns the list of statements
    """
    return _rust_module.split_sql_statements_rust(sql)


def is_duplicate_schema_error_rust(exc_msg: str) -> bool | None:
    """Check if an error message indicates a duplicate schema error (Rust-backed).

    Returns ``True``/``False``
    """
    return _rust_module.is_duplicate_schema_error_rust(exc_msg)


def is_recoverable_connection_error_rust(exc_msg: str) -> bool | None:
    """Check if an error message indicates a recoverable connection error (Rust-backed).

    Returns ``True``/``False``
    """
    return _rust_module.is_recoverable_connection_error_rust(exc_msg)


def advisory_lock_key_rust(database: str) -> int | None:
    """Compute a stable 63-bit advisory lock key from a database name (Rust-backed).

    Returns the key
    """
    return _rust_module.advisory_lock_key_rust(database)


def postgres_admin_dsn_rust(base_dsn: str) -> str | None:
    """Build a DSN targeting the ``postgres`` maintenance database (Rust-backed).

    Returns the DSN, or ``None`` if parsing fails.
    """
    return _rust_module.postgres_admin_dsn_rust(base_dsn)


def postgres_target_dsn_rust(base_dsn: str, database_name: str) -> str | None:
    """Build a DSN targeting a named database under ``base_dsn`` (Rust-backed)."""
    return _rust_module.postgres_target_dsn_rust(base_dsn, database_name)


def is_valid_db_name_rust(name: str) -> bool | None:
    """Validate a PostgreSQL database identifier (Rust-backed).

    Returns ``True``/``False``
    """
    return _rust_module.is_valid_db_name_rust(name)


def parse_migration_filename_rust(filename: str) -> tuple[str, str] | None:
    """Parse a migration filename into (version, name) (Rust-backed)."""
    result = _rust_module.parse_migration_filename_rust(filename)
    if result is not None:
        return (result[0], result[1])
    return None


def backoff_delay_rust(attempt: int, base_delay: float, max_delay: float) -> float | None:
    """Compute exponential backoff delay for a retry attempt (Rust-backed).

    Returns the delay in seconds
    """
    return _rust_module.backoff_delay_rust(attempt, base_delay, max_delay)


def cosine_similarity_rust(a: list[float], b: list[float]) -> float | None:
    """Compute cosine similarity between two vectors (Rust-backed).

    Returns the similarity
    """
    return _rust_module.cosine_similarity_rust(a, b)


def l2_distance_rust(a: list[float], b: list[float]) -> float | None:
    """Compute L2 (Euclidean) distance between two vectors (Rust-backed).

    Returns the distance
    """
    return _rust_module.l2_distance_rust(a, b)


def ip_similarity_rust(a: list[float], b: list[float]) -> float | None:
    """Compute inner product (dot product) similarity (Rust-backed).

    Returns the similarity
    """
    return _rust_module.ip_similarity_rust(a, b)


def pack_vector_f32_rust(vector: list[float]) -> bytes | None:
    """Pack a list of floats into F32 binary format (Rust-backed).

    Returns the packed bytes
    """
    return _rust_module.pack_vector_f32_rust(vector)


def loop_graph_langfuse_run_display_name_rust(trace_name: str | None) -> str | None:
    """Return the root graph run display name for a trace (Rust-backed).

    Returns the display name
    """
    return _rust_module.loop_graph_langfuse_run_display_name_rust(trace_name)


def execute_step_langfuse_run_display_name_rust(trace_name: str | None) -> str | None:
    """Return the execute-phase child run display name for a trace (Rust-backed).

    Returns the display name
    """
    return _rust_module.execute_step_langfuse_run_display_name_rust(trace_name)


def resolve_str_rust(value: str | None) -> str | None:
    """Strip and resolve ``${ENV}`` placeholders; return None if unresolved or empty (Rust-backed).

    Returns the resolved string
    """
    return _rust_module.resolve_str_rust(value)


def resolve_env_vars_rust(s: str) -> str | None:
    """Resolve ``${ENV_VAR}`` placeholders in a string (Rust-backed).

    Returns the resolved string
    """
    return _rust_module.resolve_env_vars_rust(s)


def normalize_tags_rust(tags: list[str] | None) -> list[str] | None:
    """Normalize a list of tags to non-empty stripped strings (Rust-backed)."""
    return _rust_module.normalize_tags_rust(tags) if tags else None


def short_thread_id_for_log_rust(thread_id: str) -> str | None:
    """Return the last N characters of a thread ID for compact log tags (Rust-backed).

    Returns the suffix
    """
    return _rust_module.short_thread_id_for_log_rust(thread_id)


# ---------------------------------------------------------------------------
# Thinking-token filter (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def strip_thinking_rust(text: str) -> tuple[str, list[str]]:
    """Strip complete ``<thinking>...</thinking>`` blocks from *text* (Rust-backed).

    Returns ``(stripped_text, captured_blocks)`` where ``captured_blocks``
    is a list of inner-content strings (without tags), in order of appearance.
    """
    return _rust_module.strip_thinking_rust(text)


def rust_thinking_stream_filter_new() -> Any:
    """Construct a Rust-backed ``ThinkingStreamFilter`` for streaming chunk filtering."""
    return _rust_module.ThinkingStreamFilter()


# ---------------------------------------------------------------------------
# LLM response text / JSON extraction (full-parity — no Python fallback)
# ---------------------------------------------------------------------------


def strip_json_text_rust(raw: str) -> str:
    """Normalize model output to a JSON-parseable string (Rust-backed).

    Strips markdown fences and, if prose precedes the first ``{``, slices to
    that position. Returns the normalized string.
    """
    return _rust_module.strip_json_text_rust(raw)


def parse_json_object_rust(content: str) -> Any:
    """Parse a JSON object from model output — raw or markdown-fenced (Rust-backed).

    Returns a dict or ``None`` when no valid JSON object can be extracted.
    """
    return _rust_module.parse_json_object_rust(content)
