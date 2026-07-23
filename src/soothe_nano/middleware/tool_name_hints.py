"""Hint helpers for invalid or hallucinated tool names."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

INVALID_TOOL_ERROR_MARKER = "is not a valid tool"

# Tool names that may embed an operand in the name field (model formatting drift).
_OPERAND_IN_NAME_RE = re.compile(
    r"^(?P<base>ls|read_file|glob|grep|run_command)\s+(?P<operand>.+)$",
    re.IGNORECASE,
)

_ARG_VALUE_ARTIFACT_RE = re.compile(r"``\s*$", re.IGNORECASE)


def is_invalid_tool_error(content: str) -> bool:
    """Return whether *content* is LangGraph's unregistered-tool error."""
    return INVALID_TOOL_ERROR_MARKER in content


def sanitize_hallucinated_tool_name(tool_name: str) -> tuple[str, dict[str, Any]]:
    """Normalize tool names that embed paths or XML artifacts in the name field."""
    raw = (tool_name or "").strip()
    if not raw:
        return raw, {}

    cleaned = _ARG_VALUE_ARTIFACT_RE.sub("", raw).strip()
    match = _OPERAND_IN_NAME_RE.match(cleaned)
    if not match:
        return cleaned, {}

    base = match.group("base").lower()
    operand = match.group("operand").strip().strip("'\"")
    if base == "ls":
        return "ls", {"path": operand}
    if base == "read_file":
        return "read_file", {"file_path": operand}
    if base == "glob":
        return "glob", {"pattern": operand}
    if base == "grep":
        return "grep", {"pattern": operand}
    if base == "run_command":
        return "run_command", {"command": operand}
    return base, {}


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
