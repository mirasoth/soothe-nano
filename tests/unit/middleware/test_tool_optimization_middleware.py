"""Tests for deterministic tool optimization middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe_nano.middleware.tool_optimization_middleware import ToolOptimizationMiddleware


def test_main_stack_mounts_tool_optimization_middleware() -> None:
    from soothe_nano.config.settings import SootheConfig
    from soothe_nano.middleware._builder import build_soothe_middleware_stack

    names = [type(m).__name__ for m in build_soothe_middleware_stack(SootheConfig(), policy=None)]
    assert "ToolOptimizationMiddleware" in names


def test_tool_optimization_wraps_edit_coalescing() -> None:
    """Optimization middleware should run before coalescing interception."""
    from soothe_nano.config.settings import SootheConfig
    from soothe_nano.middleware._builder import build_soothe_middleware_stack

    names = [type(m).__name__ for m in build_soothe_middleware_stack(SootheConfig(), policy=None)]
    opt_idx = names.index("ToolOptimizationMiddleware")
    coalesce_idx = names.index("EditCoalescingMiddleware")
    assert opt_idx < coalesce_idx


@pytest.mark.asyncio
async def test_lookup_tools_reuse_identical_args_within_scope() -> None:
    middleware = ToolOptimizationMiddleware()
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t1", "checkpoint_ns": "execute:1"}}
    request = ToolCallRequest(
        tool_call={
            "name": "grep",
            "args": {"pattern": "tool_prefix", "path": "/repo/pkg"},
            "id": "functions.grep:1",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    handler = AsyncMock(
        return_value=ToolMessage(content="packages/x.py:\n  0:", tool_call_id="functions.grep:1")
    )

    first = await middleware.awrap_tool_call(request, handler)
    request_second = ToolCallRequest(
        tool_call={**request.tool_call, "id": "functions.grep:2"},
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    second = await middleware.awrap_tool_call(request_second, handler)

    assert isinstance(first, ToolMessage)
    assert isinstance(second, ToolMessage)
    assert first.content == second.content
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_lookup_reuse_cache_invalidates_after_mutation() -> None:
    middleware = ToolOptimizationMiddleware()
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t2", "checkpoint_ns": "execute:2"}}
    grep_request = ToolCallRequest(
        tool_call={
            "name": "grep",
            "args": {"pattern": "foo", "path": "/repo/file.py"},
            "id": "functions.grep:10",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    edit_request = ToolCallRequest(
        tool_call={
            "name": "edit_file",
            "args": {"file_path": "/repo/file.py", "old_string": "a", "new_string": "b"},
            "id": "functions.edit_file:11",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    grep_handler = AsyncMock(
        return_value=ToolMessage(content="packages/x.py:\n12:foo", tool_call_id="functions.grep:10")
    )
    edit_handler = AsyncMock(
        return_value=ToolMessage(content="ok", tool_call_id="functions.edit_file:11")
    )

    await middleware.awrap_tool_call(grep_request, grep_handler)
    await middleware.awrap_tool_call(edit_request, edit_handler)
    grep_request_second = ToolCallRequest(
        tool_call={**grep_request.tool_call, "id": "functions.grep:12"},
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    await middleware.awrap_tool_call(grep_request_second, grep_handler)

    assert grep_handler.await_count == 2


@pytest.mark.asyncio
async def test_lookup_reuse_cache_is_scoped_by_checkpoint_namespace() -> None:
    middleware = ToolOptimizationMiddleware()
    runtime = MagicMock()
    grep_handler = AsyncMock(
        return_value=ToolMessage(content="packages/x.py:\n12:foo", tool_call_id="functions.grep:20")
    )

    request_ns1 = ToolCallRequest(
        tool_call={
            "name": "grep",
            "args": {"pattern": "foo", "path": "/repo"},
            "id": "functions.grep:20",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    runtime.config = {"configurable": {"thread_id": "t3", "checkpoint_ns": "execute:scope-1"}}
    await middleware.awrap_tool_call(request_ns1, grep_handler)

    request_ns2 = ToolCallRequest(
        tool_call={**request_ns1.tool_call, "id": "functions.grep:21"},
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    runtime.config = {"configurable": {"thread_id": "t3", "checkpoint_ns": "execute:scope-2"}}
    await middleware.awrap_tool_call(request_ns2, grep_handler)

    assert grep_handler.await_count == 2


@pytest.mark.asyncio
async def test_duplicate_empty_lookup_returns_guidance_instead_of_repeating() -> None:
    middleware = ToolOptimizationMiddleware()
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t4", "checkpoint_ns": "execute:4"}}
    request = ToolCallRequest(
        tool_call={
            "name": "grep",
            "args": {"pattern": "missing_symbol", "path": "/repo"},
            "id": "functions.grep:30",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    handler = AsyncMock(
        return_value=ToolMessage(content="[]", tool_call_id="functions.grep:30", name="grep")
    )

    first = await middleware.awrap_tool_call(request, handler)
    second = await middleware.awrap_tool_call(
        ToolCallRequest(
            tool_call={**request.tool_call, "id": "functions.grep:31"},
            tool=None,
            state={"messages": []},
            runtime=runtime,
        ),
        handler,
    )

    assert isinstance(first, ToolMessage)
    assert isinstance(second, ToolMessage)
    assert handler.await_count == 1
    assert getattr(second, "status", None) == "error"
    assert "Duplicate lookup blocked" in str(second.content)


@pytest.mark.asyncio
async def test_shell_search_fallback_blocked_after_native_search() -> None:
    middleware = ToolOptimizationMiddleware()
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t5", "checkpoint_ns": "execute:5"}}

    grep_request = ToolCallRequest(
        tool_call={
            "name": "grep",
            "args": {"pattern": "docker-compose", "path": "/repo"},
            "id": "functions.grep:40",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    grep_handler = AsyncMock(
        return_value=ToolMessage(
            content="/repo/Makefile:10: docker-compose",
            tool_call_id="functions.grep:40",
            name="grep",
        )
    )
    await middleware.awrap_tool_call(grep_request, grep_handler)

    run_request = ToolCallRequest(
        tool_call={
            "name": "run_command",
            "args": {"command": "grep -rn docker-compose /repo"},
            "id": "functions.run_command:41",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    run_handler = AsyncMock(
        return_value=ToolMessage(content="should not run", tool_call_id="functions.run_command:41")
    )
    run_result = await middleware.awrap_tool_call(run_request, run_handler)

    assert isinstance(run_result, ToolMessage)
    assert getattr(run_result, "status", None) == "error"
    assert "Search consolidation" in str(run_result.content)
    run_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_write_todos_short_circuited() -> None:
    from soothe_nano.middleware.tool_optimization_middleware import (
        get_tool_reuse_metrics_snapshot,
    )

    middleware = ToolOptimizationMiddleware()
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t6", "checkpoint_ns": "execute:6"}}
    request = ToolCallRequest(
        tool_call={
            "name": "write_todos",
            "args": {"todos": []},
            "id": "functions.write_todos:1",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    handler = AsyncMock(
        return_value=ToolMessage(content="should not run", tool_call_id="functions.write_todos:1")
    )

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert "Todo list unchanged" in str(result.content)
    handler.assert_not_awaited()
    assert get_tool_reuse_metrics_snapshot()["empty_write_todos_short_circuited"] >= 1


@pytest.mark.asyncio
async def test_read_file_thrash_guidance_after_consecutive_slices() -> None:
    from soothe_nano.middleware.tool_optimization_middleware import (
        get_tool_reuse_metrics_snapshot,
    )

    middleware = ToolOptimizationMiddleware()
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t7", "checkpoint_ns": "execute:7"}}

    async def _handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=f"slice:{req.tool_call['args']['offset']}",
            tool_call_id=req.tool_call["id"],
            name="read_file",
        )

    handler = AsyncMock(side_effect=_handler)
    call_count = {"n": 0}

    async def _read(offset: int, call_id: str) -> ToolMessage:
        call_count["n"] += 1
        request = ToolCallRequest(
            tool_call={
                "name": "read_file",
                "args": {
                    "file_path": "/repo/planner.py",
                    "offset": offset,
                    "limit": 20,
                },
                "id": call_id,
            },
            tool=None,
            state={"messages": []},
            runtime=runtime,
        )
        result = await middleware.awrap_tool_call(request, handler)
        assert isinstance(result, ToolMessage)
        return result

    first = await _read(0, "functions.read_file:1")
    second = await _read(20, "functions.read_file:2")
    third = await _read(40, "functions.read_file:3")

    assert "slice:0" in str(first.content)
    assert "slice:20" in str(second.content)
    assert getattr(third, "status", None) == "error"
    assert "Read thrash guidance" in str(third.content)
    assert handler.await_count == 2
    assert get_tool_reuse_metrics_snapshot()["read_file_thrash_guided"] >= 1

    # After guidance, a subsequent wider read (different args) is allowed.
    wider_request = ToolCallRequest(
        tool_call={
            "name": "read_file",
            "args": {
                "file_path": "/repo/planner.py",
                "offset": 0,
                "limit": 200,
            },
            "id": "functions.read_file:4",
        },
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )
    wider = await middleware.awrap_tool_call(wider_request, handler)
    assert isinstance(wider, ToolMessage)
    assert "Read thrash" not in str(wider.content)
    assert handler.await_count == 3
