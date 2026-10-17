"""Keep tool results from saturating model context.

Two complementary strategies: persist oversized results to disk behind a
compact ``<persisted-output>`` reference (the model can re-fetch via
``read_file``), and evict old evictable results to a stub when total
tool-result token estimate exceeds a threshold.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe_nano.config.models import ToolResultEvictionConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persist-to-disk (storage) constants
# ---------------------------------------------------------------------------

PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"

DEFAULT_PERSIST_THRESHOLD_CHARS = 10_000
DEFAULT_PREVIEW_CHARS = 2_000
DEFAULT_PER_MESSAGE_BUDGET_CHARS = 200_000

# ---------------------------------------------------------------------------
# Evict-to-stub (eviction) constants
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4

EVICTABLE_TOOLS = frozenset(
    {
        "read_file",
        "grep",
        "glob",
        "run_command",
        "run_python",
        "ls",
        "file_info",
    }
)

NON_EVICTABLE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "apply_diff",
        "delete",
        "move_file",
        "write_todos",
        "task",
    }
)


# ---------------------------------------------------------------------------
# Persist-to-disk helpers
# ---------------------------------------------------------------------------


def _session_tool_results_dir(session_id: str, workspace_root: Path) -> Path:
    """Return ``{workspace_root}/.soothe/tool-results/{session_id}``."""
    return workspace_root / ".soothe" / "tool-results" / session_id


def _get_tool_result_path(
    session_id: str,
    workspace_root: Path,
    tool_call_id: str,
    is_json: bool,
) -> Path:
    """Return the file path for a persisted tool result."""
    ext = "json" if is_json else "txt"
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in tool_call_id)
    return _session_tool_results_dir(session_id, workspace_root) / f"{safe_id}.{ext}"


def _generate_preview(content: str, max_chars: int) -> tuple[str, bool]:
    """Generate a preview of content, truncating at a line boundary.

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
    """Format a byte/char count as a human-readable size string."""
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
    """Build the compact reference message for a persisted tool result."""
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
    """Check if content has already been replaced with a persisted reference."""
    return isinstance(content, str) and content.startswith(PERSISTED_OUTPUT_TAG)


def maybe_persist_tool_result(
    tool_message: ToolMessage,
    session_id: str,
    workspace_root: Path,
    persist_threshold: int = DEFAULT_PERSIST_THRESHOLD_CHARS,
    preview_chars: int = DEFAULT_PREVIEW_CHARS,
) -> ToolMessage:
    """Persist a tool result to disk if it exceeds the threshold.

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


# ---------------------------------------------------------------------------
# Persist-to-disk middleware
# ---------------------------------------------------------------------------


class ToolResultStorageMiddleware(AgentMiddleware):
    """Persist large tool results to disk, replacing content with references.

    Operates in two modes:

    1. **Per-tool persistence** (awrap_tool_call): When a single tool result
       exceeds the persistence threshold, write it to disk and replace the
       content with a compact reference containing the file path and a preview.

    2. **Per-message budget** (awrap_model_call): When the aggregate size of
       tool results in a single turn exceeds the per-message budget, persist
       the largest results to disk until under budget.

    The middleware is idempotent: re-application on subsequent hops is a
    no-op because persisted results are already replaced with references
    (detected by the ``<persisted-output>`` tag prefix).
    """

    name = "ToolResultStorageMiddleware"

    def __init__(
        self,
        *,
        workspace_root: str,
        session_id: str = "",
        persist_threshold: int = DEFAULT_PERSIST_THRESHOLD_CHARS,
        per_message_budget: int = DEFAULT_PER_MESSAGE_BUDGET_CHARS,
        preview_chars: int = DEFAULT_PREVIEW_CHARS,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._session_id = session_id
        self._persist_threshold = persist_threshold
        self._per_message_budget = per_message_budget
        self._preview_chars = preview_chars

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Persist large single-tool results to disk after execution."""
        result = await handler(request)

        if isinstance(result, ToolMessage):
            content = str(result.content or "")
            if is_persisted_content(content):
                return result
            if len(content) <= self._persist_threshold:
                return result
            return maybe_persist_tool_result(
                result,
                self._session_id,
                Path(self._workspace_root),
                self._persist_threshold,
                self._preview_chars,
            )

        if isinstance(result, Command):
            update = result.update
            if isinstance(update, dict):
                messages = update.get("messages")
                if isinstance(messages, list):
                    patched: list[Any] = []
                    changed = False
                    for msg in messages:
                        if isinstance(msg, ToolMessage):
                            content = str(msg.content or "")
                            if (
                                not is_persisted_content(content)
                                and len(content) > self._persist_threshold
                            ):
                                msg = maybe_persist_tool_result(
                                    msg,
                                    self._session_id,
                                    Path(self._workspace_root),
                                    self._persist_threshold,
                                    self._preview_chars,
                                )
                                changed = True
                        patched.append(msg)
                    if changed:
                        return Command(update={**update, "messages": patched})
        return result

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Enforce per-message aggregate budget on tool results."""
        messages = list(getattr(request, "messages", None) or [])
        if not messages:
            return await handler(request)

        candidates: list[tuple[int, ToolMessage, int]] = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                content = str(msg.content or "")
                if is_persisted_content(content):
                    continue
                size = len(content)
                if size > self._persist_threshold:
                    candidates.append((i, msg, size))

        if not candidates:
            return await handler(request)

        total_size = sum(size for _, _, size in candidates)
        if total_size <= self._per_message_budget:
            return await handler(request)

        candidates.sort(key=lambda x: x[2], reverse=True)

        patched = list(messages)
        changed = False
        for idx, msg, size in candidates:
            if total_size <= self._per_message_budget:
                break
            persisted = maybe_persist_tool_result(
                msg,
                self._session_id,
                Path(self._workspace_root),
                self._persist_threshold,
                self._preview_chars,
            )
            if persisted is not msg:
                patched[idx] = persisted
                new_size = len(str(persisted.content or ""))
                total_size -= size - new_size
                changed = True

        if changed:
            request = request.override(messages=patched)
        return await handler(request)


# ---------------------------------------------------------------------------
# Evict-to-stub middleware
# ---------------------------------------------------------------------------


class ToolResultEvictionMiddleware(AgentMiddleware):
    """Evict old tool results from context to prevent re-read churn.

    Replaces ToolMessage.content for old evictable tool results with a
    compact stub when total tool-result token estimate exceeds a threshold.
    Runs in ``awrap_model_call`` so the eviction is visible to the model
    on the next hop without persisting to checkpoint.
    """

    name = "ToolResultEvictionMiddleware"

    def __init__(
        self,
        *,
        config: ToolResultEvictionConfig | None = None,
        max_tokens: int | None = None,
        protect_recent: int | None = None,
    ) -> None:
        super().__init__()
        if config is not None:
            self._max_tokens = config.max_tokens
            self._protect_recent = config.protect_recent
        else:
            from soothe_nano.config.constants import (
                DEFAULT_TOOL_RESULT_EVICTION_MAX_TOKENS,
                DEFAULT_TOOL_RESULT_EVICTION_PROTECT_RECENT,
            )

            self._max_tokens = max_tokens or DEFAULT_TOOL_RESULT_EVICTION_MAX_TOKENS
            self._protect_recent = protect_recent or DEFAULT_TOOL_RESULT_EVICTION_PROTECT_RECENT
        self._evicted_ids: set[str] = set()

    def _estimate_tokens(self, content: Any) -> int:
        """Estimate token count from content (string or list of blocks)."""
        if isinstance(content, str):
            return len(content) // _CHARS_PER_TOKEN
        if isinstance(content, list):
            total = 0
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", ""))) // _CHARS_PER_TOKEN
                elif isinstance(block, str):
                    total += len(block) // _CHARS_PER_TOKEN
            return total
        return len(str(content)) // _CHARS_PER_TOKEN

    def _effective_messages(self, request: Any) -> list[Any]:
        """Extract the message list from a model request."""
        messages = getattr(request, "messages", None)
        if messages is None:
            messages = getattr(request, "input", None)
        if messages is None:
            return []
        return list(messages)

    def _estimate_tool_result_tokens(self, messages: list[Any]) -> int:
        """Sum token estimates for all ToolMessages in the list."""
        total = 0
        for msg in messages:
            if isinstance(msg, ToolMessage):
                total += self._estimate_tokens(msg.content)
        return total

    def _find_evictable(self, messages: list[Any]) -> list[tuple[int, ToolMessage]]:
        """Find evictable ToolMessages, oldest first, skipping protected recent."""
        tool_msg_indices: list[tuple[int, ToolMessage]] = []
        for i, msg in enumerate(messages):
            if not isinstance(msg, ToolMessage):
                continue
            if msg.name not in EVICTABLE_TOOLS:
                continue
            if msg.name in NON_EVICTABLE_TOOLS:
                continue
            if msg.tool_call_id in self._evicted_ids:
                continue
            tool_msg_indices.append((i, msg))

        if not tool_msg_indices:
            return []

        cutoff = len(tool_msg_indices) - self._protect_recent
        if cutoff <= 0:
            return []
        return tool_msg_indices[:cutoff]

    def _build_stub(self, msg: ToolMessage) -> str:
        """Build a compact stub replacing evicted content."""
        self._evicted_ids.add(msg.tool_call_id)
        return f"[Evicted: {msg.name}(tool_call_id={msg.tool_call_id}) — re-invoke if needed]"

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Evict old tool results before the model sees them."""
        messages = self._effective_messages(request)
        if not messages:
            return await handler(request)

        tool_result_tokens = self._estimate_tool_result_tokens(messages)
        if tool_result_tokens <= self._max_tokens:
            return await handler(request)

        evictable = self._find_evictable(messages)
        if not evictable:
            return await handler(request)

        patched = list(messages)
        changed = False
        for idx, msg in evictable:
            if tool_result_tokens <= self._max_tokens:
                break
            evicted_tokens = self._estimate_tokens(msg.content)
            stub = self._build_stub(msg)
            patched[idx] = msg.model_copy(update={"content": stub})
            tool_result_tokens -= evicted_tokens
            changed = True

        if changed:
            request = request.override(messages=patched)
        return await handler(request)

    def _time_since_last_assistant(self, messages: list[Any]) -> float:
        """Return minutes since the last AIMessage (placeholder, IG-778 A.3.3)."""
        del messages  # unused for now
        return 0.0


__all__ = [
    "DEFAULT_PER_MESSAGE_BUDGET_CHARS",
    "DEFAULT_PERSIST_THRESHOLD_CHARS",
    "DEFAULT_PREVIEW_CHARS",
    "EVICTABLE_TOOLS",
    "NON_EVICTABLE_TOOLS",
    "PERSISTED_OUTPUT_CLOSING_TAG",
    "PERSISTED_OUTPUT_TAG",
    "ToolResultEvictionMiddleware",
    "ToolResultStorageMiddleware",
    "build_persisted_output_message",
    "is_persisted_content",
    "maybe_persist_tool_result",
    "persist_tool_result",
]
