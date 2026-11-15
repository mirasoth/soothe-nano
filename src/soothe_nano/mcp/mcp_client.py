"""Multi-server MCP client over the raw mcp 2.x SDK with LangChain tool mapping.

Replaces the `langchain-mcp-adapters` dependency (which caps `mcp<2.0.0`):
per-transport session creation, MCP tool -> LangChain `StructuredTool`
conversion, and resource reads. Tools open a fresh session per invocation,
matching the adapter's connection-bound behavior.
"""

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, TypedDict

import httpx2
import mcp.types as mcp_types
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

__all__ = [
    "MCPToolArtifact",
    "MultiServerMCPClient",
    "create_session",
    "load_mcp_tools",
]

_BRACED_VAR_RE = re.compile(r"\$\{([^}]+)\}")

DEFAULT_SSE_TIMEOUT = 5.0
DEFAULT_SSE_READ_TIMEOUT = 300.0
DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_HTTP_READ_TIMEOUT = 300.0
_MAX_LIST_ITERATIONS = 100


def _expand_env_vars(value: str) -> str:
    """Expand `${VAR}` references in *value* from the current environment."""
    return _BRACED_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def _seconds(value: float | timedelta | None, default: float) -> float:
    if value is None:
        return default
    return value.total_seconds() if isinstance(value, timedelta) else float(value)


@asynccontextmanager
async def create_session(connection: dict[str, Any]) -> Any:
    """Create a ClientSession for one connection spec (mcp_config format)."""
    if "transport" not in connection:
        raise ValueError(
            "MCP connection spec is missing the 'transport' key; expected one of "
            "'stdio', 'sse', 'streamable_http'"
        )
    transport = connection["transport"]
    params = {k: v for k, v in connection.items() if k != "transport"}

    if transport == "stdio":
        env = params.get("env")
        resolved_env = {k: _expand_env_vars(v) for k, v in env.items()} if env is not None else None
        server_params = StdioServerParameters(
            command=params["command"],
            args=params.get("args") or [],
            env=resolved_env,
            cwd=params.get("cwd"),
            encoding=params.get("encoding", "utf-8"),
            encoding_error_handler=params.get("encoding_error_handler", "strict"),
        )
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write) as session,
        ):
            yield session
    elif transport == "sse":
        async with (
            sse_client(
                params["url"],
                params.get("headers"),
                _seconds(params.get("timeout"), DEFAULT_SSE_TIMEOUT),
                _seconds(params.get("sse_read_timeout"), DEFAULT_SSE_READ_TIMEOUT),
            ) as (read, write),
            ClientSession(read, write) as session,
        ):
            yield session
    elif transport in ("streamable_http", "streamable-http", "http"):
        timeout = httpx2.Timeout(
            _seconds(params.get("timeout"), DEFAULT_HTTP_TIMEOUT),
            read=_seconds(params.get("sse_read_timeout"), DEFAULT_HTTP_READ_TIMEOUT),
        )
        client = create_mcp_http_client(
            headers=params.get("headers"),
            timeout=timeout,
            auth=params.get("auth"),
        )
        async with (
            client,
            streamable_http_client(
                params["url"],
                http_client=client,
                terminate_on_close=params.get("terminate_on_close", True),
            ) as (read, write),
            ClientSession(read, write) as session,
        ):
            yield session
    else:
        raise ValueError(
            f"Unsupported MCP transport: {transport!r}. The mcp 2.x SDK provides "
            "'stdio', 'sse', and 'streamable_http' (websocket was removed)."
        )


class _MCPToolExecutionError(ToolException):
    """An MCP `is_error=True` tool result, carrying its content blocks."""

    def __init__(self, tool_content: list[dict[str, Any]]) -> None:
        super().__init__("MCP tool execution error")
        self.tool_content = tool_content


def _handle_mcp_tool_error(error: ToolException) -> list[dict[str, Any]] | str:
    """Surface MCP execution errors as failed tool output, not crashes."""
    if isinstance(error, _MCPToolExecutionError):
        return error.tool_content or [{"type": "text", "text": str(error)}]
    raise error


class MCPToolArtifact(TypedDict):
    """Structured content returned alongside an MCP tool result."""

    structured_content: dict[str, Any]


def _convert_content_block(content: Any) -> dict[str, Any]:
    """Convert one MCP content block to a LangChain content block dict."""
    if isinstance(content, mcp_types.TextContent):
        return {"type": "text", "text": content.text}
    if isinstance(content, mcp_types.ImageContent):
        return {"type": "image", "base64": content.data, "mime_type": content.mime_type}
    if isinstance(content, mcp_types.AudioContent):
        raise NotImplementedError(
            f"AudioContent conversion is not supported. Received mime type: {content.mime_type}"
        )
    if isinstance(content, mcp_types.ResourceLink):
        mime_type = content.mime_type or None
        if mime_type and mime_type.startswith("image/"):
            return {"type": "image", "url": str(content.uri), "mime_type": mime_type}
        return {"type": "file", "url": str(content.uri), "mime_type": mime_type}
    if isinstance(content, mcp_types.EmbeddedResource):
        resource = content.resource
        if isinstance(resource, mcp_types.TextResourceContents):
            return {"type": "text", "text": resource.text}
        if isinstance(resource, mcp_types.BlobResourceContents):
            mime_type = resource.mime_type or None
            if mime_type and mime_type.startswith("image/"):
                return {"type": "image", "base64": resource.blob, "mime_type": mime_type}
            return {"type": "file", "base64": resource.blob, "mime_type": mime_type}
        raise ValueError(f"Unknown embedded resource type: {type(resource).__name__}")
    raise ValueError(f"Unknown MCP content type: {type(content).__name__}")


def _convert_call_tool_result(
    result: Any,
) -> tuple[str | list[dict[str, Any]], MCPToolArtifact | None]:
    """Convert a CallToolResult to (content, artifact) for LangChain."""
    tool_content = [_convert_content_block(block) for block in result.content]
    if result.is_error:
        raise _MCPToolExecutionError(tool_content)
    artifact = None
    if result.structured_content is not None:
        artifact = MCPToolArtifact(structured_content=result.structured_content)
    if len(tool_content) == 1 and tool_content[0].get("type") == "text":
        return tool_content[0]["text"], artifact
    return tool_content, artifact


async def _list_all_tools(session: Any) -> list[Any]:
    """List every tool from a session, following pagination cursors."""
    tools: list[Any] = []
    cursor: str | None = None
    for _ in range(_MAX_LIST_ITERATIONS):
        params = mcp_types.PaginatedRequestParams(cursor=cursor) if cursor else None
        result = await session.list_tools(params=params)
        tools.extend(result.tools)
        cursor = result.next_cursor
        if not cursor:
            return tools
    raise RuntimeError("Exceeded maximum iterations while listing MCP tools")


def _convert_tool(connection: dict[str, Any], tool: Any) -> BaseTool:
    """Wrap one MCP tool in a StructuredTool that opens a fresh session per call."""

    async def call_tool(**arguments: Any) -> tuple[Any, MCPToolArtifact | None]:
        async with create_session(connection) as session:
            await session.initialize()
            result = await session.call_tool(tool.name, arguments)
        return _convert_call_tool_result(result)

    return StructuredTool(
        name=tool.name,
        description=tool.description or "",
        args_schema=tool.input_schema,
        coroutine=call_tool,
        response_format="content_and_artifact",
        handle_tool_error=_handle_mcp_tool_error,  # type: ignore[arg-type]
    )


async def load_mcp_tools(connection: dict[str, Any]) -> list[BaseTool]:
    """List tools on one connection and convert them to LangChain tools."""
    async with create_session(connection) as session:
        await session.initialize()
        tools = await _list_all_tools(session)
    return [_convert_tool(connection, tool) for tool in tools]


class MultiServerMCPClient:
    """Client for connecting to multiple MCP servers via the raw mcp SDK."""

    def __init__(
        self,
        connections: dict[str, dict[str, Any]] | None = None,
        *,
        tool_name_prefix: bool = False,
    ) -> None:
        self.connections: dict[str, dict[str, Any]] = connections or {}
        self.tool_name_prefix = tool_name_prefix

    @asynccontextmanager
    async def session(
        self,
        server_name: str,
        *,
        auto_initialize: bool = True,
    ) -> Any:
        """Connect to one named server and yield an initialized ClientSession."""
        if server_name not in self.connections:
            raise ValueError(
                f"Couldn't find a server with name {server_name!r}, "
                f"expected one of {sorted(self.connections)}"
            )
        async with create_session(self.connections[server_name]) as session:
            if auto_initialize:
                await session.initialize()
            yield session

    def _connection(self, server_name: str | None) -> dict[str, Any]:
        if server_name is None:
            raise ValueError("server_name is required")
        if server_name not in self.connections:
            raise ValueError(
                f"Couldn't find a server with name {server_name!r}, "
                f"expected one of {sorted(self.connections)}"
            )
        return self.connections[server_name]

    async def get_tools(self, *, server_name: str | None = None) -> list[BaseTool]:
        """List tools on one server as LangChain tools (fresh session per call)."""
        return await load_mcp_tools(self._connection(server_name))

    async def get_resources(
        self,
        server_name: str | None = None,
        *,
        uris: str | list[str] | None = None,
    ) -> list[Any]:
        """Read resource contents from one server.

        Args:
            server_name: Name of the server to read from.
            uris: A single URI or list of URIs to read.

        Returns:
            A list of TextResourceContents / BlobResourceContents objects.
        """
        uri_list = [uris] if isinstance(uris, str) else list(uris or [])
        contents: list[Any] = []
        async with self.session(server_name) as session:
            for uri in uri_list:
                result = await session.read_resource(uri)
                contents.extend(result.contents)
        return contents

    async def __aenter__(self) -> MultiServerMCPClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Nothing to close: every session is scoped to its own context manager."""
        return None
