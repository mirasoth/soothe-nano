"""Unit tests for plan subagent engine (RFC-618 / RFC-633)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe_nano.subagents.plan import engine as plan_engine
from soothe_nano.subagents.plan.engine import (
    PlanRefinement,
    PlanSubagentConfig,
    build_plan_engine,
)


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
async def test_plan_engine_logs_tool_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Orphan card gets tool updates only; tool calls are logged at INFO."""
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

    _patch_planner(
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
    with caplog.at_level(logging.INFO, logger="soothe_nano.subagents.plan.engine"):
        await graph.ainvoke({"messages": [HumanMessage(content="inventory the workspace")]})

    assert any(e.get("name") == "ls" for e in emitted)
    assert not any(str(e.get("type") or "").startswith("soothe.subagent.planner.") for e in emitted)
    assert any("[planner] tool ls" in r.message for r in caplog.records)
    assert any("[planner] tool ls →" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_plan_engine_emits_stage_progress_not_in_tool_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage progress uses subagent wire (status line); not tool_call.update rows."""
    _patch_planner(
        monkeypatch,
        planner_returns=PlanRefinement(plan_markdown="# Plan\nDone.", finish_planning=True),
    )
    wire_events: list[dict[str, Any]] = []
    tool_events: list[dict[str, Any]] = []

    def _capture_wire(payload: dict[str, Any], _logger: Any = None) -> None:
        wire_events.append(dict(payload))

    def _capture_tool(payload: dict[str, Any], _logger: Any = None) -> None:
        tool_events.append(dict(payload))

    monkeypatch.setattr(plan_engine, "emit_subagent_wire_event", _capture_wire)
    monkeypatch.setattr(plan_engine, "emit_progress", _capture_tool)

    graph = build_plan_engine(MagicMock(), _plan_only_config())
    await graph.ainvoke({"messages": [HumanMessage(content="parent task")]})

    progress = [e for e in wire_events if e.get("type") == "soothe.subagent.planner.progress"]
    assert progress
    assert any(e.get("phase") == "start" for e in progress)
    assert any(e.get("phase") == "draft" for e in progress)
    assert not any(
        str(e.get("type") or "").startswith("soothe.subagent.planner.") for e in tool_events
    )


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


def test_planner_prompts_require_solution_report_not_investigation() -> None:
    """Prompt contract: solution report with Changes; forbid investigate-roadmap steps."""
    assert "solution report" in plan_engine._PLANNER_SYSTEM.lower()
    assert "**Solution**" in plan_engine._PLANNER_SYSTEM
    assert "**Design principles**" in plan_engine._PLANNER_SYSTEM
    assert "**Architecture changes**" in plan_engine._PLANNER_SYSTEM
    assert "**Changes**" in plan_engine._PLANNER_SYSTEM
    assert "Forbidden as steps" in plan_engine._PLANNER_SYSTEM
    assert "diagnose" in plan_engine._PLANNER_SYSTEM.lower()
    assert "Do the reading **now**" in plan_engine._RECON_SYSTEM
    assert "investigation roadmap" in plan_engine._PLANNER_SYSTEM.lower()
    assert "module boundaries" in plan_engine._RECON_SYSTEM.lower()


@pytest.mark.asyncio
async def test_plan_iteration_user_prompt_forbids_reread_as_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft user blob tells the model not to schedule re-reading as Changes."""
    calls = _patch_planner(
        monkeypatch,
        planner_returns=PlanRefinement(
            plan_markdown="## Goal\n\nx\n\n## Solution\n\ny\n\n## Changes\n\n1. Edit a.py\n",
            finish_planning=True,
        ),
    )
    graph = build_plan_engine(MagicMock(), _plan_only_config())
    await graph.ainvoke({"messages": [HumanMessage(content="polish tips")]})
    blob = str(calls[0]).lower()
    assert "solution report" in blob
    assert "do not schedule re-reading" in blob
