"""Evict old tool results from context to prevent re-read churn.

Replaces ToolMessage.content for old evictable tool results with a
compact stub when total tool-result token estimate exceeds a threshold.
Runs in ``awrap_model_call`` so the eviction is visible to the model
on the next hop without persisting to checkpoint.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from soothe_nano.config.models import ToolResultEvictionConfig

logger = logging.getLogger(__name__)

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
            self._protect_recent = (
                protect_recent or DEFAULT_TOOL_RESULT_EVICTION_PROTECT_RECENT
            )
        self._evicted_ids: set[str] = set()

    def _estimate_tokens(self, content: Any) -> int:
        """Estimate token count from content.

        Args:
            content: Message content (string or list of blocks).

        Returns:
            Estimated token count.
        """
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
        """Extract the message list from a model request.

        Args:
            request: Model request (may have ``messages`` or ``input``).

        Returns:
            List of messages.
        """
        messages = getattr(request, "messages", None)
        if messages is None:
            messages = getattr(request, "input", None)
        if messages is None:
            return []
        return list(messages)

    def _estimate_tool_result_tokens(self, messages: list[Any]) -> int:
        """Sum token estimates for all ToolMessages in the list.

        Args:
            messages: List of messages.

        Returns:
            Total estimated tool-result tokens.
        """
        total = 0
        for msg in messages:
            if isinstance(msg, ToolMessage):
                total += self._estimate_tokens(msg.content)
        return total

    def _find_evictable(self, messages: list[Any]) -> list[tuple[int, ToolMessage]]:
        """Find evictable ToolMessages, oldest first, skipping protected recent.

        Args:
            messages: Full message list.

        Returns:
            List of (index, ToolMessage) tuples, oldest first.
        """
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
        """Build a compact stub replacing evicted content.

        Args:
            msg: ToolMessage being evicted.

        Returns:
            Compact stub string preserving tool name and key arguments.
        """
        self._evicted_ids.add(msg.tool_call_id)
        return f"[Evicted: {msg.name}(tool_call_id={msg.tool_call_id}) — re-invoke if needed]"

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Evict old tool results before the model sees them.

        Args:
            request: Model request containing messages.
            handler: Next handler in the middleware chain.

        Returns:
            Model response from handler (with possibly evicted messages).
        """
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
        """Return minutes since the last AIMessage in the list.

        Args:
            messages: Full message list.

        Returns:
            Minutes since last assistant message, or float('inf') if none.
        """
        # Placeholder for future time-based trigger (IG-778 Appendix A.3.3)
        del messages  # unused for now
        return 0.0
