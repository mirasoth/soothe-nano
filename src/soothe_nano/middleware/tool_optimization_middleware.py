"""Deterministic tool-call optimization middleware for execute scopes.

Owns lookup reuse/dedup and search-consolidation controls while keeping
step lifecycle semantics in the executor.
"""

from __future__ import annotations

import json
import logging
import shlex
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe_nano.middleware.tool_call_args_registry import coerce_tool_call_args

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.types import Command

logger = logging.getLogger(__name__)

_CACHEABLE_LOOKUP_TOOLS = frozenset({"read_file", "glob", "grep"})
_CACHE_INVALIDATING_TOOLS = frozenset(
    {
        "edit_file",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "write_file",
        "move_file",
        "delete_file",
        "run_command",
        "run_python",
    }
)
_NATIVE_SEARCH_TOOLS = frozenset({"glob", "grep"})
_DEFAULT_READ_FILE_THRASH_THRESHOLD = 3
_SIMPLE_SHELL_SEARCH_BINS = frozenset({"grep", "egrep", "fgrep", "ag"})
_FIND_PATH_FLAGS = frozenset({"-name", "-iname", "-path", "-ipath", "-regex", "-iregex"})
_RG_FIXED_FLAGS = frozenset({"-F", "--fixed-strings"})
_RG_REGEX_FLAGS = frozenset({"-P", "--pcre2", "-e", "--regexp"})
_RG_REGEX_METACHARS = frozenset(".^$*+?{}[]|()\\")
_SHELL_SEARCH_REDIRECT_MSG = (
    "Native search preferred: use the grep tool for content search and glob for "
    "path patterns instead of shell grep/rg/find. Only use run_command with rg when "
    "you need true regex or flags the grep tool lacks (always pass an explicit path "
    "after the pattern)."
)
_ENV_SKIP_TOKENS = frozenset({"sudo", "env", "command", "time", "nice"})
_COMPOUND_MARKERS = ("|", "&&", ";", "||")


@dataclass(slots=True)
class _ReadFileWindow:
    """Normalized read_file path for consecutive-slice thrash detection."""

    path: str


@dataclass(slots=True)
class _ToolReuseState:
    """Per-execution-scope deterministic tool lookup reuse state."""

    scope_id: str = ""
    cache: dict[str, tuple[Any, str | None]] = field(default_factory=dict)
    last_signature: str | None = None
    repeated_signature_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    duplicate_signature_blocked: int = 0
    native_search_calls: int = 0
    shell_search_fallback_blocked: int = 0
    empty_write_todos_short_circuited: int = 0
    read_file_thrash_guided: int = 0
    recent_read_windows: list[_ReadFileWindow] = field(default_factory=list)


_tool_reuse_state: ContextVar[_ToolReuseState | None] = ContextVar(
    "tool_reuse_state",
    default=None,
)


def _runtime_config_from_request(request: ToolCallRequest) -> dict[str, Any]:
    runtime = getattr(request, "runtime", None)
    cfg = getattr(runtime, "config", None)
    return cfg if isinstance(cfg, dict) else {}


def _scope_id_for_request(request: ToolCallRequest) -> str:
    """Build a deterministic scope id for per-step lookup reuse cache."""
    cfg = _runtime_config_from_request(request)
    configurable = cfg.get("configurable", {})
    if not isinstance(configurable, dict):
        configurable = {}
    thread_id = str(configurable.get("thread_id") or "")
    checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
    return f"{thread_id}:{checkpoint_ns}"


def _normalize_args_for_signature(args: dict[str, Any]) -> str:
    """Canonical JSON for deterministic signature matching."""
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except TypeError:
        return str(args)


def _tool_message_text(result: Any) -> str:
    """Extract best-effort textual body from a ToolMessage-like result."""
    if not isinstance(result, ToolMessage):
        return str(result)
    content = result.content
    if isinstance(content, str):
        return content
    return str(content)


def _tool_result_has_actionable_output(result: Any) -> bool:
    """True when tool output contains actionable non-error content."""
    text = _tool_message_text(result).strip()
    if not text:
        return False
    lowered = text.lower()
    # Deterministic structural signals from tool output shape.
    if lowered.startswith("error:"):
        return False
    if "no files found" in lowered:
        return False
    if "no matches found" in lowered:
        return False
    if "0 matches" in lowered:
        return False
    if text in ("[]", "{}", "None"):
        return False
    return True


def _empty_write_todos_payload(args: dict[str, Any]) -> bool:
    """True when write_todos args carry an empty todo list."""
    todos = args.get("todos")
    if todos is None:
        return True
    if isinstance(todos, (list, tuple)):
        return len(todos) == 0
    return False


def _read_file_window(args: dict[str, Any]) -> _ReadFileWindow | None:
    """Build a normalized window from read_file args, or None if path missing."""
    path = str(args.get("file_path") or args.get("path") or "").strip()
    if not path:
        return None
    return _ReadFileWindow(path=path)


def _first_positional_arg(tokens: list[str]) -> str | None:
    """Return the first non-flag token (pattern/path) from argv after the binary."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--":
            return tokens[i + 1] if i + 1 < len(tokens) else None
        if tok.startswith("-"):
            # Flags that take a separate value (e.g. -g '*.py', -e PAT).
            if tok in {"-g", "--glob", "-e", "--regexp", "-f", "--file"} and i + 1 < len(tokens):
                i += 2
                continue
            i += 1
            continue
        return tok
    return None


def _pattern_looks_like_regex(pattern: str) -> bool:
    """True when pattern contains regex metacharacters (structural check)."""
    return any(ch in _RG_REGEX_METACHARS for ch in pattern)


def _is_simple_shell_search_command(command: str) -> bool:
    """True when command is a simple shell content/path search to redirect.

    Blocks grep/ag and literal-style rg/find. Allows compound pipelines and
    rg invocations that clearly need regex (non-fixed-string with metacharacters
    or explicit regex flags).
    """
    text = command.strip()
    if not text:
        return False
    if any(marker in text for marker in _COMPOUND_MARKERS):
        return False
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    if not tokens:
        return False

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if "=" in tok and not tok.startswith("-") and not tok.startswith("./"):
            i += 1
            continue
        if tok in _ENV_SKIP_TOKENS:
            i += 1
            continue
        break
    if i >= len(tokens):
        return False

    bin_name = Path(tokens[i]).name
    rest = tokens[i + 1 :]
    if bin_name in _SIMPLE_SHELL_SEARCH_BINS:
        return True
    if bin_name == "rg":
        if any(t in _RG_FIXED_FLAGS for t in rest):
            return True
        if any(t in _RG_REGEX_FLAGS for t in rest):
            return False
        pattern = _first_positional_arg(rest)
        if pattern is not None and _pattern_looks_like_regex(pattern):
            return False
        return True
    if bin_name == "find":
        return any(t in _FIND_PATH_FLAGS for t in rest)
    return False


def _scope_metrics(state: _ToolReuseState) -> dict[str, int]:
    """Expose current deterministic reuse metrics for executor telemetry."""
    return {
        "repeated_signature_calls": int(state.repeated_signature_calls),
        "cache_hits": int(state.cache_hits),
        "cache_misses": int(state.cache_misses),
        "duplicate_signature_blocked": int(state.duplicate_signature_blocked),
        "native_search_calls": int(state.native_search_calls),
        "shell_search_fallback_blocked": int(state.shell_search_fallback_blocked),
        "empty_write_todos_short_circuited": int(state.empty_write_todos_short_circuited),
        "read_file_thrash_guided": int(state.read_file_thrash_guided),
    }


def get_tool_reuse_metrics_snapshot() -> dict[str, int]:
    """Return per-scope tool reuse metrics from current async context."""
    state = _tool_reuse_state.get()
    if state is None:
        return {
            "repeated_signature_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "duplicate_signature_blocked": 0,
            "native_search_calls": 0,
            "shell_search_fallback_blocked": 0,
            "empty_write_todos_short_circuited": 0,
            "read_file_thrash_guided": 0,
        }
    return _scope_metrics(state)


def _reset_scope_counters(state: _ToolReuseState, scope_id: str) -> None:
    state.scope_id = scope_id
    state.cache.clear()
    state.last_signature = None
    state.repeated_signature_calls = 0
    state.cache_hits = 0
    state.cache_misses = 0
    state.duplicate_signature_blocked = 0
    state.native_search_calls = 0
    state.shell_search_fallback_blocked = 0
    state.empty_write_todos_short_circuited = 0
    state.read_file_thrash_guided = 0
    state.recent_read_windows.clear()


class ToolOptimizationMiddleware(AgentMiddleware):
    """Deterministic tool-call optimization middleware.

    Controls:
    - Lookup cache for deterministic same-args reuse.
    - Duplicate empty-result replay blocking.
    - Native-search-first policy (block simple shell grep/rg/find).
    - Empty write_todos short-circuit.
    - Same-path read_file thrash guidance.
    """

    name = "ToolOptimizationMiddleware"
    # Opt into general-purpose subagent inheritance (deepagents generic flag).
    propagate_to_general_purpose = True

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        metadata = getattr(request, "metadata", None) or {}
        if metadata.get("_batched"):
            return await handler(request)

        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name") or "").strip()
        tool_args = coerce_tool_call_args(tool_call.get("args"))
        tool_call_id = str(tool_call.get("id") or "")

        state = _tool_reuse_state.get()
        if state is None:
            state = _ToolReuseState()
            _tool_reuse_state.set(state)
        scope_id = _scope_id_for_request(request)
        if state.scope_id != scope_id:
            _reset_scope_counters(state, scope_id)

        if tool_name == "write_todos" and _empty_write_todos_payload(tool_args):
            state.empty_write_todos_short_circuited += 1
            logger.debug(
                "[ToolOptimization] empty write_todos short-circuit scope=%s count=%d",
                scope_id,
                state.empty_write_todos_short_circuited,
            )
            return ToolMessage(
                content="Todo list unchanged (empty write_todos skipped).",
                tool_call_id=tool_call_id,
                name=tool_name,
                status="success",
            )

        if tool_name == "read_file":
            window = _read_file_window(tool_args)
            if window is not None:
                threshold = _DEFAULT_READ_FILE_THRASH_THRESHOLD
                streak = state.recent_read_windows
                if streak and streak[-1].path == window.path:
                    streak.append(window)
                else:
                    streak.clear()
                    streak.append(window)
                if len(streak) >= threshold:
                    thrash_count = len(streak)
                    state.read_file_thrash_guided += 1
                    logger.debug(
                        "[ToolOptimization] read_file thrash guidance scope=%s path=%s count=%d",
                        scope_id,
                        window.path,
                        state.read_file_thrash_guided,
                    )
                    # Clear streak so a subsequent wider read_file can proceed.
                    state.recent_read_windows.clear()
                    return ToolMessage(
                        content=(
                            f"Read thrash guidance: {thrash_count} consecutive read_file "
                            f"calls on the same path ({window.path}). Prefer one wider "
                            "read_file (larger limit/range or full file) instead of many "
                            "tiny offset/limit slices. Previous slice results remain in "
                            "context — do not invent file contents."
                        ),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        status="error",
                    )
            else:
                state.recent_read_windows.clear()
        elif tool_name:
            # Other tools break the consecutive read_file streak.
            state.recent_read_windows.clear()

        if tool_name in _NATIVE_SEARCH_TOOLS:
            state.native_search_calls += 1

        if tool_name == "run_command":
            command = str(tool_args.get("command") or "")
            if _is_simple_shell_search_command(command):
                state.shell_search_fallback_blocked += 1
                logger.debug(
                    "[ToolOptimization] blocked simple shell search scope=%s "
                    "native_search_calls=%d",
                    scope_id,
                    state.native_search_calls,
                )
                return ToolMessage(
                    content=_SHELL_SEARCH_REDIRECT_MSG,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    status="error",
                )

        signature: str | None = None
        if tool_name in _CACHEABLE_LOOKUP_TOOLS:
            signature = f"{tool_name}:{_normalize_args_for_signature(tool_args)}"
            if signature == state.last_signature:
                state.repeated_signature_calls += 1
            cached = state.cache.get(signature)
            if cached is not None:
                state.cache_hits += 1
                cached_content, cached_status = cached
                cached_msg = ToolMessage(
                    content=cached_content,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    status=cached_status,
                )
                if signature == state.last_signature and not _tool_result_has_actionable_output(
                    cached_msg
                ):
                    state.duplicate_signature_blocked += 1
                    logger.debug(
                        "[ToolOptimization] blocked duplicate empty signature scope=%s tool=%s blocked=%d",
                        scope_id,
                        tool_name,
                        state.duplicate_signature_blocked,
                    )
                    return ToolMessage(
                        content=(
                            "Duplicate lookup blocked: the same tool call with identical arguments "
                            "already returned no actionable result in this step scope. "
                            "Change arguments (path/glob/pattern/offset) before retrying."
                        ),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        status="error",
                    )
                logger.debug(
                    "[ToolOptimization] cache hit scope=%s tool=%s hits=%d repeated=%d",
                    scope_id,
                    tool_name,
                    state.cache_hits,
                    state.repeated_signature_calls,
                )
                return cached_msg
            state.cache_misses += 1

        result = await handler(request)

        if tool_name in _CACHE_INVALIDATING_TOOLS:
            state.cache.clear()
            state.last_signature = None
            return result

        if signature is not None and isinstance(result, ToolMessage):
            state.last_signature = signature
            state.cache[signature] = (
                result.content,
                getattr(result, "status", None),
            )

        return result


__all__ = ["ToolOptimizationMiddleware", "get_tool_reuse_metrics_snapshot"]
