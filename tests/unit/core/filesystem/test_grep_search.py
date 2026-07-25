"""Tests for deepagents ripgrep resolution (nano no longer ships a grep shim)."""

from __future__ import annotations

from pathlib import Path

import pytest
from soothe_deepagents.backends.grep_search import (
    get_rg_bin,
    is_rg_available,
    reset_rg_bin_cache,
)


@pytest.fixture(autouse=True)
def _reset_rg_cache() -> None:
    reset_rg_bin_cache()
    yield
    reset_rg_bin_cache()


def test_is_rg_available_reflects_rg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_RG_PATH", raising=False)
    monkeypatch.delenv("DEEPAGENTS_RG_PATH", raising=False)
    monkeypatch.setattr(
        "soothe_deepagents.backends.grep_search.shutil.which",
        lambda _: None,
    )
    reset_rg_bin_cache()
    assert is_rg_available() is False
    assert get_rg_bin() is None

    monkeypatch.setattr(
        "soothe_deepagents.backends.grep_search.shutil.which",
        lambda name: "/usr/bin/rg" if name == "rg" else None,
    )
    reset_rg_bin_cache()
    assert is_rg_available() is True
    assert get_rg_bin() == "/usr/bin/rg"


def test_soothe_rg_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_rg = tmp_path / "custom-rg"
    custom_rg.write_text("#!/bin/sh\n", encoding="utf-8")
    custom_rg.chmod(0o755)
    monkeypatch.setenv("SOOTHE_RG_PATH", str(custom_rg))
    monkeypatch.delenv("DEEPAGENTS_RG_PATH", raising=False)
    monkeypatch.setattr(
        "soothe_deepagents.backends.grep_search.shutil.which",
        lambda _: "/usr/bin/rg",
    )
    reset_rg_bin_cache()
    assert get_rg_bin() == str(custom_rg)
