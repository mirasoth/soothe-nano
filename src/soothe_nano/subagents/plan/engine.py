"""Plan subagent LangGraph.

Readonly filesystem recon (optional), then agentic plan-design loops, then a
single delegate final message. Mutating tools are never bound (RFC-633).

Recon executes middleware tools via ``ToolNode`` so ``ToolRuntime`` is injected
(bare ``tool.ainvoke(args)`` fails FilesystemMiddleware tools).
"""

from __future__ import annotations

import logging
import operator
import uuid
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_nano.utils.llm.structured import invoke_structured_chat_typed
from soothe_nano.utils.progress import emit_progress
from soothe_nano.utils.subagent_emit import emit_subagent_wire_event
from soothe_nano.utils.text_preview import log_preview

from .events import PlannerProgressEvent
from .schemas import PlanRefinement, PlanSubagentConfig
from .tools import get_planner_readonly_tools

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_FINDING_TRUNCATE = 4000
_TOOL_ARGS_LOG_CHARS = 80


def _emit_planner_stage(
    phase: str,
    message: str,
    *,
    loop_count: int = 0,
    total_loops: int = 0,
) -> None:
    """Emit stage for the orphan card status line (CLI maps this; not an activity note)."""
    emit_subagent_wire_event(
        PlannerProgressEvent(
            phase=phase,
            message=message,
            loop_count=loop_count,
            total_loops=total_loops,
        ).to_dict(),
        logger,
    )


def _compact_tool_args(args: dict[str, Any]) -> str:
    """One short arg hint for logs (prefer path/pattern keys)."""
    for key in ("path", "file_path", "glob", "pattern", "query", "regex", "file"):
        val = args.get(key)
        if val is None or val == "":
            continue
        return f"{key}={log_preview(str(val), _TOOL_ARGS_LOG_CHARS)}"
    if not args:
        return ""
    return log_preview(str(args), _TOOL_ARGS_LOG_CHARS)


def _emit_tool_update(*, tool_call_id: str, name: str, args: dict[str, Any]) -> None:
    """Emit tool row for the orphan SubAgent card and log the call."""
    hint = _compact_tool_args(args)
    logger.info("[planner] tool %s%s", name, f" {hint}" if hint else "")
    emit_progress(
        {
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": tool_call_id,
            "name": name,
            "args": dict(args or {}),
        },
        logger,
    )


def _log_tool_result(tm: ToolMessage) -> None:
    name = str(getattr(tm, "name", None) or "tool")
    content = getattr(tm, "content", "")
    result_text = content if isinstance(content, str) else str(content)
    logger.info("[planner] tool %s → %d chars", name, len(result_text))


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


def _truncate_finding(text: str) -> str:
    if len(text) <= _FINDING_TRUNCATE:
        return text
    return text[:_FINDING_TRUNCATE] + "\n…(truncated)"


def _tool_calls_from_message(msg: Any) -> list[dict[str, Any]]:
    raw = getattr(msg, "tool_calls", None) or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for tc in raw:
        if isinstance(tc, dict):
            out.append(tc)
        else:
            out.append(
                {
                    "name": getattr(tc, "name", "") or "",
                    "args": dict(getattr(tc, "args", None) or {}),
                    "id": getattr(tc, "id", "") or "",
                }
            )
    return out


def _format_tool_findings(ai: Any, tool_messages: list[ToolMessage]) -> list[str]:
    """Build finding blocks from ToolNode outputs paired with the prior AI tool_calls."""
    by_id = {
        str(tc.get("id") or ""): tc
        for tc in _tool_calls_from_message(ai)
        if str(tc.get("id") or "")
    }
    findings: list[str] = []
    for tm in tool_messages:
        call_id = str(getattr(tm, "tool_call_id", "") or "")
        tc = by_id.get(call_id) or {}
        name = str(getattr(tm, "name", None) or tc.get("name") or "tool")
        args = dict(tc.get("args") or {})
        content = getattr(tm, "content", "")
        result_text = content if isinstance(content, str) else str(content)
        findings.append(f"### {name}({args})\n{_truncate_finding(result_text)}")
    return findings


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
    recon_tool_node = ToolNode(list(tools_by_name.values())) if tools_by_name else None

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
        logger.info(
            "[planner] start chars=%d recon=%s max_recon=%d max_plan=%d",
            len(text),
            "on" if tools_by_name else "off",
            plan_config.max_recon_rounds if tools_by_name else 0,
            plan_config.max_plan_rounds,
        )
        _emit_planner_stage("start", "starting")
        return {
            "task_text": text,
            "plan_markdown": "",
            "plan_round": 0,
            "finish_planning": False,
            "findings": [],
            "recon_round": 0,
            "finish_recon": not bool(tools_by_name),
        }

    async def recon_model(state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task_text", "")
        rr = int(state.get("recon_round", 0)) + 1
        prior = "\n\n".join(state.get("findings") or []) or "(none yet)"
        user = (
            f"## Delegated task\n{task}\n\n## Recon round\n{rr} / {plan_config.max_recon_rounds}\n\n"
            f"## Findings so far\n{prior}"
        )
        logger.info("[planner] recon %d/%d", rr, plan_config.max_recon_rounds)
        _emit_planner_stage(
            "recon",
            f"recon {rr}/{plan_config.max_recon_rounds}",
            loop_count=rr,
            total_loops=plan_config.max_recon_rounds,
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
            logger.exception("[planner] recon model call failed")
            return {"recon_round": rr, "finish_recon": True, "findings": []}

        tool_calls = _tool_calls_from_message(ai)
        if not tool_calls:
            summary = ""
            content = getattr(ai, "content", "")
            if isinstance(content, str):
                summary = content.strip()
            elif content:
                summary = str(content).strip()
            findings = [f"### Recon summary\n{summary}"] if summary else []
            logger.info("[planner] recon done (no tools) round=%d", rr)
            return {
                "recon_round": rr,
                "finish_recon": True,
                "findings": findings,
                "messages": [ai if isinstance(ai, AIMessage) else AIMessage(content=summary)],
            }

        for tc in tool_calls:
            name = str(tc.get("name") or "")
            args = dict(tc.get("args") or {})
            call_id = str(tc.get("id") or f"call_{uuid.uuid4().hex[:12]}")
            if not tc.get("id"):
                tc["id"] = call_id
            _emit_tool_update(tool_call_id=call_id, name=name, args=args)

        # Ensure ids exist on the AIMessage for ToolNode pairing.
        if isinstance(ai, AIMessage) and ai.tool_calls:
            normalized = []
            for tc in ai.tool_calls:
                if isinstance(tc, dict):
                    entry = dict(tc)
                    if not entry.get("id"):
                        entry["id"] = f"call_{uuid.uuid4().hex[:12]}"
                    normalized.append(entry)
                else:
                    normalized.append(tc)
            ai = AIMessage(content=ai.content, tool_calls=normalized)

        return {
            "recon_round": rr,
            "finish_recon": False,
            "messages": [ai],
        }

    def recon_collect(state: dict[str, Any]) -> dict[str, Any]:
        """Harvest ToolNode ``ToolMessage`` outputs into recon findings."""
        msgs = list(state.get("messages") or [])
        tool_msgs: list[ToolMessage] = []
        ai_for_calls: Any = None
        for msg in reversed(msgs):
            if isinstance(msg, ToolMessage):
                tool_msgs.append(msg)
                continue
            if getattr(msg, "type", None) == "ai" or isinstance(msg, AIMessage):
                ai_for_calls = msg
            break
        tool_msgs.reverse()
        findings = _format_tool_findings(ai_for_calls, tool_msgs) if tool_msgs else []
        for tm in tool_msgs:
            _log_tool_result(tm)
        rr = int(state.get("recon_round", 0))
        done = rr >= plan_config.max_recon_rounds
        logger.info(
            "[planner] recon tools n=%d round=%d%s",
            len(tool_msgs),
            rr,
            " → draft" if done else "",
        )
        return {"findings": findings, "finish_recon": done}

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
        logger.info("[planner] drafting %d/%d", pr, plan_config.max_plan_rounds)
        _emit_planner_stage(
            "draft",
            f"drafting {pr}/{plan_config.max_plan_rounds}",
            loop_count=pr,
            total_loops=plan_config.max_plan_rounds,
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
            logger.exception("[planner] draft structured output failed")
            ref = PlanRefinement(
                plan_markdown=f"## Plan\n\n1. Address: {task}\n",
                rationale="planner_failed_fallback",
                finish_planning=True,
            )

        done = bool(ref.finish_planning) or pr >= plan_config.max_plan_rounds
        markdown = (ref.plan_markdown or "").strip()
        logger.info(
            "[planner] draft %d/%d md=%d finish=%s",
            pr,
            plan_config.max_plan_rounds,
            len(markdown),
            done,
        )
        return {
            "plan_round": pr,
            "plan_markdown": markdown,
            "finish_planning": done,
        }

    def emit_final(state: dict[str, Any]) -> dict[str, Any]:
        body = (state.get("plan_markdown") or "").strip() or "(no plan produced)"
        logger.info(
            "[planner] done rounds=%d md=%d",
            int(state.get("plan_round", 0) or 0),
            len(body),
        )
        return {"messages": [AIMessage(content=body)]}

    def route_after_ingest(state: dict[str, Any]) -> str:
        if state.get("finish_recon"):
            return "plan"
        return "recon"

    def route_after_recon_model(state: dict[str, Any]) -> str:
        if state.get("finish_recon"):
            return "plan"
        if recon_tool_node is None:
            return "plan"
        msgs = state.get("messages") or []
        if not msgs:
            return "plan"
        if _tool_calls_from_message(msgs[-1]):
            return "tools"
        return "plan"

    def route_after_recon_collect(state: dict[str, Any]) -> str:
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
    graph.add_node("plan_iteration", plan_iteration)
    graph.add_node("emit_final", emit_final)

    graph.add_edge(START, "ingest_task")
    if recon_tool_node is not None:
        graph.add_node("recon_model", recon_model)
        graph.add_node("recon_tools", recon_tool_node)
        graph.add_node("recon_collect", recon_collect)
        graph.add_conditional_edges(
            "ingest_task",
            route_after_ingest,
            {"recon": "recon_model", "plan": "plan_iteration"},
        )
        graph.add_conditional_edges(
            "recon_model",
            route_after_recon_model,
            {"tools": "recon_tools", "plan": "plan_iteration"},
        )
        graph.add_edge("recon_tools", "recon_collect")
        graph.add_conditional_edges(
            "recon_collect",
            route_after_recon_collect,
            {"recon": "recon_model", "plan": "plan_iteration"},
        )
    else:
        graph.add_edge("ingest_task", "plan_iteration")
    graph.add_conditional_edges(
        "plan_iteration",
        route_after_plan,
        {"plan": "plan_iteration", "done": "emit_final"},
    )
    graph.add_edge("emit_final", END)

    return graph.compile()
