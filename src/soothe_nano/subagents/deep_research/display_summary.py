"""Summaries for deep_research completion display."""

from __future__ import annotations

from soothe_nano._rust_compat import (
    subagents_brief_summary_for_display_rust,
    subagents_derive_report_title_rust,
)

_PREFERRED_SUMMARY_SECTIONS = frozenset(
    {
        "executive summary",
        "key findings",
        "overview",
        "summary",
        "verdict",
        "recommendation",
    }
)


def derive_report_title(report: str, topic: str) -> str:
    """Pick a human title from report headings, falling back to the research topic."""
    return subagents_derive_report_title_rust(report, topic, "research-report")


def deep_research_brief_summary_for_display(report: str, *, max_len: int = 320) -> str:
    """Return a short summary skipping boilerplate Scope headings."""
    sections = sorted(_PREFERRED_SUMMARY_SECTIONS)
    return subagents_brief_summary_for_display_rust(report, sections, max_len)
