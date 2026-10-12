"""End-to-end MCPRegistry lifecycle tests against a mocked MCP service.

Drives the full registry lifecycle — initialize → fetch capabilities →
invoke tool → read resource → shutdown — against an in-process mock of
``langchain_mcp_adapters.MultiServerMCPClient`` and a fake session. Covers
``MCPRegistry`` public methods and the ``mcp_registry_support`` functions
(``fetch_tools_and_descriptors``, ``fetch_prompts``, ``fetch_resources``,
``invoke_tool``, ``read_resource``, cleanup) that issue #22 regressed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from soothe_nano.config.models import (
    MCPAuthHeaders,
    MCPServerConfig,
    MCPTransport,
)
from soothe_nano.mcp.mcp_registry import MCPRegistry

# --- Fake MCP service objects ------------------------------------------------


class _FakeTool:
    """A tool-like object exposing ``name``, ``description``, ``ainvoke``."""

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self.invoked_with: dict | None = None

    async def ainvoke(self, args: dict) -> str:
        self.invoked_with = args
        return f"result:{self.name}"


class _FakePrompt:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


class _FakeResource:
    def __init__(
        self, uri: str, name: str, description: str = "", mime_type: str = "text/plain"
    ) -> None:
        self.uri = uri
        self.name = name
        self.description = description
        self.mimeType = mime_type


class _FakeBlob:
    def __init__(self, data: bytes | str) -> None:
        self.data = data


class _FakeSession:
    """Simulates an MCP server session (prompts/resources + close)."""

    def __init__(self, prompts: list[_FakePrompt], resources: list[_FakeResource]) -> None:
        self._prompts = prompts
        self._resources = resources
        self.closed = False

    async def list_prompts(self) -> list[_FakePrompt]:
        return self._prompts

    async def list_resources(self) -> list[_FakeResource]:
        return self._resources

    async def close(self) -> None:
        self.closed = True


class _FakeSessionContext:
    """Async context manager yielding a fake session — matches the client.session() shape."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *args: Any) -> None:
        return None


class MockMCPService:
    """In-process stand-in for ``MultiServerMCPClient``.

    Constructed with per-server tool/prompt/resource catalogs. Exposes the
    subset of the client API that ``MCPRegistry`` and ``mcp_registry_support``
    touch: ``session()``, ``get_tools()``, ``get_resources()``, ``__aexit__``.
    """

    def __init__(self, server_data: dict[str, dict[str, list]]) -> None:
        self._server_data = server_data
        self.connections_arg: dict | None = None
        self.tool_name_prefix_arg: Any = None
        self.closed = False
        self.resource_blobs: dict[tuple[str, str], _FakeBlob] = {}
        self.sessions: dict[str, _FakeSession] = {}

    def construct(self, connections: dict, tool_name_prefix: bool = False) -> MockMCPService:
        """Pretend to be the MultiServerMCPClient constructor."""
        self.connections_arg = connections
        self.tool_name_prefix_arg = tool_name_prefix
        return self

    def set_resource_blob(self, server: str, uri: str, blob: _FakeBlob) -> None:
        self.resource_blobs[(server, uri)] = blob

    def session(self, name: str, auto_initialize: bool = True) -> _FakeSessionContext:
        data = self._server_data[name]
        session = _FakeSession(data.get("prompts", []), data.get("resources", []))
        self.sessions[name] = session
        return _FakeSessionContext(session)

    async def get_tools(self, *, server_name: str) -> list[_FakeTool]:
        """0.3.x-style async get_tools — returns a coroutine that must be awaited."""
        return list(self._server_data[server_name]["tools"])

    async def get_resources(self, *, server_name: str, uris: str) -> list[_FakeBlob]:
        blob = self.resource_blobs.get((server_name, uris))
        return [blob] if blob is not None else []

    async def __aexit__(self, *args: Any) -> None:
        self.closed = True


# --- Fixtures ----------------------------------------------------------------


def _stdio_server(name: str, *, defer: bool = False, env: dict | None = None) -> MCPServerConfig:
    return MCPServerConfig(
        name=name, command="echo", transport=MCPTransport.STDIO, defer=defer, env=env or {}
    )


def _sse_server(
    name: str, *, defer: bool = False, auth: MCPAuthHeaders | None = None
) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        url="http://localhost:9999/sse",
        transport=MCPTransport.SSE,
        defer=defer,
        auth=auth,
    )


@pytest.fixture
def mock_service() -> MockMCPService:
    return MockMCPService(
        {
            "tasks": {
                "tools": [
                    _FakeTool("create_task", "Create a task"),
                    _FakeTool("list_tasks", "List tasks"),
                ],
                "prompts": [_FakePrompt("show_tasks", "Show open tasks")],
                "resources": [_FakeResource("task://1", "Task 1", "A task", "text/plain")],
            },
            "monitor": {
                "tools": [_FakeTool("query_metric", "Query a metric")],
                "prompts": [],
                "resources": [],
            },
        }
    )


def _patch_client(service: MockMCPService):
    return patch(
        "langchain_mcp_adapters.client.MultiServerMCPClient",
        side_effect=service.construct,
    )


# --- Lifecycle tests ---------------------------------------------------------


async def test_initialize_connects_and_fetches_capabilities(mock_service: MockMCPService) -> None:
    """initialize() connects every server and populates tools/prompts/resources."""
    servers = [_stdio_server("tasks", defer=False), _sse_server("monitor", defer=True)]
    registry = MCPRegistry(servers=servers)

    with _patch_client(mock_service):
        await registry.initialize()

    status = registry.connection_status()
    assert set(status) == {"tasks", "monitor"}
    assert status["tasks"].status == "connected"
    assert status["tasks"].tool_count == 2
    assert status["tasks"].prompt_count == 1
    assert status["tasks"].resource_count == 1
    assert status["monitor"].tool_count == 1

    always_loaded = registry.always_loaded_tools()
    assert {t.name for t in always_loaded} == {"mcp__tasks__create_task", "mcp__tasks__list_tasks"}

    all_tools = registry.all_tools()
    assert {t.name for t in all_tools} == {
        "mcp__tasks__create_task",
        "mcp__tasks__list_tasks",
        "mcp__monitor__query_metric",
    }

    deferred = registry.deferred_tools()
    assert len(deferred) == 1
    assert deferred[0].bare_name == "query_metric"
    assert deferred[0].server == "monitor"
    assert deferred[0].is_essential is False

    prompts = registry.prompts()
    assert len(prompts["tasks"]) == 1
    assert prompts["tasks"][0]["bare_name"] == "show_tasks"
    assert prompts["tasks"][0]["name"] == "mcp__tasks__show_tasks"

    resources = registry.resources()
    assert len(resources["tasks"]) == 1
    assert resources["tasks"][0]["uri"] == "task://1"
    assert resources["tasks"][0]["mime_type"] == "text/plain"

    await registry.shutdown()


async def test_invoke_routes_args_and_returns_result(mock_service: MockMCPService) -> None:
    """invoke() finds the tool by mangled name and awaits ainvoke with args."""
    registry = MCPRegistry(servers=[_stdio_server("tasks")])

    with _patch_client(mock_service):
        await registry.initialize()

    result = await registry.invoke("tasks", "mcp__tasks__create_task", {"title": "ship it"})

    assert result == "result:mcp__tasks__create_task"
    tool = next(t for t in registry._tools["tasks"] if t.name == "mcp__tasks__create_task")
    assert tool.invoked_with == {"title": "ship it"}

    await registry.shutdown()


async def test_read_resource_decodes_bytes_and_str(mock_service: MockMCPService) -> None:
    """read_resource() decodes bytes payloads and passes through str payloads."""
    registry = MCPRegistry(servers=[_stdio_server("tasks")])

    with _patch_client(mock_service):
        await registry.initialize()

    mock_service.set_resource_blob("tasks", "task://1", _FakeBlob(b"hello bytes"))
    content = await registry.read_resource("tasks", "task://1")
    assert content == "hello bytes"

    mock_service.set_resource_blob("tasks", "task://1", _FakeBlob("plain string"))
    content = await registry.read_resource("tasks", "task://1")
    assert content == "plain string"

    await registry.shutdown()


async def test_shutdown_closes_client(mock_service: MockMCPService) -> None:
    """shutdown() runs the cleanup ladder and closes the underlying client."""
    registry = MCPRegistry(servers=[_stdio_server("tasks"), _sse_server("monitor")])

    with _patch_client(mock_service):
        await registry.initialize()

    await registry.shutdown()

    assert mock_service.closed is True
    assert mock_service.sessions["monitor"].closed is True


async def test_secret_resolver_resolves_env_and_auth_headers(
    mock_service: MockMCPService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """secret_resolver interpolates ${VAR} in server env and auth headers at connect time."""
    monkeypatch.setenv("TEST_MCP_TOKEN", "super-secret-token")

    from soothe_nano.config.settings import SootheConfig

    config = SootheConfig()
    resolver = config.secret_resolver
    assert resolver("${TEST_MCP_TOKEN}") == "super-secret-token"

    servers = [
        _stdio_server("tasks", env={"API_TOKEN": "${TEST_MCP_TOKEN}"}),
        _sse_server(
            "monitor", auth=MCPAuthHeaders(headers={"Authorization": "Bearer ${TEST_MCP_TOKEN}"})
        ),
    ]
    registry = MCPRegistry(servers=servers, secret_resolver=config.secret_resolver)

    with _patch_client(mock_service):
        await registry.initialize()

    assert mock_service.connections_arg is not None
    assert mock_service.connections_arg["tasks"]["env"]["API_TOKEN"] == "super-secret-token"
    assert (
        mock_service.connections_arg["monitor"]["headers"]["Authorization"]
        == "Bearer super-secret-token"
    )

    await registry.shutdown()


async def test_coroutine_get_tools_is_awaited_in_lifecycle(mock_service: MockMCPService) -> None:
    """Regression for issue #22: the async get_tools coroutine is awaited during initialize."""
    servers = [_stdio_server("tasks", defer=False)]
    registry = MCPRegistry(servers=servers)

    with _patch_client(mock_service):
        await registry.initialize()

    # If the coroutine were not awaited, _tools would be empty and a
    # RuntimeWarning ("coroutine was never awaited") would surface.
    assert len(registry.all_tools()) == 2
    assert {t.name for t in registry.all_tools()} == {
        "mcp__tasks__create_task",
        "mcp__tasks__list_tasks",
    }

    await registry.shutdown()


async def test_invoke_unknown_tool_raises(mock_service: MockMCPService) -> None:
    """invoke() on an unknown tool name raises ValueError via invoke_tool."""
    registry = MCPRegistry(servers=[_stdio_server("tasks")])

    with _patch_client(mock_service):
        await registry.initialize()

    with pytest.raises(ValueError, match="not found"):
        await registry.invoke("tasks", "mcp__tasks__nope", {})

    await registry.shutdown()


async def test_initialize_is_idempotent(mock_service: MockMCPService) -> None:
    """A second initialize() is a no-op that warns."""
    registry = MCPRegistry(servers=[_stdio_server("tasks")])

    with _patch_client(mock_service):
        await registry.initialize()
        await registry.initialize()

    assert len(registry.all_tools()) == 2
    await registry.shutdown()


async def test_handle_disconnect_marks_connection(mock_service: MockMCPService) -> None:
    """handle_disconnect() flips status and leaves the connection registered."""
    registry = MCPRegistry(servers=[_stdio_server("tasks")])

    with _patch_client(mock_service):
        await registry.initialize()

    assert registry.connection_status()["tasks"].status == "connected"
    await registry.handle_disconnect("tasks")
    assert registry.connection_status()["tasks"].status == "disconnected"

    await registry.shutdown()
