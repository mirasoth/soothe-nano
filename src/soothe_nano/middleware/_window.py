"""Shared per-scope detection-window infrastructure for coalescing middlewares."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Generic, Protocol, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


class PendingCall(Protocol):
    """Duck type shared by coalescer pending items."""

    request: Any
    handler: Callable[[Any], Awaitable[Any]]
    result_future: asyncio.Future[Any]


class ScopeWindowBank(Generic[T]):
    """Per-scope pending queues with one detection-window task per scope.

    The bank owns the lock and window-task lifecycle so coalescers share one
    implementation of: enqueue under lock, fast-flush singletons after one
    event-loop tick, and take-on-flush. Concurrent graph threads share the
    middleware instance, hence the scope key.
    """

    def __init__(
        self,
        window_seconds: float,
        on_flush: Callable[[str, list[T]], Awaitable[None]],
    ) -> None:
        self._window_seconds = window_seconds
        self._on_flush = on_flush
        self._pending: dict[str, list[T]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, item: T, scope: str) -> None:
        """Append item and start the scope's window task if not running."""
        async with self._lock:
            self._pending.setdefault(scope, []).append(item)
            task = self._tasks.get(scope)
            if task is None or task.done():
                self._tasks[scope] = asyncio.create_task(self._run_window(scope))

    async def _run_window(self, scope: str) -> None:
        # Fast path: after one event-loop tick, if no sibling item has joined
        # the window, skip the full wait — batching cannot help a singleton.
        await asyncio.sleep(0)
        async with self._lock:
            solo = len(self._pending.get(scope, [])) == 1
        if not solo:
            await asyncio.sleep(self._window_seconds)
        pending = await self.take(scope)
        try:
            await self._on_flush(scope, pending)
        except Exception:
            # The window task is never awaited directly; an exception here
            # would otherwise silently kill it and hang every future in
            # `pending`. Fail loud and resolve what we can.
            logger.exception("Detection-window flush failed for scope %r", scope)
            for item in pending:
                future = getattr(item, "result_future", None)
                if future is not None and not future.done():
                    future.set_exception(RuntimeError("coalesced batch flush failed; see logs"))

    async def take(self, scope: str) -> list[T]:
        """Pop the scope's pending items (window task, if any, is cleared)."""
        async with self._lock:
            self._tasks.pop(scope, None)
            return self._pending.pop(scope, [])


async def resolve_pending_results(pending: list[Any]) -> None:
    """Execute pending items' handlers and resolve their result futures.

    A singleton executes directly (no gather overhead); the rest run
    concurrently with exception capture.
    """
    if not pending:
        return

    call: Any
    if len(pending) == 1:
        call = pending[0]
        try:
            result = await call.handler(call.request)
        except Exception as exc:
            if not call.result_future.done():
                call.result_future.set_exception(exc)
            return
        if not call.result_future.done():
            call.result_future.set_result(result)
        return

    results = await asyncio.gather(
        *(call.handler(call.request) for call in pending),
        return_exceptions=True,
    )
    for call, result in zip(pending, results, strict=True):
        if isinstance(result, BaseException):
            if not call.result_future.done():
                call.result_future.set_exception(result)
        else:
            if not call.result_future.done():
                call.result_future.set_result(result)


__all__ = ["PendingCall", "ScopeWindowBank", "resolve_pending_results"]
