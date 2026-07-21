"""Unit tests for wizsearch_search limit / max_results_per_engine aliases."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from soothe_nano.toolkits.wizsearch import (
    WizsearchSearchInput,
    WizsearchSearchTool,
    _resolve_max_results_per_engine,
)


def test_resolve_max_results_prefers_max_results_per_engine() -> None:
    assert (
        _resolve_max_results_per_engine(
            default=10,
            limit=3,
            max_results_per_engine=7,
        )
        == 7
    )


def test_resolve_max_results_uses_limit_alias() -> None:
    assert _resolve_max_results_per_engine(default=10, limit=5) == 5


def test_resolve_max_results_falls_back_to_default() -> None:
    assert _resolve_max_results_per_engine(default=10) == 10


def test_search_input_schema_includes_limit() -> None:
    schema = WizsearchSearchInput.model_json_schema()
    props = schema["properties"]
    assert "query" in props
    assert "limit" in props
    assert "max_results_per_engine" in props
    assert "timeout_seconds" in props


def test_search_tool_has_args_schema() -> None:
    tool = WizsearchSearchTool()
    assert tool.args_schema is WizsearchSearchInput


@pytest.mark.asyncio
async def test_arun_accepts_limit_alias() -> None:
    """LLM-generated ``limit`` must not raise TypeError on _arun."""
    tool = WizsearchSearchTool()
    with patch(
        "soothe_nano.toolkits.wizsearch.perform_wizsearch_search",
        new_callable=AsyncMock,
        return_value="ok",
    ) as mock_search:
        result = await tool._arun(query="python asyncio", limit=5)

    assert result == "ok"
    mock_search.assert_awaited_once()
    kwargs = mock_search.await_args.kwargs
    assert kwargs["query"] == "python asyncio"
    assert kwargs["max_results_per_engine"] == 5


@pytest.mark.asyncio
async def test_arun_max_results_per_engine_still_works() -> None:
    tool = WizsearchSearchTool()
    with patch(
        "soothe_nano.toolkits.wizsearch.perform_wizsearch_search",
        new_callable=AsyncMock,
        return_value="ok",
    ) as mock_search:
        result = await tool._arun(query="python", max_results_per_engine=3)

    assert result == "ok"
    assert mock_search.await_args.kwargs["max_results_per_engine"] == 3


def test_run_accepts_limit_alias() -> None:
    tool = WizsearchSearchTool()
    with patch(
        "soothe_nano.toolkits.wizsearch.perform_wizsearch_search",
        new_callable=AsyncMock,
        return_value="ok",
    ) as mock_search:
        result = tool._run(query="python", limit=4)

    assert result == "ok"
    assert mock_search.await_args.kwargs["max_results_per_engine"] == 4
