"""MCP server diagnose checks."""

from __future__ import annotations

from shutil import which
from typing import Any

from soothe_nano.config.models import MCPTransport
from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)


def _transport_value(transport: Any) -> str:
    if hasattr(transport, "value"):
        return str(transport.value)
    return str(transport)


def _check_mcp_configs(config: Any | None) -> CheckResult:
    """Check MCP server configurations."""
    if config is None:
        return CheckResult(
            name="mcp_configs",
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    mcp_servers = getattr(config, "mcp_servers", None) or []
    if not mcp_servers:
        return CheckResult(
            name="mcp_configs",
            status=CheckStatus.INFO,
            message="No MCP servers configured",
        )

    invalid = []
    for server in mcp_servers:
        if not getattr(server, "name", None):
            invalid.append("server missing name")
            continue
        transport = getattr(server, "transport", MCPTransport.STDIO)
        tval = _transport_value(transport)
        if tval == MCPTransport.STDIO.value:
            if not getattr(server, "command", None):
                invalid.append(f"'{server.name}' missing command for stdio transport")
        elif tval in {
            MCPTransport.SSE.value,
            MCPTransport.STREAMABLE_HTTP.value,
            MCPTransport.WEBSOCKET.value,
        }:
            if not getattr(server, "url", None):
                invalid.append(f"'{server.name}' missing url for {tval} transport")

    if invalid:
        return CheckResult(
            name="mcp_configs",
            status=CheckStatus.ERROR,
            message=f"Invalid MCP server configs: {', '.join(invalid)}",
            details={"remediation": "Fix MCP server configuration in config file"},
        )

    return CheckResult(
        name="mcp_configs",
        status=CheckStatus.OK,
        message=f"{len(mcp_servers)} MCP server(s) configured",
        details={"servers": [s.name for s in mcp_servers]},
    )


def _check_mcp_availability(config: Any | None) -> CheckResult:
    """Check if MCP server executables/URLs are available."""
    if config is None:
        return CheckResult(
            name="mcp_availability",
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    mcp_servers = getattr(config, "mcp_servers", None) or []
    if not mcp_servers:
        return CheckResult(
            name="mcp_availability",
            status=CheckStatus.INFO,
            message="No MCP servers to check",
        )

    missing = []
    available = []
    remote = []

    for server in mcp_servers:
        transport = getattr(server, "transport", MCPTransport.STDIO)
        tval = _transport_value(transport)
        if tval == MCPTransport.STDIO.value:
            command = getattr(server, "command", None)
            cmd = command.split()[0] if command else None
            if cmd:
                if which(cmd):
                    available.append(server.name)
                else:
                    missing.append(f"{server.name} ({cmd})")
        else:
            remote.append(server.name)

    if missing:
        return CheckResult(
            name="mcp_availability",
            status=CheckStatus.WARNING,
            message=f"MCP servers not found: {', '.join(missing)}",
            details={
                "missing": missing,
                "available": available,
                "remote": remote,
                "remediation": "Install missing MCP servers or update config",
            },
        )

    details = {"available": available, "remote": remote}
    msg_parts = []
    if available:
        msg_parts.append(f"{len(available)} stdio command(s) found")
    if remote:
        msg_parts.append(f"{len(remote)} remote server(s)")

    return CheckResult(
        name="mcp_availability",
        status=CheckStatus.OK,
        message="All MCP servers: " + ", ".join(msg_parts) if msg_parts else "No servers",
        details=details,
    )


async def check_mcp_servers(config: Any | None = None) -> CategoryResult:
    """Check MCP servers."""
    checks = [
        _check_mcp_configs(config),
        _check_mcp_availability(config),
    ]
    return CategoryResult(
        category="mcp_servers",
        status=aggregate_status([check.status for check in checks]),
        checks=checks,
    )
