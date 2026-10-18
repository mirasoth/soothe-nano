"""Capture tool-call kwargs at invocation time (provider `tool_call_id`).

LangGraph may stream only `ToolMessage` results without preceding `AIMessage` tool
metadata (e.g. some fast-model paths). The registry records args from
`ToolCallRequest` in middleware before tools run so downstream stream code can
attach them to unified wire ids. `ToolCallArgsMiddleware` is the lightweight
recorder; optimization logic is owned by `ToolOptimizationMiddleware`.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_registry: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "tool_call_args_registry",
    default=None,
)


def coerce_tool_call_args(raw: Any) -> dict[str, Any]:
    """Normalize tool-call `args` from a request or wire payload."""
    if isinstance(raw, dict):
        inp = raw.get("input")
        if isinstance(inp, dict) and inp:
            return dict(inp)
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def init_tool_call_args_registry() -> None:
    """Reset the per-thread invocation registry (call at execute-wave start)."""
    _registry.set({})


def record_tool_call_args_from_request(request: ToolCallRequest) -> None:
    """Store kwargs from an in-flight tool invocation keyed by provider `tool_call_id`."""
    store = _registry.get()
    if store is None:
        return
    tc = getattr(request, "tool_call", None)
    if not isinstance(tc, dict):
        return
    tid = str(tc.get("id") or "").strip()
    args = coerce_tool_call_args(tc.get("args"))
    if tid and args:
        store[tid] = dict(args)


def get_recorded_tool_call_args(tool_call_id: str) -> dict[str, Any]:
    """Return kwargs recorded at invocation for a provider `tool_call_id`."""
    store = _registry.get()
    if store is None:
        return {}
    key = str(tool_call_id or "").strip()
    if not key:
        return {}
    stored = store.get(key)
    return dict(stored) if isinstance(stored, dict) else {}


class ToolCallArgsMiddleware(AgentMiddleware):
    """Record tool-call kwargs at invocation time for display purposes.

    Captures kwargs from each ``ToolCallRequest`` so downstream stream code
    can attach them to unified wire ids (subagent display). Batched
    operations are skipped. Must wrap ``EditCoalescingMiddleware`` (outer):
    coalescing intercepts edit tools without calling inner handlers.

    Example:
        mw = ToolCallArgsMiddleware()
    """

    name = "ToolCallArgsMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Record tool call args before execution."""
        # Fast path: skip recording for batched operations
        metadata = getattr(request, "metadata", None) or {}
        if metadata.get("_batched"):
            return await handler(request)

        record_tool_call_args_from_request(request)
        return await handler(request)


__all__ = [
    "ToolCallArgsMiddleware",
    "coerce_tool_call_args",
    "get_recorded_tool_call_args",
    "init_tool_call_args_registry",
    "record_tool_call_args_from_request",
]
