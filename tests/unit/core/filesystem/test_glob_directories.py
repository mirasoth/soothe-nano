"""Tests for high-performance directory-capable glob."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from soothe_deepagents.backends.glob_search import (
    list_via_scandir,
    max_depth_for_pattern,
    parse_glob_pattern,
)

from soothe_nano.filesystem.workspace import WorkspaceFilesystem


def test_parse_glob_pattern_trailing_slash() -> None:
    assert parse_glob_pattern("packages/*/") == ("packages/*", True)
    assert parse_glob_pattern("**/*.py") == ("**/*.py", False)


def test_max_depth_for_pattern() -> None:
    assert max_depth_for_pattern("packages/*") == 2
    assert max_depth_for_pattern("*") is None  # basename patterns are recursive
    assert max_depth_for_pattern("**/*.py") is None


def test_glob_dirs_only_trailing_slash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe_nano.filesystem.workspace.list_via_fd",
        lambda *_a, **_k: None,
    )

    ws = tmp_path / "repo"
    (ws / "packages" / "soothe").mkdir(parents=True)
    (ws / "packages" / "soothe-cli").mkdir(parents=True)
    (ws / "packages" / "soothe" / "src").mkdir()
    (ws / "packages" / "soothe" / "src" / "x.py").write_text("x", encoding="utf-8")
    (ws / "README.md").write_text("hi", encoding="utf-8")

    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("packages/*/")
    assert result.error is None
    matches = result.matches or []
    assert matches
    assert all(m.get("is_dir") for m in matches)
    names = {Path(m["path"]).name for m in matches}
    assert names == {"soothe", "soothe-cli"}
    # Depth bound must not return nested src as a packages/*/ match
    assert not any(Path(m["path"]).name == "src" for m in matches)


def test_glob_files_and_dirs_without_trailing_slash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe_nano.filesystem.workspace.list_via_fd",
        lambda *_a, **_k: None,
    )

    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "subdir").mkdir()
    (ws / "file.txt").write_text("x", encoding="utf-8")

    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("*")
    matches = result.matches or []
    by_name = {Path(m["path"]).name: m.get("is_dir") for m in matches}
    assert by_name.get("subdir") is True
    assert by_name.get("file.txt") is False


def test_glob_scandir_depth_bound_skips_deep_tree(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    deep = ws / "packages" / "foo" / "src" / "nested"
    deep.mkdir(parents=True)
    (deep / "deep.txt").write_text("x", encoding="utf-8")
    (ws / "packages" / "bar.txt").write_text("y", encoding="utf-8")

    entries, _truncated = list_via_scandir(
        ws,
        workspace=ws,
        is_ignored=None,
        max_depth=2,
        dirs_only=False,
        include_ignored=True,
    )
    rels = {rel for rel, _ in entries}
    assert "packages/foo" in rels
    assert "packages/bar.txt" in rels  # depth 2
    assert "packages/foo/src/nested/deep.txt" not in rels


def test_glob_works_without_git_and_without_fd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe_nano.filesystem.workspace.list_via_fd",
        lambda *_a, **_k: None,
    )

    ws = tmp_path / "repo"
    ws.mkdir()
    assert not (ws / ".git").exists()
    (ws / "a.py").write_text("x", encoding="utf-8")

    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("*.py")
    assert result.error is None
    assert any(m["path"].endswith("a.py") and not m.get("is_dir") for m in (result.matches or []))


def test_glob_fd_path_used_when_available(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    (ws / "packages" / "alpha").mkdir(parents=True)

    abs_dir = str((ws / "packages" / "alpha").resolve())

    def fake_fd(*_a, **_k):
        return [(abs_dir, True)]

    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    with (
        patch("soothe_nano.filesystem.workspace.list_via_fd", side_effect=fake_fd),
        patch("soothe_nano.filesystem.workspace.list_via_scandir") as scandir_mock,
    ):
        result = fs.glob("packages/*/")
        scandir_mock.assert_not_called()
    matches = result.matches or []
    assert len(matches) == 1
    assert matches[0]["is_dir"] is True
    assert matches[0]["path"].endswith("alpha")


def test_glob_ignores_essential_excludes_on_scandir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe_nano.filesystem.workspace.list_via_fd",
        lambda *_a, **_k: None,
    )

    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "ok.txt").write_text("x", encoding="utf-8")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "pkg").mkdir()
    (ws / "node_modules" / "pkg" / "x.js").write_text("x", encoding="utf-8")

    fs = WorkspaceFilesystem(workspace=str(ws), virtual_mode=True)
    result = fs.glob("**/*")
    paths = [m["path"] for m in (result.matches or [])]
    assert any("ok.txt" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
