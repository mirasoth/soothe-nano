"""Helpers for research topics that may include host attachment bodies.

Attached file extracts (for example Triarch PDF text) may be present so
PlanResearch can derive a concise topic plus search queries. Downstream nodes —
especially Synthesize — must receive only the extracted topic, never file bodies.
"""

from __future__ import annotations

from typing import Any

from soothe_nano._rust_compat import (
    subagents_planned_research_topic_rust,
    subagents_topic_without_attachments_rust,
    subagents_ui_language_suffix_rust,
)


def ui_language_suffix(topic: str) -> str:
    """Return the ``--- Triarch UI language ---`` block when present."""
    return subagents_ui_language_suffix_rust(topic)


def topic_without_attachments(topic: str) -> str:
    """Return the user ask (and optional UI-language footer), without file bodies."""
    return subagents_topic_without_attachments_rust(topic)


def planned_research_topic(parsed: dict[str, Any] | None, raw_topic: str) -> str:
    """Prefer LLM-extracted topic from PlanResearch; else strip attachments."""
    return subagents_planned_research_topic_rust(parsed, raw_topic)
