"""Lightweight text preview for logging (mirrors ``browser_use._preview``)."""

from __future__ import annotations


def preview_first(text: str, chars: int = 200) -> str:
    """Return a single-line preview of ``text`` up to ``chars`` characters."""
    t = str(text).replace("\n", " ").strip()
    if len(t) <= chars:
        return t
    if chars <= 1:
        return "…"
    return t[: chars - 1] + "…"


__all__ = ["preview_first"]
