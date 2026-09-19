"""Persist large tool results to disk instead of truncating.

Replaces the truncate-and-discard strategy with persist-to-disk + compact
reference. The model can re-fetch the full output via read_file if needed,
but the default path keeps context small without information loss.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"

DEFAULT_PERSIST_THRESHOLD_CHARS = 10_000
DEFAULT_PREVIEW_CHARS = 2_000
DEFAULT_PER_MESSAGE_BUDGET_CHARS = 200_000


def _session_tool_results_dir(session_id: str, workspace_root: Path) -> Path:
    """Return the directory for persisting tool results for a session.

    Args:
        session_id: Unique session identifier.
        workspace_root: Workspace root path.

    Returns:
        Path to ``{workspace_root}/.soothe/tool-results/{session_id}``.
    """
    return workspace_root / ".soothe" / "tool-results" / session_id


def _get_tool_result_path(
    session_id: str,
    workspace_root: Path,
    tool_call_id: str,
    is_json: bool,
) -> Path:
    """Return the file path for a persisted tool result.

    Args:
        session_id: Session identifier.
        workspace_root: Workspace root path.
        tool_call_id: Unique tool call ID (used as filename).
        is_json: Whether the content is JSON (affects extension).

    Returns:
        File path for the persisted result.
    """
    ext = "json" if is_json else "txt"
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in tool_call_id)
    return _session_tool_results_dir(session_id, workspace_root) / f"{safe_id}.{ext}"


def _generate_preview(content: str, max_chars: int) -> tuple[str, bool]:
    """Generate a preview of content, truncating at a line boundary.

    Args:
        content: Full content string.
        max_chars: Maximum characters in the preview.

    Returns:
        Tuple of (preview, has_more). The preview is truncated at the last
        newline within max_chars to avoid cutting mid-line.
    """
    if len(content) <= max_chars:
        return content, False

    truncated = content[:max_chars]
    last_newline = truncated.rfind("\n")
    cut_point = last_newline if last_newline > max_chars * 0.5 else max_chars
    return content[:cut_point], True


def _format_file_size(size: int) -> str:
    """Format a byte/char count as a human-readable size string.

    Args:
        size: Size in characters (approximated as bytes for display).

    Returns:
        Human-readable size string like "2.0KB" or "150.0KB".
    """
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


def persist_tool_result(
    content: str,
    tool_call_id: str,
    session_id: str,
    workspace_root: Path,
    preview_chars: int = DEFAULT_PREVIEW_CHARS,
) -> dict[str, Any] | None:
    """Persist a tool result to disk and return metadata.

    Writes the full content to
    ``{workspace_root}/.soothe/tool-results/{session_id}/{tool_call_id}.txt``
    and returns a dict with the file path, original size, and preview.

    Args:
        content: Full tool result content.
        tool_call_id: Unique tool call ID.
        session_id: Session identifier.
        workspace_root: Workspace root path.
        preview_chars: Maximum preview characters.

    Returns:
        Dict with keys: filepath, original_size, preview, has_more.
        None if persistence failed (caller should fall back to truncation).
    """
    try:
        result_dir = _session_tool_results_dir(session_id, workspace_root)
        result_dir.mkdir(parents=True, exist_ok=True)
        filepath = _get_tool_result_path(session_id, workspace_root, tool_call_id, is_json=False)
        filepath.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "[ToolResultStorage] Failed to persist result for %s: %s",
            tool_call_id,
            exc,
        )
        return None

    preview, has_more = _generate_preview(content, preview_chars)
    return {
        "filepath": str(filepath),
        "original_size": len(content),
        "preview": preview,
        "has_more": has_more,
    }


def build_persisted_output_message(
    filepath: str,
    original_size: int,
    preview: str,
    has_more: bool,
    preview_chars: int = DEFAULT_PREVIEW_CHARS,
) -> str:
    """Build the compact reference message for a persisted tool result.

    Args:
        filepath: Path to the persisted file on disk.
        original_size: Original content size in characters.
        preview: Preview text to include in the reference.
        has_more: Whether the preview was truncated.
        preview_chars: Preview size for display label.

    Returns:
        Compact reference string wrapped in persisted-output tags.
    """
    lines = [
        PERSISTED_OUTPUT_TAG,
        f"Output too large ({_format_file_size(original_size)}). Full output saved to: {filepath}",
        "",
        f"Preview (first {_format_file_size(preview_chars)}):",
        preview,
    ]
    if has_more:
        lines.append("...")
    lines.append(PERSISTED_OUTPUT_CLOSING_TAG)
    return "\n".join(lines)


def is_persisted_content(content: Any) -> bool:
    """Check if content has already been replaced with a persisted reference.

    Args:
        content: ToolMessage content.

    Returns:
        True if content starts with the persisted-output tag.
    """
    return isinstance(content, str) and content.startswith(PERSISTED_OUTPUT_TAG)


def maybe_persist_tool_result(
    tool_message: ToolMessage,
    session_id: str,
    workspace_root: Path,
    persist_threshold: int = DEFAULT_PERSIST_THRESHOLD_CHARS,
    preview_chars: int = DEFAULT_PREVIEW_CHARS,
) -> ToolMessage:
    """Persist a tool result to disk if it exceeds the threshold.

    Args:
        tool_message: Original ToolMessage with full content.
        session_id: Session identifier.
        workspace_root: Workspace root path.
        persist_threshold: Character threshold above which to persist.
        preview_chars: Preview size for the compact reference.

    Returns:
        Original ToolMessage if under threshold, or a new ToolMessage with
        a compact reference if persisted. On persistence failure, returns
        the original (the existing ToolOutputCapMiddleware will truncate).
    """
    content = str(tool_message.content or "")
    if len(content) <= persist_threshold:
        return tool_message

    result = persist_tool_result(
        content,
        tool_message.tool_call_id,
        session_id,
        workspace_root,
        preview_chars=preview_chars,
    )
    if result is None:
        return tool_message

    reference = build_persisted_output_message(
        result["filepath"],
        result["original_size"],
        result["preview"],
        result["has_more"],
        preview_chars=preview_chars,
    )
    return tool_message.model_copy(update={"content": reference})
