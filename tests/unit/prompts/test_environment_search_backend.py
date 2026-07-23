"""Tests for environment context XML (search backend surface)."""

from __future__ import annotations

from unittest.mock import patch

from soothe_nano.prompts.context_xml import build_soothe_environment_section


def test_environment_includes_ripgrep_search_backend() -> None:
    with patch(
        "soothe_nano.filesystem.grep_search.is_grep_available",
        return_value=True,
    ):
        section = build_soothe_environment_section(model="test-model")
    assert "<search_backend>ripgrep</search_backend>" in section
    assert "<ENVIRONMENT>" in section


def test_environment_includes_python_fallback_search_backend() -> None:
    with patch(
        "soothe_nano.filesystem.grep_search.is_grep_available",
        return_value=False,
    ):
        section = build_soothe_environment_section(model="test-model")
    assert "<search_backend>python_fallback</search_backend>" in section
