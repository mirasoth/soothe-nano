"""Hint helpers for invalid or hallucinated tool names."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

INVALID_TOOL_ERROR_MARKER = "is not a valid tool"


def is_invalid_tool_error(content: str) -> bool:
    """Return whether *content* is LangGraph's unregistered-tool error."""
    return INVALID_TOOL_ERROR_MARKER in content


def extract_tool_message_content(result: ToolMessage | Command[Any]) -> str | None:
    """Return ToolMessage text from a middleware tool-call result."""
    if isinstance(result, ToolMessage):
        return str(result.content or "")
    if isinstance(result, Command):
        update = result.update
        if not isinstance(update, dict):
            return None
        messages = update.get("messages")
        if not isinstance(messages, list):
            return None
        for msg in messages:
            if isinstance(msg, ToolMessage):
                return str(msg.content or "")
    return None
