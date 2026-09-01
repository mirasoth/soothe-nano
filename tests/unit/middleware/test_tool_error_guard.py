"""Tests for ``ToolErrorGuardMiddleware``."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe_nano.middleware.tool_error_guard import ToolErrorGuardMiddleware


def _request(name: str = "kill_process", call_id: str = "call_1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": {"pid": "14449"}, "id": call_id},
        tool=None,
        state={"messages": []},
        runtime=None,
    )


def test_main_stack_mounts_tool_error_guard() -> None:
    """The guard must be in the default stack, outer to NetworkToolErrors."""
    from soothe_nano.config.settings import SootheConfig
    from soothe_nano.middleware._builder import build_soothe_middleware_stack

    names = [type(m).__name__ for m in build_soothe_middleware_stack(SootheConfig(), policy=None)]
    assert "ToolErrorGuardMiddleware" in names
    guard_idx = names.index("ToolErrorGuardMiddleware")
    net_idx = names.index("NetworkToolErrorsMiddleware")
    # Guard wraps the network middleware's re-raised exceptions → outer (later).
    assert guard_idx > net_idx


@pytest.mark.asyncio
async def test_unexpected_exception_becomes_error_tool_message() -> None:
    """A TypeError from a tool must surface as an error ToolMessage."""
    middleware = ToolErrorGuardMiddleware()
    handler = AsyncMock(
        side_effect=TypeError("'<=' not supported between instances of 'str' and 'int'")
    )

    result = await middleware.awrap_tool_call(_request(), handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "call_1"
    assert result.name == "kill_process"
    content = str(result.content)
    assert "TypeError" in content
    assert "kill_process" in content
    # The original message text survives so the agent can correct itself.
    assert "'<=' not supported" in content


@pytest.mark.asyncio
async def test_successful_call_passes_through_unchanged() -> None:
    middleware = ToolErrorGuardMiddleware()
    ok = ToolMessage(content="Process 42 terminated", tool_call_id="call_1", name="kill_process")
    handler = AsyncMock(return_value=ok)

    result = await middleware.awrap_tool_call(_request(), handler)

    assert result is ok


@pytest.mark.asyncio
async def test_cancelled_error_propagates_uncaught() -> None:
    """Cooperative cancellation must not be swallowed into a ToolMessage."""
    middleware = ToolErrorGuardMiddleware()
    handler = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await middleware.awrap_tool_call(_request(), handler)


@pytest.mark.asyncio
async def test_graph_interrupt_propagates_uncaught() -> None:
    """``GraphInterrupt`` must bubble up, not become an error ToolMessage."""
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Interrupt

    middleware = ToolErrorGuardMiddleware()
    interrupt_value = Interrupt(
        value={"type": "ask_user", "questions": []},
        id="test-interrupt-id",
    )
    handler = AsyncMock(side_effect=GraphInterrupt((interrupt_value,)))

    with pytest.raises(GraphInterrupt):
        await middleware.awrap_tool_call(_request(), handler)


@pytest.mark.asyncio
async def test_missing_tool_call_id_does_not_crash() -> None:
    middleware = ToolErrorGuardMiddleware()
    handler = AsyncMock(side_effect=ValueError("boom"))
    request = ToolCallRequest(tool_call={}, tool=None, state={"messages": []}, runtime=None)

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "tool" in str(result.content)


@pytest.mark.asyncio
async def test_error_text_is_truncated() -> None:
    """A huge exception message must be capped for model context safety."""
    middleware = ToolErrorGuardMiddleware()
    huge = "x" * 10_000
    handler = AsyncMock(side_effect=RuntimeError(huge))

    result = await middleware.awrap_tool_call(_request(), handler)

    content = str(result.content)
    assert len(content) <= 2200  # cap + truncation marker
    assert content.endswith("[truncated]")
