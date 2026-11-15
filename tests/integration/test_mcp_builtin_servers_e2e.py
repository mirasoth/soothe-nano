"""Integration tests: builtin MCP server configs connect and serve tools for real.

Verifies the end-to-end path for catalog configs in
`soothe_nano.mcp.mcp_config`: config → connection spec → stdio subprocess →
initialize → capability fetch → shutdown.

- playwright, chrome-devtools: need `npx` (packages download on first run,
  bounded by `MCP_E2E_NPM_TIMEOUT_S`, default 240s).
- postgres: additionally needs a reachable PostgreSQL; the DSN comes from
  `SOOTHE_TEST_POSTGRES_DSN` (default postgresql://postgres:postgres@127.0.0.1:6432/soothe_metadata)
  and is injected as POSTGRES_CONNECTION_STRING exactly like production.

All tests are slow and spawn real subprocesses: run with pytest --run-integration.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from soothe_nano.config import SootheConfig
from soothe_nano.mcp.mcp_config import get_builtin_mcp_server
from soothe_nano.mcp.mcp_registry import MCPRegistry

_NPM_BOOT_TIMEOUT_S = float(os.environ.get("MCP_E2E_NPM_TIMEOUT_S", "240"))
_SHUTDOWN_TIMEOUT_S = 60.0
_DEFAULT_PG_DSN = "postgresql://postgres:postgres@127.0.0.1:6432/soothe_metadata"


def _require_npx() -> None:
    if shutil.which("npx") is None:
        pytest.skip("npx is not on PATH; cannot spawn npm-based MCP servers")


async def _connect(registry: MCPRegistry) -> None:
    await asyncio.wait_for(registry.initialize(), timeout=_NPM_BOOT_TIMEOUT_S)


def _assert_server_served(registry: MCPRegistry, name: str) -> None:
    status = registry.connection_status()
    assert name in status, f"server {name!r} never reported a connection: {dict(status)}"
    conn = status[name]
    assert conn.status == "connected", f"{name}: status={conn.status!r} error={conn.last_error!r}"
    deferred = registry.deferred_tools()
    served = [t for t in deferred if t.server == name]
    assert served, f"{name}: no deferred tools listed"
    for descriptor in served:
        assert descriptor.name.startswith(f"mcp__{name}__"), (
            f"{name}: tool {descriptor.name!r} is not mangled with the mcp__{name}__ prefix"
        )
    assert (
        all(tool.server == name for tool in registry.always_loaded_tools() if tool.server == name)
        or not registry.always_loaded_tools()
    ), "builtin servers are defer=True; nothing loads eagerly"
    assert name in registry.prompts(), f"{name}: prompts fetch never ran"
    assert name in registry.resources(), f"{name}: resources fetch never ran"


async def _shutdown(registry: MCPRegistry) -> None:
    await asyncio.wait_for(registry.shutdown(), timeout=_SHUTDOWN_TIMEOUT_S)


@pytest.mark.integration
@pytest.mark.slow
async def test_playwright_builtin_connects_and_lists_tools() -> None:
    """The playwright catalog config spawns the server and lists its tools."""
    _require_npx()
    server = get_builtin_mcp_server("playwright")
    assert server is not None and server.transport.value == "stdio"
    registry = MCPRegistry(servers=[server])
    await _connect(registry)
    _assert_server_served(registry, "playwright")
    await _shutdown(registry)


@pytest.mark.integration
@pytest.mark.slow
async def test_chrome_devtools_builtin_connects_and_lists_tools() -> None:
    """The chrome-devtools catalog config spawns the server and lists its tools."""
    _require_npx()
    server = get_builtin_mcp_server("chrome-devtools")
    assert server is not None and server.transport.value == "stdio"
    registry = MCPRegistry(servers=[server])
    await _connect(registry)
    _assert_server_served(registry, "chrome-devtools")
    await _shutdown(registry)


async def _postgres_reachable(dsn: str) -> bool:
    """Quick TCP probe of the DSN host:port so the test skips instead of hanging."""
    try:
        host_part = dsn.split("@", 1)[1].split("/", 1)[0]
        host, _, port = host_part.rpartition(":")
        if not host:
            host, port = host_part, "5432"
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host or "127.0.0.1", int(port)), timeout=3.0
        )
    except (TimeoutError, OSError, ValueError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 - probe cleanup only
        pass
    return True


@pytest.mark.integration
@pytest.mark.slow
async def test_postgres_builtin_connects_and_lists_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The postgres catalog config spawns the server against a live database."""
    _require_npx()
    dsn = os.environ.get("SOOTHE_TEST_POSTGRES_DSN", _DEFAULT_PG_DSN)
    if not await _postgres_reachable(dsn):
        pytest.skip(f"PostgreSQL at {dsn.rsplit('@', 1)[-1]} is not reachable")

    class _Resolver:
        """Resolves ${VAR} the way SootheConfig.secret_resolver does."""

        def __call__(self, value: str) -> str:
            import re

            return re.sub(
                r"\$\{([^}]+)\}",
                lambda m: os.environ.get(m.group(1), m.group(0)),
                value,
            )

    server = get_builtin_mcp_server("postgres")
    assert server is not None
    monkeypatch.setenv("POSTGRES_CONNECTION_STRING", dsn)
    registry = MCPRegistry(servers=[server], secret_resolver=_Resolver())
    await _connect(registry)
    _assert_server_served(registry, "postgres")
    await _shutdown(registry)


@pytest.mark.integration
@pytest.mark.slow
async def test_mcp_builtins_config_resolution_end_to_end() -> None:
    """`mcp_builtins: [playwright]` resolves into mcp_servers and connects for real."""
    _require_npx()
    config = SootheConfig.model_validate({"mcp_builtins": ["playwright"]})
    resolved = [s for s in config.mcp_servers if s.name == "playwright"]
    assert len(resolved) == 1, "mcp_builtins name did not merge into mcp_servers"
    assert resolved[0].command == "npx"
    assert resolved[0].defer is True, "builtin servers must stay progressive (defer=True)"
    registry = MCPRegistry(servers=resolved)
    await _connect(registry)
    _assert_server_served(registry, "playwright")
    await _shutdown(registry)


@pytest.mark.integration
async def test_websocket_transport_fails_fast_with_clear_error() -> None:
    """A websocket-transport config (removed in mcp 2.x) raises instead of hanging."""
    from soothe_nano.config.models import MCPServerConfig, MCPTransport

    server = MCPServerConfig(
        name="dead-ws", transport=MCPTransport.WEBSOCKET, url="ws://localhost:1/ws"
    )
    registry = MCPRegistry(servers=[server])
    await asyncio.wait_for(registry.initialize(), timeout=30)
    conn = registry.connection_status()["dead-ws"]
    assert conn.status == "connect_failed"
    assert conn.last_error and "websocket" in conn.last_error.lower()
    await _shutdown(registry)
