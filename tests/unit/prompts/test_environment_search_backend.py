"""Tests for environment context XML (search backend surface)."""

from __future__ import annotations

from unittest.mock import patch

from soothe_nano.prompts.context_xml import ContextXml


def test_environment_includes_ripgrep_search_backend() -> None:
    with patch(
        "soothe_deepagents.backends.grep_search.is_rg_available",
        return_value=True,
    ):
        section = ContextXml.build_environment(model="test-model")
    assert "<search_backend>ripgrep</search_backend>" in section
    assert "<ENVIRONMENT>" in section


def test_environment_includes_python_fallback_search_backend() -> None:
    with patch(
        "soothe_deepagents.backends.grep_search.is_rg_available",
        return_value=False,
    ):
        section = ContextXml.build_environment(model="test-model")
    assert "<search_backend>python_fallback</search_backend>" in section
