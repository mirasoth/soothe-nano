"""Unified text preview utility for consistent truncation across the codebase.

Provides char-based, line-based, and full-output preview modes with
configurable markers. Delegates to the Rust ``preview_full`` implementation
via PyO3; convenience wrappers compose the Rust-backed core.
"""

from __future__ import annotations

from typing import Literal

from soothe_nano._rust_compat import preview_full_rust, text_preview_rust

# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

DEFAULT_PREVIEW_CHARS: int = 200
"""Default character limit for char-based previews."""

DEFAULT_PREVIEW_LINES: int = 5
"""Default line limit for line-based previews."""

DEFAULT_MARKER_TEMPLATE: str = "[...{count} {unit} abbr...]"
"""Template for auto-generated truncation markers.

Available variables: `{count}` (number of omitted units) and `{unit}`
(`"chars"` or `"lines"`).
"""


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def preview(
    text: str,
    *,
    mode: Literal["chars", "lines", "full"] = "chars",
    first: int | None = None,
    last: int | None = None,
    marker: str | None = None,
) -> str:
    """Generate a preview of text with configurable truncation.

    Args:
        text: Input text to preview.
        mode: Preview mode:
            - `"chars"`: Character-based truncation (default).
            - `"lines"`: Line-based truncation.
            - `"full"`: No truncation (return as-is).
        first: First N chars/lines to include.  Defaults to 200 (chars) or
            5 (lines).
        last: Last N chars/lines to include.  When `None`, only the
            *first* portion is shown.  When set, both *first* and *last*
            are shown with a marker in between.
        marker: Custom truncation marker.  `None` uses the default
            `"[...N chars/lines abbr...]"`.  Set to `""` to suppress.

    Returns:
        Previewed text with optional truncation marker.
    """
    if mode == "full" or not text:
        return text
    return preview_full_rust(text, mode=mode, first=first, last=last, marker=marker)


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def preview_first(text: str, chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    """Preview the first N characters."""
    return preview(text, mode="chars", first=chars)


def preview_lines(
    text: str,
    first: int = DEFAULT_PREVIEW_LINES,
    last: int = 0,
) -> str:
    """Preview the first N lines and optionally the last M lines."""
    return preview(text, mode="lines", first=first, last=last if last > 0 else None)


def log_preview(text: str, chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    """Logger-optimized preview with a minimal `"..."` marker."""
    if not text:
        return text
    return text_preview_rust(text, chars)


# Hosts may append extracted file bodies after these markers.
# Logs should keep the user ask + attachment metadata, and omit the dump.
_ATTACHMENT_BODY_MARKERS: tuple[str, ...] = ("--- Triarch attachments (extracted content) ---",)

DEFAULT_GOAL_LOG_CHARS: int = 1200
"""Default total character budget for goal-description log previews."""


def goal_description_for_log(
    description: str,
    *,
    max_chars: int = DEFAULT_GOAL_LOG_CHARS,
) -> str:
    """Return a log-safe goal description that omits extracted attachment bodies.

    Preserves the user ask and light context metadata (for example
    `Attached files: …`). When an extracted-attachment section is present,
    everything from that marker onward is dropped so `soothe.log` stays
    readable.

    The stored goal description is unchanged; this helper is for logging only.
    """
    text = description or ""
    if not text:
        return ""

    cut: int | None = None
    for marker in _ATTACHMENT_BODY_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cut = idx if cut is None else min(cut, idx)

    if cut is not None:
        text = text[:cut].rstrip()
        if not text:
            return ""

    return log_preview(text, chars=max_chars)


# ---------------------------------------------------------------------------
# Evidence-specific utilities
# ---------------------------------------------------------------------------


def create_output_summary(
    content: str,
    first_chars: int = 300,
    last_chars: int = 200,
) -> dict[str, str]:
    """Create truncated output summary for Reason phase evidence.

    Captures initial findings and final results without full output bloat.
    Used for CoreAgent execution evidence in Layer 2 Reason phase.

    Args:
        content: Full output content from AIMessage + ToolMessage accumulation
        first_chars: Number of chars from beginning (default: 300)
        last_chars: Number of chars from end (default: 200)

    Returns:
        Dict with "first" and "last" keys containing truncated sections.
        Empty strings if content is empty.

    Examples:
        >>> create_output_summary(
        ...     "Found async patterns in file.py...", first_chars=50, last_chars=30
        ... )
        {'first': 'Found async patterns in file.py...', 'last': '...'}

        >>> create_output_summary("")
        {'first': '', 'last': ''}
    """
    if not content:
        return {"first": "", "last": ""}

    total_len = len(content)

    # If content shorter than both sections, just return full content in "first"
    if total_len <= first_chars + last_chars:
        return {"first": content, "last": ""}

    first_section = content[:first_chars]
    last_section = content[total_len - last_chars :]

    # Clean truncation: avoid cutting mid-word if possible (look back for space)
    # Only apply to first section (last section is end of text, harder to clean)

    # Find last space in first_chars range to avoid mid-word cut
    last_space_in_first = first_section.rfind(" ")
    if last_space_in_first > first_chars * 0.8:  # Only if space is reasonably close to target
        first_section = first_section[:last_space_in_first]

    return {"first": first_section.strip(), "last": last_section.strip()}
