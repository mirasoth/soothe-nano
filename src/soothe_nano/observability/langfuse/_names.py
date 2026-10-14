"""Langfuse display-name helpers."""

from __future__ import annotations

from soothe_nano._rust_compat import (
    execute_step_langfuse_run_display_name_rust,
    loop_graph_langfuse_run_display_name_rust,
)

_ROOT_GRAPH_RUN_NAME = "nanoagent-graph"
_EXECUTE_STEP_RUN_NAME = "execute-step"


def loop_graph_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return the root graph run display name for a trace."""
    return loop_graph_langfuse_run_display_name_rust(trace_name)


def execute_step_langfuse_run_display_name(trace_name: str | None) -> str:
    """Return the execute-phase child run display name for a trace."""
    return execute_step_langfuse_run_display_name_rust(trace_name)
