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
from typing import TYPE_CHECKING, Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class PendingRead:
    """A pending read_file call awaiting coalesced execution."""

    request: ToolCallRequest
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    tool_call_id: str
    result_future: asyncio.Future[ToolMessage | Command[Any]] = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
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
        self._pending_reads: list[PendingRead] = []
        self._window_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

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

        async with self._lock:
            if self._window_task is None or self._window_task.done():
                # First read in window — start timer and execute immediately
                # if no other reads arrive within the window.
                pending = PendingRead(
                    request=request,
                    handler=handler,
                    tool_call_id=tool_call_id,
                )
                self._pending_reads.append(pending)
                self._window_task = asyncio.create_task(self._flush_after_window())
                result_future = pending.result_future
            else:
                # Additional read within window — add to batch
                pending = PendingRead(
                    request=request,
                    handler=handler,
                    tool_call_id=tool_call_id,
                )
                self._pending_reads.append(pending)
                result_future = pending.result_future

        return await result_future

    async def _flush_after_window(self) -> None:
        """Wait for the detection window, then flush pending reads."""
        await asyncio.sleep(self._detection_window_ms / 1000.0)
        await self._flush_pending_reads()

    async def _flush_pending_reads(self) -> None:
        """Execute all pending reads concurrently and resolve futures."""
        async with self._lock:
            pending = self._pending_reads
            self._pending_reads = []
            self._window_task = None

        if not pending:
            return

        # If only one read, execute directly (no gather overhead)
        if len(pending) == 1:
            p = pending[0]
            try:
                result = await p.handler(p.request)
                if not p.result_future.done():
                    p.result_future.set_result(result)
            except Exception as exc:
                if not p.result_future.done():
                    p.result_future.set_exception(exc)
            return

        # Execute all reads concurrently
        results: list[ToolMessage | Command[Any] | BaseException] = await asyncio.gather(  # type: ignore[assignment]
            *[p.handler(p.request) for p in pending],
            return_exceptions=True,
        )

        for read, result in zip(pending, results, strict=True):  # type: ignore[assignment]
            if isinstance(result, BaseException):
                if not read.result_future.done():
                    read.result_future.set_exception(result)
            else:
                if not read.result_future.done():
                    read.result_future.set_result(
                        cast("ToolMessage | Command[Any]", result)
                    )

