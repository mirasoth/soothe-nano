"""Tests for ephemeral execute-stream env gate and durability kwargs."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver

from soothe_nano.agent.core_agent import (
    SootheNanoAgent,
    _langgraph_durability_kwargs,
    ephemeral_execute_stream_enabled,
)


def test_ephemeral_execute_stream_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", raising=False)
    assert ephemeral_execute_stream_enabled() is True


def test_ephemeral_execute_stream_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "0")
    assert ephemeral_execute_stream_enabled() is False


def test_langgraph_durability_kwargs_omitted_without_checkpointer() -> None:
    graph = MagicMock()
    graph.checkpointer = None
    assert _langgraph_durability_kwargs(graph, "exit") == {}
    assert _langgraph_durability_kwargs(graph, None) == {}


def test_langgraph_durability_kwargs_included_with_checkpointer() -> None:
    graph = MagicMock()
    graph.checkpointer = MagicMock(spec=BaseCheckpointSaver)
    assert _langgraph_durability_kwargs(graph, "exit") == {"durability": "exit"}
    assert _langgraph_durability_kwargs(graph, None) == {}


@pytest.mark.asyncio
async def test_execute_stream_omits_durability_on_ephemeral_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "1")
    call_kwargs: list[dict[str, Any]] = []

    async def mock_astream(_input: Any, _config: Any, **kwargs: Any):
        call_kwargs.append(kwargs)
        if False:  # pragma: no cover — make this an async generator
            yield None

    main_graph = MagicMock()
    main_graph.checkpointer = MagicMock(spec=BaseCheckpointSaver)
    execute_graph = MagicMock()
    execute_graph.checkpointer = None
    execute_graph.astream = mock_astream

    agent = SootheNanoAgent(
        graph=main_graph,
        config=MagicMock(),
        execute_graph=execute_graph,
    )
    stream = agent.execute_stream("hello")
    async for _ in stream:
        pass

    assert call_kwargs
    assert "durability" not in call_kwargs[0]
    assert call_kwargs[0].get("subgraphs") is False
