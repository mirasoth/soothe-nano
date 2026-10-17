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

from soothe_nano.middleware._scope import request_scope_id

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
        # Per-scope (thread_id:checkpoint_ns) pending state: concurrent graph
        # threads share this middleware instance and must not co-mingle reads.
        self._pending_reads: dict[str, list[PendingRead]] = {}
        self._window_tasks: dict[str, asyncio.Task[None]] = {}
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

        scope = request_scope_id(request)
        async with self._lock:
            pending = self._pending_reads.setdefault(scope, [])
            pending_read = PendingRead(
                request=request,
                handler=handler,
                tool_call_id=tool_call_id,
            )
            pending.append(pending_read)
            task = self._window_tasks.get(scope)
            if task is None or task.done():
                self._window_tasks[scope] = asyncio.create_task(self._flush_after_window(scope))

        return await pending_read.result_future

    async def _flush_after_window(self, scope: str) -> None:
        """Wait for the detection window, then flush pending reads.

        Fast path: after one event-loop tick, if no sibling read has joined
        the window, skip the full wait — batching cannot help a singleton.
        """
        await asyncio.sleep(0)
        async with self._lock:
            solo = len(self._pending_reads.get(scope, [])) == 1
        if not solo:
            await asyncio.sleep(self._detection_window_ms / 1000.0)
        await self._flush_pending_reads(scope)

    async def _flush_pending_reads(self, scope: str) -> None:
        """Execute all pending reads concurrently and resolve futures."""
        async with self._lock:
            pending = self._pending_reads.pop(scope, [])
            self._window_tasks.pop(scope, None)

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
                    read.result_future.set_result(cast("ToolMessage | Command[Any]", result))
