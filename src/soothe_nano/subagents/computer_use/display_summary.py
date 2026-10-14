"""One-line summary for computer_use subagent completion display."""

from __future__ import annotations

from soothe_nano._rust_compat import subagents_result_summary_for_display_rust

__all__ = ["computer_use_result_summary_for_display"]


def computer_use_result_summary_for_display(result: str, *, max_len: int = 160) -> str:
    """First non-empty line from computer-use result text (markdown/prose)."""
    return subagents_result_summary_for_display_rust(result, max_len)
