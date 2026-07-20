"""Tests for thin grep helpers over deepagents search."""

from __future__ import annotations

from pathlib import Path

import pytest
from soothe_deepagents.backends.protocol import GrepResult

from soothe_nano.filesystem.grep_search import (
    get_ag_bin,
    get_rg_bin,
    is_grep_available,
    reset_grep_backend_cache,
    run_grep,
)
from soothe_nano.filesystem.local import LocalFilesystem


@pytest.fixture(autouse=True)
def _reset_grep_cache() -> None:
    reset_grep_backend_cache()


def test_is_grep_available_reflects_rg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_RG_PATH", raising=False)
    monkeypatch.setattr("soothe_nano.filesystem.grep_search.shutil.which", lambda _: None)
    reset_grep_backend_cache()
    assert is_grep_available() is False
    assert get_rg_bin() is None

    monkeypatch.setattr(
        "soothe_nano.filesystem.grep_search.shutil.which",
        lambda name: "/usr/bin/rg" if name == "rg" else None,
    )
    reset_grep_backend_cache()
    assert is_grep_available() is True
    assert get_rg_bin() == "/usr/bin/rg"


def test_resolve_rg_prefers_soothe_rg_path_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom_rg = tmp_path / "custom-rg"
    custom_rg.write_text("stub\n")
    custom_rg.chmod(0o755)
    monkeypatch.setenv("SOOTHE_RG_PATH", str(custom_rg))
    monkeypatch.setattr("soothe_nano.filesystem.grep_search.shutil.which", lambda _: "/usr/bin/rg")
    reset_grep_backend_cache()
    assert get_rg_bin() == str(custom_rg)


def test_get_ag_bin_always_none() -> None:
    assert get_ag_bin() is None


def test_run_grep_content_mode(tmp_path: Path) -> None:
    (tmp_path / "search.txt").write_text("line one\nhello world\n")
    result = run_grep("hello", path=tmp_path, output_mode="content")
    assert isinstance(result, GrepResult)
    assert result.matches
    assert any("hello world" in (m.get("text") or "") for m in result.matches)


def test_run_grep_content_mode_single_file(tmp_path: Path) -> None:
    target = tmp_path / "search.txt"
    target.write_text("line one\nhello world\n")
    result = run_grep("hello", path=target, output_mode="content")
    assert isinstance(result, GrepResult)
    assert result.matches
    assert len(result.matches) >= 1


def test_run_grep_files_with_matches(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle here\n")
    (tmp_path / "b.txt").write_text("nothing\n")
    result = run_grep("needle", path=tmp_path, output_mode="files_with_matches")
    assert isinstance(result, list)
    assert any("a.txt" in p for p in result)


def test_run_grep_count_mode(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle\nneedle\n")
    result = run_grep("needle", path=tmp_path, output_mode="count")
    assert isinstance(result, str)
    assert "a.txt" in result


def test_run_grep_with_glob(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("needle\n")
    (tmp_path / "skip.txt").write_text("needle\n")
    result = run_grep("needle", path=tmp_path, output_mode="files_with_matches", glob="*.py")
    assert isinstance(result, list)
    assert any("keep.py" in p for p in result)
    assert not any("skip.txt" in p for p in result)


def test_local_grep_uses_backend_search(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle\n")
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    result = fs.grep("needle", output_mode="files_with_matches")
    assert isinstance(result, list)
    assert any("a.txt" in p for p in result)


def test_local_grep_content_mode_via_backend(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("find needle here\n")
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    result = fs.grep("needle", output_mode="content")
    assert isinstance(result, GrepResult)
    assert result.matches


@pytest.mark.asyncio
async def test_agrep_uses_backend_search(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle\n")
    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    result = await fs.agrep("needle", output_mode="files_with_matches")
    assert isinstance(result, list)
    assert any("a.txt" in p for p in result)


def test_local_grep_single_file_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    log_file = tmp_path / "outside.log"
    log_file.write_text("executor:1186 boom\n", encoding="utf-8")

    fs = LocalFilesystem(workspace=ws, virtual_mode=True)
    result = fs.grep("executor:1186", path=str(log_file.resolve()), output_mode="content")
    assert isinstance(result, GrepResult)
    assert result.matches
    assert "executor:1186" in result.matches[0]["text"]


def test_grep_host_absolute_file_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    log_file = tmp_path / "outside.log"
    log_file.write_text("executor:1186 boom\n", encoding="utf-8")

    fs = LocalFilesystem(workspace=ws, virtual_mode=True)
    result = fs.grep("executor:1186", path=str(log_file.resolve()), output_mode="content")
    assert isinstance(result, GrepResult)
    assert result.matches
    assert "executor:1186" in result.matches[0]["text"]


def test_grep_write_rejects_host_absolute_outside_workspace(tmp_path: Path) -> None:
    from soothe_nano.filesystem.exceptions import FilesystemError

    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original\n", encoding="utf-8")

    fs = LocalFilesystem(workspace=ws, virtual_mode=True)
    with pytest.raises(FilesystemError):
        fs.write(str(outside.resolve()), "mutated\n")


def test_normalized_backend_grep_via_backend(tmp_path: Path) -> None:
    from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend

    (tmp_path / "needle.txt").write_text("find AgentLoop here\n")

    backend = NormalizedPathBackend(root_dir=tmp_path, virtual_mode=True)
    result = backend.grep("AgentLoop", path=".", output_mode="content")

    assert result.error is None
    assert result.matches is not None
    assert len(result.matches) == 1


def test_local_grep_content_mode_with_backend(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# AgentLoop migration\n")

    fs = LocalFilesystem(workspace=tmp_path, virtual_mode=True)
    result = fs.grep("AgentLoop", path=".", output_mode="content")

    assert isinstance(result, GrepResult)
    assert len(result.matches or []) >= 1
