"""Global constants for Coding CoreAgent configuration.

Centralizing defaults keeps tool timeouts and output caps consistent.
"""

from soothe_sdk.paths import DEFAULT_EXECUTE_TIMEOUT  # noqa: F401

__all__ = [
    "DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS",
    "DEFAULT_EXECUTE_TIMEOUT",
    "DEFAULT_IDENTICAL_TOOL_CALL_THRESHOLD",
    "DEFAULT_TASK_TIMEOUT_SECONDS",
    "DEFAULT_TOOL_OUTPUT_CHARS",
    "DEFAULT_TOOL_RESULT_EVICTION_MAX_TOKENS",
    "DEFAULT_TOOL_RESULT_EVICTION_PROTECT_RECENT",
    "DEFAULT_TOOL_RESULT_PER_MESSAGE_BUDGET",
    "DEFAULT_TOOL_RESULT_PERSIST_THRESHOLD",
    "DEFAULT_TOOL_RESULT_PREVIEW_CHARS",
    "MAX_EXECUTE_TIMEOUT",
    "clamp_execute_timeout",
]


# ============================================================================
# Execution Tool Limits
# ============================================================================

# Default timeout for shell command execution
# Used by execution tools (run_command) and TUI display logic
# Canonical home is ``soothe_sdk.paths`` (shared with host/CLI/daemon).

# Upper bound for per-call run_command timeout (LLM arg and middleware ceiling)
MAX_EXECUTE_TIMEOUT = 18000  # 5 hours

# Default timeout for the task tool (subagent delegation)
DEFAULT_TASK_TIMEOUT_SECONDS = 18000  # 5 hours


def clamp_execute_timeout(seconds: int | float) -> int:
    """Clamp run_command timeout to `MAX_EXECUTE_TIMEOUT`."""
    return min(int(seconds), MAX_EXECUTE_TIMEOUT)


# Max chars for shell/code tool stdout (run_command) and code_exec aggregation.
DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS = 100_000

# Max chars for non-code_exec tool output in stream aggregation.
DEFAULT_TOOL_OUTPUT_CHARS = 10_000

# Consecutive identical tool-call threshold for the Act-stream circuit breaker.
# When the same tool is invoked with the same arguments N times in a row within
# a single step, the stream is stopped to prevent degenerate repetition loops
# (e.g. heartbeat-sentinel recovery re-emitting the same read_file call).
DEFAULT_IDENTICAL_TOOL_CALL_THRESHOLD = 3


# ============================================================================
# Tool Result Disk Storage (IG-778 §6)
# ============================================================================

# Character threshold above which to persist tool results to disk.
DEFAULT_TOOL_RESULT_PERSIST_THRESHOLD = 10_000

# Per-message aggregate budget for tool results (chars).
DEFAULT_TOOL_RESULT_PER_MESSAGE_BUDGET = 200_000

# Preview size shown in the compact reference message (chars).
DEFAULT_TOOL_RESULT_PREVIEW_CHARS = 2_000


# ============================================================================
# Tool Result Eviction (IG-778 §2)
# ============================================================================

# Maximum estimated tool-result tokens before eviction triggers.
DEFAULT_TOOL_RESULT_EVICTION_MAX_TOKENS = 60_000

# Number of most-recent tool results to protect from eviction.
DEFAULT_TOOL_RESULT_EVICTION_PROTECT_RECENT = 3
