"""MCP server diagnose checks.

Delegates config validation and category aggregation to the Rust extension.
Python retains the config introspection and binary availability probing.
"""

from __future__ import annotations

from shutil import which
from typing import Any

from soothe_nano._rust_compat import (
    check_mcp_availability_rust,
    check_mcp_configs_rust,
    check_mcp_servers_from_results_rust,
)
from soothe_nano.config.models import MCPTransport
from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
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

    # Build server specs for Rust validation.
    server_specs: list[tuple[str, str, str | None, str | None]] = []
    for server in mcp_servers:
        name = getattr(server, "name", None) or ""
        transport = getattr(server, "transport", MCPTransport.STDIO)
        tval = _transport_value(transport)
        command = getattr(server, "command", None)
        url = getattr(server, "url", None)
        server_specs.append((name, tval, command, url))

    # Delegate config validation to Rust.
    result_dict = check_mcp_configs_rust(server_specs)
    return CheckResult(
        name=result_dict["name"],
        status=CheckStatus(result_dict["status"]),
        message=result_dict["message"],
        details=result_dict.get("details", {}),
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

    # Build availability data for Rust.
    availability_data: list[tuple[str, str, str | None, bool, bool]] = []
    for server in mcp_servers:
        transport = getattr(server, "transport", MCPTransport.STDIO)
        tval = _transport_value(transport)
        if tval == MCPTransport.STDIO.value:
            command = getattr(server, "command", None)
            cmd = command.split()[0] if command else None
            is_available = bool(which(cmd)) if cmd else False
            availability_data.append((server.name, tval, cmd, is_available, False))
        else:
            url = getattr(server, "url", None)
            availability_data.append((server.name, tval, url, False, True))

    # Delegate availability aggregation to Rust.
    result_dict = check_mcp_availability_rust(availability_data)
    return CheckResult(
        name=result_dict["name"],
        status=CheckStatus(result_dict["status"]),
        message=result_dict["message"],
        details=result_dict.get("details", {}),
    )


async def check_mcp_servers(config: Any | None = None) -> CategoryResult:
    """Check MCP servers."""
    checks = [
        _check_mcp_configs(config),
        _check_mcp_availability(config),
    ]
    # Delegate category aggregation to Rust.
    check_dicts = [c.to_dict() for c in checks]
    result_dict = check_mcp_servers_from_results_rust(check_dicts)
    return CategoryResult(
        category=result_dict["category"],
        status=CheckStatus(result_dict["status"]),
        checks=checks,
        message=result_dict.get("message"),
    )
