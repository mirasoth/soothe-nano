"""Tests for filesystem discovery hints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from soothe_deepagents.backends import FilesystemBackend

from soothe_nano.filesystem.discovery_hints import (
    GLOB_DISCOVERY_FALLBACK_HINT,
    GLOB_TOOL_DESCRIPTION,
    GREP_DISCOVERY_FALLBACK_HINT,
    GREP_TOOL_DESCRIPTION,
    format_glob_timeout_error,
)
from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware
from soothe_nano.workspace.workspace_filesystem import get_workspace_backend


def test_glob_tool_description_includes_discovery_fallback() -> None:
    assert "grep" in GLOB_TOOL_DESCRIPTION
    assert GLOB_DISCOVERY_FALLBACK_HINT in GLOB_TOOL_DESCRIPTION


def test_grep_tool_description_prefers_native_over_shell() -> None:
    assert "LITERAL" in GREP_TOOL_DESCRIPTION
    assert "run_command" in GREP_TOOL_DESCRIPTION
    assert GREP_DISCOVERY_FALLBACK_HINT in GREP_TOOL_DESCRIPTION
    assert "explicit path" in GREP_TOOL_DESCRIPTION


def test_format_glob_timeout_error_includes_fallback() -> None:
    message = format_glob_timeout_error(30.0)
    assert "timed out after 30s" in message
    assert "grep" in message


def test_soothe_filesystem_middleware_glob_has_discovery_description(tmp_path: Path) -> None:
    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=False)
    middleware = SootheFilesystemMiddleware(backend=backend)
    glob_tool = next(t for t in middleware.tools if t.name == "glob")
    assert GLOB_DISCOVERY_FALLBACK_HINT in glob_tool.description
    assert glob_tool.args_schema is not None


def test_soothe_filesystem_middleware_grep_has_native_search_description(tmp_path: Path) -> None:
    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=False)
    middleware = SootheFilesystemMiddleware(backend=backend)
    grep_tool = next(t for t in middleware.tools if t.name == "grep")
    assert GREP_DISCOVERY_FALLBACK_HINT in grep_tool.description
    assert "LITERAL" in grep_tool.description


def test_deepagents_glob_uses_soothe_backend(tmp_path: Path) -> None:
    """Deepagents built-in glob must call ``backend.glob`` on the resolved workspace backend."""
    (tmp_path / "alpha.txt").write_text("x", encoding="utf-8")

    def factory(ws: str) -> object:
        return get_workspace_backend(Path(ws), virtual_mode=True)

    backend = factory(str(tmp_path))
    middleware = SootheFilesystemMiddleware(
        backend=backend,
        workspace_root=str(tmp_path),
        workspace_backend_factory=factory,
    )
    glob_tool = next(t for t in middleware.tools if t.name == "glob")
    runtime = MagicMock(spec=ToolRuntime)
    runtime.tool_call_id = "glob-test"
    runtime.config = {"configurable": {}}

    result = glob_tool.func("*.txt", runtime, "/")

    assert isinstance(result, ToolMessage)
    assert result.status == "success"
    assert "alpha.txt" in str(result.content)
