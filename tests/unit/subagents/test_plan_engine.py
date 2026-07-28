"""Unit tests for plan subagent engine (RFC-618 / RFC-633)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe_nano.subagents.plan import engine as plan_engine
from soothe_nano.subagents.plan.engine import build_plan_engine
from soothe_nano.subagents.plan.schemas import PlanRefinement, PlanSubagentConfig


def _patch_planner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    planner_returns: list[PlanRefinement] | PlanRefinement,
) -> list[Any]:
    planner_seq: list[PlanRefinement] = (
        list(planner_returns) if isinstance(planner_returns, list) else [planner_returns]
    )
    calls: list[Any] = []

    async def _fake(_model: Any, messages: Any, schema: type[Any]) -> Any:
        if schema is PlanRefinement:
            calls.append(messages)
            return planner_seq.pop(0) if len(planner_seq) > 1 else planner_seq[0]
        raise AssertionError(f"unexpected schema: {schema}")

    monkeypatch.setattr(plan_engine, "invoke_structured_chat_typed", _fake)
    return calls


def _plan_only_config(**kwargs: Any) -> PlanSubagentConfig:
    return PlanSubagentConfig(enable_recon=False, **kwargs)


@pytest.mark.asyncio
async def test_plan_engine_produces_markdown_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan subagent runs plan-design loop and returns markdown."""
    calls = _patch_planner(
        monkeypatch,
        planner_returns=PlanRefinement(plan_markdown="# Plan\nDone.", finish_planning=True),
    )

    graph = build_plan_engine(MagicMock(), _plan_only_config())
    out = await graph.ainvoke({"messages": [HumanMessage(content="parent task")]})

    assert len(calls) == 1
    assert "Plan" in out["messages"][-1].content


@pytest.mark.asyncio
async def test_plan_engine_multi_round_refinement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple plan rounds run before finish."""
    calls = _patch_planner(
        monkeypatch,
        planner_returns=[
            PlanRefinement(plan_markdown="# Draft", finish_planning=False),
            PlanRefinement(plan_markdown="# Final", finish_planning=True),
        ],
    )

    graph = build_plan_engine(MagicMock(), _plan_only_config(max_plan_rounds=5))
    out = await graph.ainvoke({"messages": [HumanMessage(content="task")]})

    assert len(calls) == 2
    assert "Final" in out["messages"][-1].content


@pytest.mark.asyncio
async def test_plan_engine_recon_toolnode_executes_ls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Recon runs middleware tools via ToolNode (ToolRuntime injected)."""
    (tmp_path / "alpha.txt").write_text("hello\n", encoding="utf-8")

    emitted: list[dict[str, Any]] = []

    def _capture(payload: dict[str, Any], _logger: Any = None) -> None:
        emitted.append(dict(payload))

    monkeypatch.setattr(plan_engine, "emit_progress", _capture)

    recon_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "ls",
                "args": {"path": "."},
                "id": "call_ls1",
                "type": "tool_call",
            }
        ],
    )
    summary_ai = AIMessage(content="Workspace has alpha.txt")

    bound = MagicMock()
    bound.ainvoke = AsyncMock(side_effect=[recon_ai, summary_ai])
    model = MagicMock()
    model.bind_tools = MagicMock(return_value=bound)

    planner_calls = _patch_planner(
        monkeypatch,
        planner_returns=PlanRefinement(
            plan_markdown="# Plan\n1. Use alpha.txt\n",
            finish_planning=True,
        ),
    )

    graph = build_plan_engine(
        model,
        PlanSubagentConfig(enable_recon=True, max_recon_rounds=4),
        workspace=str(tmp_path),
    )
    out = await graph.ainvoke({"messages": [HumanMessage(content="inventory the workspace")]})

    findings = "\n".join(out.get("findings") or [])
    assert "alpha.txt" in findings
    assert "TypeError" not in findings
    assert "runtime" not in findings.lower()
    assert any(e.get("name") == "ls" for e in emitted)
    assert bound.ainvoke.await_count == 2
    assert len(planner_calls) == 1
    user_blob = str(planner_calls[0])
    assert "alpha.txt" in user_blob
    assert "Plan" in out["messages"][-1].content


@pytest.mark.asyncio
async def test_plan_engine_recon_disabled_skips_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """enable_recon=False never binds or invokes filesystem tools."""
    bind = MagicMock()
    model = MagicMock()
    model.bind_tools = bind
    _patch_planner(
        monkeypatch,
        planner_returns=PlanRefinement(plan_markdown="# X", finish_planning=True),
    )
    graph = build_plan_engine(model, _plan_only_config())
    await graph.ainvoke({"messages": [HumanMessage(content="t")]})
    bind.assert_not_called()
