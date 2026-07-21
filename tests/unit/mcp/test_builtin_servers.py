"""Unit tests for builtin MCP server catalog."""

import pytest

from soothe_nano.config import SootheConfig
from soothe_nano.mcp.mcp_config import (
    builtin_mcp_server_names,
    get_builtin_mcp_server,
    get_builtin_mcp_servers,
    resolve_mcp_builtins,
)


def test_builtin_catalog_includes_daily_use_servers() -> None:
    names = builtin_mcp_server_names()
    assert {"playwright", "github", "slack", "postgres", "gdrive"}.issubset(names)


def test_all_builtins_are_deferred() -> None:
    for server in get_builtin_mcp_servers():
        assert server.defer is True


def test_resolve_mcp_builtins_returns_copies() -> None:
    resolved = resolve_mcp_builtins(["github", "playwright"])
    assert len(resolved) == 2
    assert {s.name for s in resolved} == {"github", "playwright"}
    assert resolved[0] is not get_builtin_mcp_server("github")


def test_resolve_unknown_builtin_raises() -> None:
    with pytest.raises(ValueError, match="Unknown mcp_builtins"):
        resolve_mcp_builtins(["not-a-server"])


def test_mcp_builtins_merges_into_soothe_config() -> None:
    cfg = SootheConfig(mcp_builtins=["slack", "postgres"])
    assert len(cfg.mcp_servers) == 2
    assert {s.name for s in cfg.mcp_servers} == {"slack", "postgres"}
    assert all(s.defer for s in cfg.mcp_servers)


def test_mcp_builtins_empty_does_not_connect_servers() -> None:
    cfg = SootheConfig()
    assert cfg.mcp_builtins == []
    assert cfg.mcp_servers == []


def test_mcp_builtins_skips_duplicate_explicit_server() -> None:
    from soothe_nano.config.models import MCPServerConfig

    explicit = MCPServerConfig(name="github", command="echo", args=[])
    cfg = SootheConfig(mcp_servers=[explicit], mcp_builtins=["github", "playwright"])
    assert len(cfg.mcp_servers) == 2
    assert cfg.mcp_servers[0].command == "echo"


def test_register_builtin_mcp_server_extends_catalog() -> None:
    from soothe_nano.config.models import MCPServerConfig, MCPTransport
    from soothe_nano.mcp.mcp_config import (
        builtin_mcp_server_names,
        register_builtin_mcp_server,
        resolve_mcp_builtins,
    )

    unregister = register_builtin_mcp_server(
        MCPServerConfig(
            name="fj-test-mcp",
            command="echo",
            args=["hello"],
            transport=MCPTransport.STDIO,
            defer=True,
        )
    )
    try:
        assert "fj-test-mcp" in builtin_mcp_server_names()
        resolved = resolve_mcp_builtins(["fj-test-mcp"])
        assert len(resolved) == 1
        assert resolved[0].name == "fj-test-mcp"
        assert resolved[0].command == "echo"

        cfg = SootheConfig(mcp_builtins=["fj-test-mcp"])
        assert any(s.name == "fj-test-mcp" for s in cfg.mcp_servers)
    finally:
        unregister()

    assert "fj-test-mcp" not in builtin_mcp_server_names()
    with pytest.raises(ValueError, match="Unknown mcp_builtins"):
        resolve_mcp_builtins(["fj-test-mcp"])


def test_register_builtin_mcp_duplicate_raises() -> None:
    from soothe_nano.config.models import MCPServerConfig, MCPTransport
    from soothe_nano.mcp.mcp_config import register_builtin_mcp_server

    cfg = MCPServerConfig(
        name="fj-dup-mcp",
        command="echo",
        args=[],
        transport=MCPTransport.STDIO,
    )
    unregister = register_builtin_mcp_server(cfg)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_builtin_mcp_server(cfg)
        with pytest.raises(ValueError, match="conflicts with nano builtin"):
            register_builtin_mcp_server(
                MCPServerConfig(name="github", command="echo", args=[]),
            )
    finally:
        unregister()


def test_register_builtin_mcp_replace() -> None:
    from soothe_nano.config.models import MCPServerConfig, MCPTransport
    from soothe_nano.mcp.mcp_config import get_builtin_mcp_server, register_builtin_mcp_server

    unregister = register_builtin_mcp_server(
        MCPServerConfig(name="fj-replace-mcp", command="v1", args=[], transport=MCPTransport.STDIO)
    )
    try:
        register_builtin_mcp_server(
            MCPServerConfig(
                name="fj-replace-mcp", command="v2", args=[], transport=MCPTransport.STDIO
            ),
            replace=True,
        )
        assert get_builtin_mcp_server("fj-replace-mcp").command == "v2"
    finally:
        unregister()


def test_register_mcp_alone_does_not_connect() -> None:
    from soothe_nano.config.models import MCPServerConfig, MCPTransport
    from soothe_nano.mcp.mcp_config import register_builtin_mcp_server

    unregister = register_builtin_mcp_server(
        MCPServerConfig(name="fj-dark-mcp", command="echo", args=[], transport=MCPTransport.STDIO)
    )
    try:
        cfg = SootheConfig()
        assert cfg.mcp_servers == []
        assert "fj-dark-mcp" not in {s.name for s in cfg.mcp_servers}
    finally:
        unregister()
