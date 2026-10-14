"""Lightweight text preview for logging (mirrors ``browser_use._preview``)."""

from __future__ import annotations

from soothe_nano._rust_compat import subagents_preview_first_rust

__all__ = ["preview_first"]


def preview_first(text: str, chars: int = 200) -> str:
    """Return a single-line preview of ``text`` up to ``chars`` characters."""
    return subagents_preview_first_rust(text, chars)
