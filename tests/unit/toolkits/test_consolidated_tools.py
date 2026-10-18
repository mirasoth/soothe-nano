"""Tests for consolidated capability toolkits (see RFC-0016)."""

from __future__ import annotations

from pathlib import Path

from langchain.tools import ToolRuntime

from soothe_nano.toolkits.wizsearch import WizsearchCrawlTool, WizsearchSearchTool

# ---------------------------------------------------------------------------
# Wizsearch Toolkit (formerly web_search)
# ---------------------------------------------------------------------------


class TestWizsearchToolkit:
    """Tests for the wizsearch toolkit."""

    def test_tool_names(self) -> None:
        """Wizsearch tools should have prefixed names."""
        search_tool = WizsearchSearchTool()
        crawl_tool = WizsearchCrawlTool()
        assert search_tool.name == "wizsearch_search"
        assert crawl_tool.name == "wizsearch_crawl"

    def test_description_mentions_search(self) -> None:
        tool = WizsearchSearchTool()
        assert "search" in tool.description.lower()
        assert "engine" in tool.description.lower()

    def test_crawl_description(self) -> None:
        tool = WizsearchCrawlTool()
        assert "crawl" in tool.description.lower() or "browser" in tool.description.lower()


# ---------------------------------------------------------------------------
# FileOps Toolkit (surgical file editing, not basic read/write)
# ---------------------------------------------------------------------------


class TestFileOpsToolkit:
    """Tests for file_ops toolkit - surgical file operations not in soothe_deepagents.

    Note: file_ops does NOT include read_file, write_file, search_files, list_files
    (those are provided by soothe_deepagents FilesystemMiddleware).
    """

    def test_delete_tool(self, tmp_path: Path) -> None:
        """Test delete tool."""
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

        test_file = tmp_path / "to_delete.txt"
        test_file.write_text("delete me")

        backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
        middleware = SootheFilesystemMiddleware(backend=backend)
        tool = next(t for t in middleware.tools if t.name == "delete")
        result = tool.func(
            file_path=str(test_file),
            runtime=ToolRuntime(
                state={"messages": [], "files": {}},
                context=None,
                tool_call_id="delete",
                store=None,
                stream_writer=lambda _: None,
                config={},
            ),
        )
        text = str(getattr(result, "content", result))
        assert "Deleted" in text or "deleted" in text.lower()
        assert not test_file.exists()

    def test_file_info_tool(self, tmp_path: Path) -> None:
        """Test file_info tool."""
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

        test_file = tmp_path / "info.txt"
        test_file.write_text("some content")

        backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
        middleware = SootheFilesystemMiddleware(backend=backend)
        tool = next(t for t in middleware.tools if t.name == "file_info")
        result = tool.func(
            path=str(test_file),
            runtime=ToolRuntime(
                state={"messages": [], "files": {}},
                context=None,
                tool_call_id="file_info",
                store=None,
                stream_writer=lambda _: None,
                config={},
            ),
        )

        text = str(getattr(result, "content", result))
        assert "Size" in text or "Path" in text or "size" in text.lower()

    def test_edit_lines_tool(self, tmp_path: Path) -> None:
        """Test edit_lines tool."""
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

        test_file = tmp_path / "edit.txt"
        test_file.write_text("line1\nline2\nline3\n")

        backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
        middleware = SootheFilesystemMiddleware(backend=backend)
        tool = next(t for t in middleware.tools if t.name == "edit_lines")
        tool.func(
            file_path=str(test_file),
            start_line=2,
            end_line=2,
            new_content="modified",
            runtime=ToolRuntime(
                state={"messages": [], "files": {}},
                context=None,
                tool_call_id="edit_lines",
                store=None,
                stream_writer=lambda _: None,
                config={},
            ),
        )

        assert "modified" in test_file.read_text()

    def test_insert_lines_tool(self, tmp_path: Path) -> None:
        """Test insert_lines tool."""
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

        test_file = tmp_path / "insert.txt"
        test_file.write_text("before\nafter\n")

        backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
        middleware = SootheFilesystemMiddleware(backend=backend)
        tool = next(t for t in middleware.tools if t.name == "insert_lines")
        tool.func(
            file_path=str(test_file),
            line=2,
            content="inserted",
            runtime=ToolRuntime(
                state={"messages": [], "files": {}},
                context=None,
                tool_call_id="insert_lines",
                store=None,
                stream_writer=lambda _: None,
                config={},
            ),
        )

        assert "inserted" in test_file.read_text()

    def test_delete_lines_tool(self, tmp_path: Path) -> None:
        """Test delete_lines tool."""
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

        test_file = tmp_path / "delete_lines.txt"
        test_file.write_text("keep1\ndelete\nkeep2\n")

        backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
        middleware = SootheFilesystemMiddleware(backend=backend)
        tool = next(t for t in middleware.tools if t.name == "delete_lines")
        tool.func(
            file_path=str(test_file),
            start_line=2,
            end_line=2,
            runtime=ToolRuntime(
                state={"messages": [], "files": {}},
                context=None,
                tool_call_id="delete_lines",
                store=None,
                stream_writer=lambda _: None,
                config={},
            ),
        )

        content = test_file.read_text()
        assert "keep1" in content
        assert "keep2" in content
        assert "delete" not in content

    def test_apply_diff_tool(self, tmp_path: Path) -> None:
        """Test apply_diff tool."""
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

        test_file = tmp_path / "diff.txt"
        test_file.write_text("old content\n")

        backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
        middleware = SootheFilesystemMiddleware(backend=backend)
        # Verify apply_diff tool is registered
        assert any(t.name == "apply_diff" for t in middleware.tools)
        # Note: apply_diff implementation would need proper diff format
        # This is a placeholder test


# ---------------------------------------------------------------------------
# Resolver: toolkit names resolve with backward compat
# ---------------------------------------------------------------------------


class TestResolverToolkitNames:
    """Toolkit names resolve correctly with backward compatibility."""

    def test_wizsearch_resolves(self) -> None:
        """Wizsearch toolkit should resolve to 2 tools."""
        from soothe_nano.utils.resolver import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("wizsearch")
        assert len(tools) == 2
        assert tools[0].name == "wizsearch_search"
        assert tools[1].name == "wizsearch_crawl"

    def test_surgical_file_names_resolve_individually(self) -> None:
        """Surgical FS names resolve via single-name routing (file_ops group retired)."""
        from soothe_nano.utils.resolver import _resolve_single_tool_group_uncached

        expected = {
            "delete",
            "file_info",
            "edit_lines",
            "insert_lines",
            "delete_lines",
            "apply_diff",
        }
        for name in expected:
            tools = _resolve_single_tool_group_uncached(name)
            assert len(tools) == 1, f"expected exactly one tool for {name}"
            assert tools[0].name == name
        # Base surface names resolve through the same middleware factory.
        for base_name in ("read_file", "write_file"):
            tools = _resolve_single_tool_group_uncached(base_name)
            assert {t.name for t in tools} == {base_name}

    def test_execution_resolves(self) -> None:
        """Execution toolkit should resolve to 5 tools."""
        from soothe_nano.utils.resolver import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("shell")
        assert len(tools) == 5
        assert tools[0].name == "run_command"
        tool_names = {t.name for t in tools}
        assert "tail_background_log" in tool_names


class TestResolverOldNamesRejected:
    """Legacy names should not resolve."""

    def test_old_names_rejected(self) -> None:
        """Legacy names without backward compat should not resolve."""
        from soothe_nano.utils.resolver import _resolve_single_tool_group_uncached

        for old_name in (
            "inquiry",
            "web_search",
            "code_edit",
            "cli",
            "tabular",
            "document",
            "python_executor",
            "data",
            "image",
            "analyze_image",
            "inspect_data",
        ):
            tools = _resolve_single_tool_group_uncached(old_name)
            assert tools == [], f"Legacy name '{old_name}' should not resolve"


# ---------------------------------------------------------------------------
# Domain-scoped prompts
# ---------------------------------------------------------------------------


class TestDomainScopedPrompts:
    """Tests for domain-scoped prompt guides."""

    def test_guides_exist(self) -> None:
        from soothe_nano.prompts.system_templates import (
            _DATA_GUIDE,
            _FILE_OPS_GUIDE,
            _RESEARCH_GUIDE,
            _SEARCH_GUIDE,
            _SHELL_GUIDE,
            _SUBAGENT_GUIDE,
        )

        assert "wizsearch_search" in _RESEARCH_GUIDE
        assert "wizsearch_crawl" in _RESEARCH_GUIDE
        assert "research" in _RESEARCH_GUIDE.lower()
        assert "read_file" in _FILE_OPS_GUIDE or "file" in _FILE_OPS_GUIDE.lower()
        assert "grep" in _FILE_OPS_GUIDE
        assert "glob" in _FILE_OPS_GUIDE
        assert "search_files" not in _FILE_OPS_GUIDE
        assert "list_files" not in _FILE_OPS_GUIDE
        assert "run_command" in _SHELL_GUIDE
        assert "grep / glob" in _SHELL_GUIDE or "grep" in _SHELL_GUIDE
        assert "grep tool" in _SEARCH_GUIDE
        assert "run_command with `rg`" in _SEARCH_GUIDE or "true regex" in _SEARCH_GUIDE
        assert "data" in _DATA_GUIDE.lower()
        assert "planner" in _SUBAGENT_GUIDE.lower()
        assert "task" in _SUBAGENT_GUIDE.lower()
        assert "batched `grep`" in _SUBAGENT_GUIDE
        assert "run_command` with `rg`" not in _SUBAGENT_GUIDE

    def test_orchestration_guide_has_all_domains(self) -> None:
        from soothe_nano.prompts import SystemTemplates

        guide = SystemTemplates.TOOL_ORCHESTRATION_GUIDE
        # Check for tool categories mentioned in the guide
        guide_lower = guide.lower()
        assert "read_file" in guide_lower or "file" in guide_lower
        assert "run_command" in guide_lower or "shell" in guide_lower
        assert "data" in guide_lower
        assert "wizsearch_search" in guide_lower or "web" in guide_lower
        assert "research" in guide_lower
        assert "native tools first" in guide_lower or "grep tool" in guide_lower

    def test_no_old_tool_names_in_guide(self) -> None:
        from soothe_nano.prompts import SystemTemplates

        guide = SystemTemplates.TOOL_ORCHESTRATION_GUIDE
        # Old names should not appear (they've been consolidated)
        # Note: wizsearch is a valid name, so we check for the old web_search pattern
        # file_edit is also valid (backward compat), so we check for truly deprecated ones
        assert "run_cli" not in guide
        assert "python_executor" not in guide
        assert "inquiry" not in guide
        assert "search_files" not in guide
        assert "list_files" not in guide
