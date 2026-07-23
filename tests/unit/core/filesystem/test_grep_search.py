"""Tests for thin grep helpers over deepagents search."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_nano.filesystem.grep_search import (
    get_rg_bin,
    is_grep_available,
    reset_grep_backend_cache,
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


def test_local_grep_uses_backend_search(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle\n")
    LocalFilesystem(workspace=tmp_path, virtual_mode=True)
