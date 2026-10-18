"""Tests for the shared scope detection-window bank."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from soothe_nano.middleware._window import ScopeWindowBank, resolve_pending_results


class _Item:
    """Minimal pending-call duck type."""

    def __init__(self, handler: Any) -> None:
        self.request = object()
        self.handler = handler
        self.result_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()


async def _ok_handler(request: Any) -> str:
    return "ok"


@pytest.mark.asyncio
async def test_solo_item_flushes_without_window_wait() -> None:
    """A lone item flushes after one event-loop tick (no window sleep)."""
    flushed: list[list[_Item]] = []

    async def on_flush(scope: str, pending: list[_Item]) -> None:
        flushed.append(pending)
        await resolve_pending_results(pending)

    bank = ScopeWindowBank[_Item](60.0, on_flush=on_flush)
    item = _Item(_ok_handler)
    await bank.enqueue(item, "scope-a")
    # One tick is enough — must not wait the 60s window for a singleton.
    await asyncio.wait_for(item.result_future, timeout=1.0)
    assert flushed and len(flushed[0]) == 1


@pytest.mark.asyncio
async def test_failed_flush_resolves_pending_futures() -> None:
    """A flush callback exception must not leave pending futures hanging."""

    async def bad_flush(scope: str, pending: list[_Item]) -> None:
        raise RuntimeError("boom")

    # Tiny window: two items mean the full detection window applies.
    bank = ScopeWindowBank[_Item](0.05, on_flush=bad_flush)
    items = [_Item(_ok_handler), _Item(_ok_handler)]
    for item in items:
        await bank.enqueue(item, "scope-a")
    results = await asyncio.gather(
        *[asyncio.wait_for(i.result_future, timeout=2.0) for i in items],
        return_exceptions=True,
    )
    assert all(isinstance(r, RuntimeError) for r in results)


@pytest.mark.asyncio
async def test_resolve_pending_results_singleton_and_batch() -> None:
    """Singleton executes directly; batches run concurrently and resolve all."""

    async def slow_handler(request: Any) -> str:
        await asyncio.sleep(0.01)
        return "slow"

    solo = _Item(slow_handler)
    await resolve_pending_results([solo])
    assert solo.result_future.result() == "slow"

    batch = [_Item(slow_handler), _Item(slow_handler)]
    await resolve_pending_results(batch)
    assert all(i.result_future.result() == "slow" for i in batch)


@pytest.mark.asyncio
async def test_resolve_pending_results_captures_handler_errors() -> None:
    """Handler exceptions resolve the future instead of escaping the flush."""

    async def bad_handler(request: Any) -> str:
        raise ValueError("nope")

    item = _Item(bad_handler)
    await resolve_pending_results([item])
    with pytest.raises(ValueError, match="nope"):
        item.result_future.result()
