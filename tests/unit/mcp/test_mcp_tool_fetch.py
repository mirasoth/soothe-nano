"""Regression tests for MCP tool fetch across langchain-mcp-adapters versions.

Covers both the sync ``get_tools`` (0.2.x) and coroutine-returning
``get_tools`` (0.3.x) code paths in ``fetch_tools_and_descriptors``.
"""

from types import SimpleNamespace

from soothe_nano.config.models import MCPServerConfig
from soothe_nano.mcp.mcp_registry_support import fetch_tools_and_descriptors


def _make_server() -> MCPServerConfig:
    return MCPServerConfig(name="test", command="echo", defer=False)


def _fake_tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=f"desc for {name}")


async def test_sync_get_tools_returns_tools() -> None:
    """0.2.x: client.get_tools returns a list directly."""
    client = SimpleNamespace(get_tools=lambda server_name: [_fake_tool("alpha")])
    server_cfg = _make_server()

    tools, descriptors = await fetch_tools_and_descriptors(
        client, server_name="test", server_cfg=server_cfg
    )

    assert len(tools) == 1
    assert tools[0].name == "mcp__test__alpha"
    assert len(descriptors) == 1
    assert descriptors[0].bare_name == "alpha"
    assert descriptors[0].server == "test"


async def test_coroutine_get_tools_is_awaited() -> None:
    """0.3.x: client.get_tools returns a coroutine that must be awaited.

    Regression for issue #22 — without awaiting, iterating the coroutine
    raised ``'coroutine' object is not iterable`` and zero tools loaded.
    """

    class AsyncGetToolsClient:
        def get_tools(self, *, server_name: str):  # type: ignore[no-untyped-def]
            async def _coro() -> list:
                return [_fake_tool("beta")]

            return _coro()

    client = AsyncGetToolsClient()
    server_cfg = _make_server()

    tools, descriptors = await fetch_tools_and_descriptors(
        client, server_name="test", server_cfg=server_cfg
    )

    assert len(tools) == 1
    assert tools[0].name == "mcp__test__beta"
    assert len(descriptors) == 1
    assert descriptors[0].bare_name == "beta"


async def test_tool_filter_applied() -> None:
    """tool_filter allowlist restricts the returned tools."""
    client = SimpleNamespace(get_tools=lambda server_name: [_fake_tool("keep"), _fake_tool("drop")])
    server_cfg = MCPServerConfig(name="test", command="echo", defer=False, tool_filter=["keep"])

    tools, descriptors = await fetch_tools_and_descriptors(
        client, server_name="test", server_cfg=server_cfg
    )

    assert len(tools) == 1
    assert tools[0].name == "mcp__test__keep"
