"""Coalesce parallel read_file calls into concurrent execution.

Collects read_file tool calls within a detection window, executes
them concurrently, and returns per-call ToolMessage results. This
reduces execution time (concurrent I/O vs sequential) and middleware
overhead (one detection-window cycle vs N).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe_nano.middleware._scope import request_scope_id
from soothe_nano.middleware._window import ScopeWindowBank, resolve_pending_results

logger = logging.getLogger(__name__)


@dataclass
class PendingRead:
    """A pending read_file call awaiting coalesced execution."""

    request: ToolCallRequest
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    tool_call_id: str
    result_future: asyncio.Future[ToolMessage | Command[Any]] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )


class ReadCoalescingMiddleware(AgentMiddleware):
    """Coalesce parallel read_file calls into concurrent execution.

    Collects read_file tool calls within a detection window, executes
    them concurrently via ``asyncio.gather``, and returns per-call
    ``ToolMessage`` results (the model expects per-``tool_call_id`` responses).
    """

    name = "ReadCoalescingMiddleware"

    READ_TOOL_NAME = "read_file"
    DEFAULT_DETECTION_WINDOW_MS = 50

    def __init__(self, *, detection_window_ms: int = 50) -> None:
        super().__init__()
        self._detection_window_ms = detection_window_ms
        self._bank: ScopeWindowBank[PendingRead] = ScopeWindowBank(
            detection_window_ms / 1000.0,
            on_flush=self._flush_reads,
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Collect read_file calls within a detection window for concurrent execution.

        Args:
            request: Tool call request.
            handler: Next handler in the middleware chain.

        Returns:
            ToolMessage or Command result from the (possibly coalesced) execution.
        """
        tool_call = getattr(request, "tool_call", None)
        tool_name = getattr(tool_call, "name", None) if tool_call else None
        tool_call_id = getattr(tool_call, "id", "") if tool_call else ""

        if tool_name != self.READ_TOOL_NAME:
            return await handler(request)

        pending_read = PendingRead(
            request=request,
            handler=handler,
            tool_call_id=tool_call_id,
        )
        await self._bank.enqueue(pending_read, request_scope_id(request))
        return await pending_read.result_future

    async def _flush_reads(self, scope: str, pending: list[PendingRead]) -> None:
        """Execute all pending reads concurrently and resolve futures."""
        await resolve_pending_results(pending)
