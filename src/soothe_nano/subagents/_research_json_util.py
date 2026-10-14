"""JSON utilities for research subagents."""

from __future__ import annotations

from typing import Any

from soothe_nano._rust_compat import (
    subagents_compact_search_query_rust,
    subagents_fallback_queries_rust,
    subagents_fallback_sub_questions_rust,
)
from soothe_nano.llm.response_text import llm_response_text, parse_json_object

__all__ = [
    "compact_search_query",
    "fallback_queries",
    "fallback_sub_questions",
    "llm_response_text",
    "parse_json_object",
]


def compact_search_query(raw: str, *, max_len: int = 120) -> str:
    """Reduce a long task prompt to a short search-engine query."""
    return subagents_compact_search_query_rust(raw, max_len)


def fallback_sub_questions(topic: str, *, domain: str = "public") -> list[dict[str, str]]:
    """Single sub-question derived from the research topic."""
    return subagents_fallback_sub_questions_rust(topic)


def fallback_queries(
    topic: str,
    sub_questions: list[Any] | None = None,
    *,
    default_domain: str = "public",
) -> list[dict[str, str]]:
    """Build search queries from sub-questions or the topic."""
    return subagents_fallback_queries_rust(topic, sub_questions or [])
