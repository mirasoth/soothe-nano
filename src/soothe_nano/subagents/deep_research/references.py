"""Reference collection and bibliography formatting for Deep Research."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from soothe_nano._rust_compat import (
    subagents_format_references_section_rust,
    subagents_merge_reference_indices_rust,
    subagents_reference_key_rust,
)

from .protocol import ResearchReference, SourceResult

_URL_IN_TEXT = re.compile(r"https?://[^\s\])>\"']+")


def reference_from_source_result(
    result: SourceResult,
    *,
    query: str | None = None,
) -> ResearchReference:
    """Build a structured reference from a gather ``SourceResult``."""
    meta = result.metadata or {}
    url = meta.get("url") or meta.get("link")
    if not url and result.source_ref.startswith(("http://", "https://")):
        url = result.source_ref
    if not url:
        found = _URL_IN_TEXT.search(result.content or "")
        if found:
            url = found.group(0).rstrip(".,;)")
    title = meta.get("title") or meta.get("domain")
    if not title and url:
        try:
            host = urlparse(str(url)).hostname or ""
            title = host.removeprefix("www.") or None
        except Exception:
            title = None
    if not title:
        title = result.source_ref if result.source_ref else result.source_name
    return ResearchReference(
        url=str(url) if url else None,
        title=str(title) if title else None,
        source_name=result.source_name,
        source_ref=result.source_ref,
        query=query,
    )


def _reference_key(ref: ResearchReference) -> str:
    return subagents_reference_key_rust(ref.url, ref.source_name, ref.source_ref)


def merge_references(refs: list[ResearchReference]) -> list[ResearchReference]:
    """Deduplicate references while preserving first-seen order."""
    ref_dicts = [
        {
            "url": r.url,
            "source_name": r.source_name,
            "source_ref": r.source_ref,
            "title": r.title,
            "query": r.query,
        }
        for r in refs
    ]
    keep_indices = subagents_merge_reference_indices_rust(ref_dicts)
    return [refs[i] for i in keep_indices]


def format_references_section(
    refs: list[ResearchReference],
    *,
    accessed_date: str | None = None,
) -> str:
    """Format a markdown bibliography section."""
    ref_dicts = [
        {
            "url": r.url,
            "source_name": r.source_name,
            "source_ref": r.source_ref,
            "title": r.title,
            "query": r.query,
        }
        for r in refs
    ]
    return subagents_format_references_section_rust(ref_dicts, accessed_date)


__all__ = [
    "format_references_section",
    "merge_references",
    "reference_from_source_result",
]
