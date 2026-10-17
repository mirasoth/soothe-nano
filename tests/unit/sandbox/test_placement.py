"""Placement model tests (RFC §7.5): derivation, overrides, shuttle adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from soothe_nano.sandbox.placement import (
    PLACEMENT_DENY,
    PLACEMENT_GUEST,
    PLACEMENT_HOST,
    PLACEMENT_PROTOCOL,
    PLACEMENT_SHUTTLE,
    resolve_placement,
    wrap_shuttle_tool,
)


@pytest.fixture()
def fake_meta(monkeypatch: pytest.MonkeyPatch):
    """Register a temp ToolMeta and clean up afterwards."""

    def _register(name: str, **kwargs: Any) -> None:
        from soothe_nano.tools.metadata import TOOL_REGISTRY, ToolMeta

        meta = ToolMeta(name=name, **kwargs)
        monkeypatch.setitem(TOOL_REGISTRY, name, meta)

    return _register


class TestResolvePlacement:
    def test_default_table(self) -> None:
        assert resolve_placement("run_command") == PLACEMENT_GUEST
        assert resolve_placement("run_background") == PLACEMENT_GUEST
        assert resolve_placement("read_file") == PLACEMENT_PROTOCOL
        assert resolve_placement("apply_diff") == PLACEMENT_PROTOCOL
        assert resolve_placement("search_tools") == PLACEMENT_HOST
        assert resolve_placement("current_datetime") == PLACEMENT_HOST
        assert resolve_placement("no_such_tool_xyz") == PLACEMENT_DENY

    def test_config_override_wins(self) -> None:
        class Cfg:
            class sandbox:  # noqa: N801 - simple namespace stand-in
                placement_overrides = {"read_file": "host", "no_such_tool_xyz": "shuttle"}

        assert resolve_placement("read_file", config=Cfg()) == PLACEMENT_HOST
        # Override can even rescue a registry miss.
        assert resolve_placement("no_such_tool_xyz", config=Cfg()) == PLACEMENT_SHUTTLE

    def test_explicit_tool_declaration_wins_over_table(self) -> None:
        class Tool:
            name = "run_command"
            _tool_placement = "host"

        assert resolve_placement("run_command", tool=Tool()) == PLACEMENT_HOST

    def test_registry_placement_beats_category(self, fake_meta) -> None:
        fake_meta("my_shuttled_reader", category="generic", outcome_type="file_read",
                  placement="host")
        assert resolve_placement("my_shuttled_reader") == PLACEMENT_HOST
        fake_meta("my_plain_reader", category="generic", outcome_type="file_read")
        assert resolve_placement("my_plain_reader") == PLACEMENT_SHUTTLE

    def test_registry_derives_guest_from_execution(self, fake_meta) -> None:
        fake_meta("my_runner", category="execution", outcome_type="code_exec")
        assert resolve_placement("my_runner") == PLACEMENT_GUEST


class TestShuttleAdapter:
    @staticmethod
    def _make_tool(name: str, func: Any, schema: Any) -> StructuredTool:
        return StructuredTool(name=name, description="t", args_schema=schema, func=func)

    def test_roundtrip_download_run_upload_remap(self, fake_meta, tmp_path: Path) -> None:
        from pydantic import BaseModel

        class AnalyzeArgs(BaseModel):
            path: str

        uploads: list[tuple[str, bytes]] = []

        class FakeBackend:
            def download_files(self, paths: list[str]):
                from types import SimpleNamespace

                return [
                    SimpleNamespace(path=p, content=b"DATA:" + p.encode(), error=None)
                    for p in paths
                ]

            def upload_files(self, pairs: list[tuple[str, bytes]]):
                from types import SimpleNamespace

                for p, d in pairs:
                    uploads.append((p, d))
                return [SimpleNamespace(path=p, error=None) for p, _ in pairs]

        backend = FakeBackend()

        def _analyze(path: str) -> str:
            content = Path(path).read_bytes()
            return f"analyzed {len(content)} bytes from {path}"

        fake_meta(
            "shuttle_analyze",
            category="generic",
            outcome_type="file_read",
            path_arg_keys=("path",),
        )
        tool = self._make_tool("shuttle_analyze", _analyze, AnalyzeArgs)
        wrapped = wrap_shuttle_tool(tool, backend=backend)
        assert wrapped is not tool

        out = wrapped.invoke({"path": "/workspace/data.csv"})
        assert "analyzed 24 bytes" in out
        # No host temp path leaks into the model-visible output (§7.5.6 step 6).
        assert "soothe-shuttle" not in out
        assert "/workspace/data.csv" in out

    def test_write_back_uploads_result(self, fake_meta) -> None:
        from pydantic import BaseModel

        class EditArgs(BaseModel):
            path: str

        downloads = {"file content here"}
        uploads: list[tuple[str, bytes]] = []

        class FakeBackend:
            def download_files(self, paths: list[str]):
                from types import SimpleNamespace

                return [SimpleNamespace(path=p, content=b"file content here", error=None) for p in paths]

            def upload_files(self, pairs: list[tuple[str, bytes]]):
                from types import SimpleNamespace

                uploads.extend(pairs)
                return [SimpleNamespace(path=p, error=None) for p, _ in pairs]

        def _edit(path: str) -> str:
            text = Path(path).read_text()
            Path(path).write_text(text + "\nappended")
            return f"edited {path}"

        fake_meta(
            "shuttle_edit",
            category="generic",
            outcome_type="file_write",
            path_arg_keys=("path",),
        )
        tool = self._make_tool("shuttle_edit", _edit, EditArgs)
        wrapped = wrap_shuttle_tool(tool, backend=FakeBackend())

        out = wrapped.invoke({"path": "/workspace/notes.txt"})
        assert "edited /workspace/notes.txt" in out
        assert uploads and uploads[0][0] == "/workspace/notes.txt"
        assert "appended" in uploads[0][1].decode()

    def test_oversize_transfer_errors(self, fake_meta) -> None:
        from pydantic import BaseModel

        class ReadArgs(BaseModel):
            path: str

        class Cfg:
            class sandbox:  # noqa: N801
                max_shuttle_bytes = 4
                placement_overrides: dict[str, str] = {}

        class FakeBackend:
            def download_files(self, paths: list[str]):
                from types import SimpleNamespace

                return [SimpleNamespace(path=p, content=b"way too many bytes", error=None) for p in paths]

        fake_meta("shuttle_big", outcome_type="file_read", path_arg_keys=("path",))
        tool = self._make_tool("shuttle_big", lambda path: "x", ReadArgs)
        wrapped = wrap_shuttle_tool(tool, backend=FakeBackend(), config=Cfg())
        with pytest.raises(RuntimeError, match="max_shuttle_bytes"):
            wrapped.invoke({"path": "/workspace/big.bin"})

    def test_non_structured_tool_passes_through(self) -> None:
        class Weird:
            name = "weird"

        weird = Weird()
        assert wrap_shuttle_tool(weird, backend=object()) is weird
