"""One-line summary for computer_use subagent completion display."""

from __future__ import annotations


def computer_use_result_summary_for_display(result: str, *, max_len: int = 160) -> str:
    """First non-empty line from computer-use result text (markdown/prose)."""
    for line in (result or "").split("\n"):
        s = line.strip()
        if s:
            out = " ".join(s.split())
            if len(out) > max_len:
                return out[: max_len - 1] + "…"
            return out
    return ""


__all__ = ["computer_use_result_summary_for_display"]
