"""Typed WebSocket stream events for tool-call UI.

Supplements LangGraph ``messages`` chunks with explicit tool kwargs so clients
do not depend on fragile LangChain message shape drift across ``model_dump`` /
``tool_call_chunks`` / ``tool_calls``.
"""

from __future__ import annotations

from typing import Any

from soothe_nano._rust_compat import (
    extract_tool_call_updates_from_wire_message_rust,
    unified_tool_update_allowed_without_args_rust,
)

STREAM_TOOL_CALL_UPDATE = "soothe.stream.tool_call.update"
TOOL_CALL_UPDATES_BATCH = "tool_call_updates_batch"


def tool_call_update_event(
    *,
    tool_call_id: str,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Build a ``mode=custom`` payload with complete tool invocation kwargs."""
    return {
        "type": STREAM_TOOL_CALL_UPDATE,
        "tool_call_id": str(tool_call_id).strip(),
        "name": str(name or "").strip() or "tool",
        "args": dict(args or {}),
    }


def unified_tool_update_allowed_without_args(tool_call_id: str) -> bool:
    """True when a wire update may omit kwargs (unified main or subgraph tool rows).

    Step-level ``task`` delegations are excluded; they are ingested via dedicated paths.
    Raw provider ids (non-unified) still require parsed args before batching.
    """
    return unified_tool_update_allowed_without_args_rust(tool_call_id)


def extract_tool_call_updates_from_wire_message(
    msg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract ``soothe.stream.tool_call.update`` payloads from a wire AI message dict."""
    if not isinstance(msg, dict):
        return []
    return extract_tool_call_updates_from_wire_message_rust(msg)


__all__ = [
    "STREAM_TOOL_CALL_UPDATE",
    "TOOL_CALL_UPDATES_BATCH",
    "extract_tool_call_updates_from_wire_message",
    "tool_call_update_event",
    "unified_tool_update_allowed_without_args",
]
