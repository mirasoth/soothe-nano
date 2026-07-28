"""Plan subagent LangGraph.

Readonly filesystem recon (optional), then agentic plan-design loops, then a
single delegate final message. Mutating tools are never bound (RFC-633).
"""

from __future__ import annotations

import logging
import operator
import uuid
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_nano.utils.llm.structured import invoke_structured_chat_typed
from soothe_nano.utils.progress import emit_progress

from .schemas import PlanRefinement, PlanSubagentConfig
from .tools import get_planner_readonly_tools

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class PlanEngineState(dict):
    """Graph state: ``messages`` satisfies CompiledSubAgent contract."""

    messages: Annotated[list[Any], add_messages]
    task_text: str
    plan_markdown: str
    plan_round: int
    finish_planning: bool
    findings: Annotated[list[str], operator.add]
    recon_round: int
    finish_recon: bool


_RECON_SYSTEM = """You are the **recon** phase of Soothe's plan subagent. Use readonly \
filesystem tools (ls, glob, grep, read_file, file_info) to gather just enough workspace \
context to draft a solid markdown plan for human review.

Rules:
- Prefer targeted searches; avoid huge dumps.
- When you have enough context (or tools cannot help), respond with a short prose summary \
and **no** tool calls.
- Never request write, edit, delete, or shell tools."""

_PLANNER_SYSTEM = """You are the **plan design** phase of Soothe's plan subagent. Produce an \
**execution-oriented markdown plan** for human discussion and approval: objective, ordered \
steps, dependencies, risks, and open questions.

Rules:
- Output the **full** plan in `plan_markdown` each round (not a diff), refined as you learn.
- Set `finish_planning` true when the plan is actionable and stable enough to hand to a human.
- You may use recon findings below; do not invent file paths that contradict findings.
- If context is thin, still produce the best plan you can and list assumptions explicitly."""


def _emit_tool_update(*, tool_call_id: str, name: str, args: dict[str, Any]) -> None:
    emit_progress(
        {
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": tool_call_id,
            "name": name,
            "args": dict(args or {}),
        },
        logger,
    )


def build_plan_engine(
    model: BaseChatModel,
    plan_config: PlanSubagentConfig,
    *,
    soothe_config: Any | None = None,
    workspace: str | None = None,
) -> Any:
    """Compile the plan subagent graph."""
    from soothe_nano.utils.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )

    llm_policy = llm_rate_limit_config_from(soothe_config)
    tools = (
        get_planner_readonly_tools(workspace)
        if plan_config.enable_recon and plan_config.max_recon_rounds > 0
        else []
    )
    tools_by_name = {getattr(t, "name", ""): t for t in tools}

    def ingest_task(state: dict[str, Any]) -> dict[str, Any]:
        text = ""
        for msg in reversed(state.get("messages") or []):
            if getattr(msg, "type", None) == "human":
                content = getattr(msg, "content", "")
                text = content if isinstance(content, str) else str(content)
                break
        if not text and state.get("messages"):
            last = state["messages"][-1]
            c = getattr(last, "content", "")
            text = c if isinstance(c, str) else str(c)
        logger.info("Plan subagent: ingested task (%d chars)", len(text))
        return {
            "task_text": text,
            "plan_markdown": "",
            "plan_round": 0,
            "finish_planning": False,
            "findings": [],
            "recon_round": 0,
            "finish_recon": not bool(tools),
        }

    async def recon_iteration(state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task_text", "")
        rr = int(state.get("recon_round", 0)) + 1
        prior = "\n\n".join(state.get("findings") or []) or "(none yet)"
        user = (
            f"## Delegated task\n{task}\n\n## Recon round\n{rr} / {plan_config.max_recon_rounds}\n\n"
            f"## Findings so far\n{prior}"
        )
        try:
            bound = model.bind_tools(list(tools_by_name.values()))

            async def _invoke() -> Any:
                return await bound.ainvoke(
                    [
                        SystemMessage(content=_RECON_SYSTEM),
                        HumanMessage(content=user),
                    ]
                )

            ai = await await_with_llm_call_policy(_invoke, config=llm_policy)
        except Exception:
            logger.exception("Plan subagent: recon model call failed")
            return {"recon_round": rr, "finish_recon": True, "findings": []}

        tool_calls = list(getattr(ai, "tool_calls", None) or [])
        if not tool_calls:
            summary = ""
            content = getattr(ai, "content", "")
            if isinstance(content, str):
                summary = content.strip()
            elif content:
                summary = str(content).strip()
            findings = [f"### Recon summary\n{summary}"] if summary else []
            logger.info("Plan subagent: recon finished at round %d (no tool calls)", rr)
            return {"recon_round": rr, "finish_recon": True, "findings": findings}

        new_findings: list[str] = []
        for tc in tool_calls:
            name = str(tc.get("name") or "")
            args = dict(tc.get("args") or {})
            call_id = str(tc.get("id") or f"call_{uuid.uuid4().hex[:12]}")
            _emit_tool_update(tool_call_id=call_id, name=name, args=args)
            tool = tools_by_name.get(name)
            if tool is None:
                result_text = f"Tool not available: {name}"
            else:
                try:
                    raw = await tool.ainvoke(args)
                    result_text = raw if isinstance(raw, str) else str(raw)
                except Exception as exc:  # noqa: BLE001
                    result_text = f"{type(exc).__name__}: {exc}"
            if len(result_text) > 4000:
                result_text = result_text[:4000] + "\n…(truncated)"
            new_findings.append(f"### {name}({args})\n{result_text}")
            # Satisfy tool-call protocol if messages are inspected later.
            _ = ToolMessage(content=result_text, tool_call_id=call_id)

        done = rr >= plan_config.max_recon_rounds
        logger.info(
            "Plan subagent: recon round %d complete (tools=%d finish=%s)",
            rr,
            len(tool_calls),
            done,
        )
        return {
            "recon_round": rr,
            "finish_recon": done,
            "findings": new_findings,
        }

    async def plan_iteration(state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task_text", "")
        pr = int(state.get("plan_round", 0)) + 1
        prev = (state.get("plan_markdown") or "").strip()
        findings = "\n\n".join(state.get("findings") or []) or "(no recon findings)"
        user = (
            f"## Delegated task\n{task}\n\n## Plan design round\n{pr} / {plan_config.max_plan_rounds}\n\n"
            f"## Recon findings\n{findings}\n\n"
            f"## Previous plan draft\n{prev or '(none — write initial plan)'}"
        )
        try:

            async def _invoke() -> PlanRefinement:
                return await invoke_structured_chat_typed(
                    model,
                    [
                        {"role": "system", "content": _PLANNER_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    PlanRefinement,
                )

            ref = await await_with_llm_call_policy(_invoke, config=llm_policy)
        except Exception:
            logger.exception("Plan subagent: planner structured output failed")
            ref = PlanRefinement(
                plan_markdown=f"## Plan\n\n1. Address: {task}\n",
                rationale="planner_failed_fallback",
                finish_planning=True,
            )

        done = bool(ref.finish_planning) or pr >= plan_config.max_plan_rounds
        logger.info(
            "Plan subagent: plan round %d complete (finish=%s, md_len=%d)",
            pr,
            done,
            len(ref.plan_markdown or ""),
        )
        return {
            "plan_round": pr,
            "plan_markdown": (ref.plan_markdown or "").strip(),
            "finish_planning": done,
        }

    def emit_final(state: dict[str, Any]) -> dict[str, Any]:
        body = (state.get("plan_markdown") or "").strip() or "(no plan produced)"
        return {"messages": [AIMessage(content=body)]}

    def route_after_ingest(state: dict[str, Any]) -> str:
        if state.get("finish_recon"):
            return "plan"
        return "recon"

    def route_after_recon(state: dict[str, Any]) -> str:
        if state.get("finish_recon"):
            return "plan"
        if int(state.get("recon_round", 0)) >= plan_config.max_recon_rounds:
            return "plan"
        return "recon"

    def route_after_plan(state: dict[str, Any]) -> str:
        if state.get("finish_planning"):
            return "done"
        if int(state.get("plan_round", 0)) >= plan_config.max_plan_rounds:
            return "done"
        return "plan"

    graph = StateGraph(PlanEngineState)
    graph.add_node("ingest_task", ingest_task)
    graph.add_node("recon_iteration", recon_iteration)
    graph.add_node("plan_iteration", plan_iteration)
    graph.add_node("emit_final", emit_final)

    graph.add_edge(START, "ingest_task")
    graph.add_conditional_edges(
        "ingest_task",
        route_after_ingest,
        {"recon": "recon_iteration", "plan": "plan_iteration"},
    )
    graph.add_conditional_edges(
        "recon_iteration",
        route_after_recon,
        {"recon": "recon_iteration", "plan": "plan_iteration"},
    )
    graph.add_conditional_edges(
        "plan_iteration",
        route_after_plan,
        {"plan": "plan_iteration", "done": "emit_final"},
    )
    graph.add_edge("emit_final", END)

    return graph.compile()
