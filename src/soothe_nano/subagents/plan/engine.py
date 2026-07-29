"""Plan subagent: grounded recon → solution report → emit for review.

Readonly filesystem tools only (no write/edit/delete/execute). Recon evidence
stays internal; the final message is a **solution report** for the user goal
(what to change and why), for human Approve / Reject / More comments
(RFC-633 / IG-659). Not an investigation roadmap of further reads.

Recon runs middleware tools via ``ToolNode`` so ``ToolRuntime`` is injected
(bare ``tool.ainvoke(args)`` fails FilesystemMiddleware tools).
"""

from __future__ import annotations

import logging
import operator
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, ConfigDict, Field
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe_nano.config import SubagentConfig
from soothe_nano.events.catalog import register_event
from soothe_nano.utils.llm.structured import invoke_structured_chat_typed
from soothe_nano.utils.progress import emit_progress
from soothe_nano.utils.subagent_emit import emit_subagent_wire_event
from soothe_nano.utils.text_preview import log_preview

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_FINDING_TRUNCATE = 4000
_TOOL_ARGS_LOG_CHARS = 80

PLANNER_READONLY_TOOL_NAMES: tuple[str, ...] = (
    "glob",
    "grep",
    "ls",
    "read_file",
    "file_info",
)

SUBAGENT_PLANNER_PROGRESS = "soothe.subagent.planner.progress"


# ---------------------------------------------------------------------------
# Schemas & wire events
# ---------------------------------------------------------------------------


class PlanSubagentConfig(BaseModel):
    """YAML configuration under ``subagents.planner.config``."""

    max_plan_rounds: int = Field(
        default=5,
        ge=1,
        le=24,
        description="Maximum proposal-design iterations before the draft is emitted.",
    )
    enable_recon: bool = Field(
        default=True,
        description="When true, run readonly filesystem recon before drafting (RFC-633).",
    )
    max_recon_rounds: int = Field(
        default=4,
        ge=0,
        le=16,
        description="Maximum bind_tools recon rounds (0 skips recon even if enable_recon).",
    )


class PlanRefinement(BaseModel):
    """Structured output for one solution-report iteration."""

    plan_markdown: str = Field(
        description=(
            "Full solution report markdown for the user goal: Goal, Solution, "
            "Design principles (or None), Architecture changes (or None), Changes "
            "(concrete edit/remove/add steps — never read/diagnose steps), Evidence, "
            "Risks & assumptions, Open questions."
        ),
    )
    rationale: str = Field(
        default="",
        description="Why this solution completes the goal, or what changed this round.",
    )
    finish_planning: bool = Field(
        description="Set true when the solution report is stable enough for human review.",
    )


class PlannerProgressEvent(SootheEvent):
    """Planner stage signal for the orphan card status line (not activity notes)."""

    type: Literal["soothe.subagent.planner.progress"] = SUBAGENT_PLANNER_PROGRESS  # type: ignore[assignment]
    phase: str = ""
    loop_count: int = 0
    total_loops: int = 0
    message: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    PlannerProgressEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{phase}: {message}",
)


# ---------------------------------------------------------------------------
# Readonly tools
# ---------------------------------------------------------------------------


def get_planner_readonly_tools(workspace: str | None = None) -> list[Any]:
    """Build the planner recon tool surface (no write/edit/delete/execute).

    Args:
        workspace: Workspace root; defaults to the process cwd.

    Returns:
        Ordered langchain tool instances present on ``SootheFilesystemMiddleware``.
    """
    from soothe_deepagents.backends.filesystem import FilesystemBackend

    from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

    root = workspace or os.getcwd()
    backend = FilesystemBackend(root_dir=Path(root), virtual_mode=False)
    middleware = SootheFilesystemMiddleware(
        backend=backend,
        backup_enabled=False,
        workspace_root=root,
    )
    by_name = {getattr(t, "name", ""): t for t in middleware.tools}
    tools = [by_name[name] for name in PLANNER_READONLY_TOOL_NAMES if name in by_name]
    missing = [n for n in PLANNER_READONLY_TOOL_NAMES if n not in by_name]
    if missing:
        logger.debug("Planner readonly tools missing from middleware: %s", missing)
    return tools


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plan_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build the plan ``CompiledSubAgent`` spec.

    Args:
        model: Primary chat model for proposal-design loops (resolver passes
            ``subagents.planner.model`` when set, else ``model_role``, default ``think``).
        config: Soothe configuration.
        context: Optional resolver context (``work_dir`` / ``workspace``).

    Returns:
        Dict with ``name``, ``description``, and ``runnable`` graph.
    """
    workspace = str(context.get("work_dir") or context.get("workspace") or "").strip() or None
    sub_cfg = config.subagents.get("planner", SubagentConfig())
    plan_opts = PlanSubagentConfig(**sub_cfg.config)

    runnable = build_plan_engine(model, plan_opts, soothe_config=config, workspace=workspace)

    return {
        "name": "planner",
        "description": (
            "Write a reviewable solution report for the user goal: readonly recon, "
            "then Solution plus Design principles / Architecture changes when needed, "
            "and concrete Changes (not an investigation roadmap) for Approve / Reject / "
            "More comments."
        ),
        "runnable": runnable,
    }


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


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


_RECON_SYSTEM = """You are the **grounding** phase of Soothe's planner. Use readonly \
filesystem tools (ls, glob, grep, read_file, file_info) to gather the facts needed \
to write a **solution report** that completes the user's goal.

Rules:
- Do the reading **now**. The next phase must already know enough to prescribe \
concrete edits — and, when relevant, design principles and architecture deltas — \
it must not schedule "read X / diagnose Y" as work.
- Prefer targeted searches and short reads; avoid huge dumps.
- When the goal implies structural work, note module boundaries, dependency \
direction, and existing patterns that the solution must respect or change.
- Stop when you can state the fix (which files change and how), or tools cannot help: \
respond with a short prose summary of the solution-relevant facts and **no** tool calls.
- Never request write, edit, delete, or shell tools."""

_PLANNER_SYSTEM = """You are the **solution report** writer for Soothe's planner. \
Given the user goal and grounding evidence (already collected), write the **answer** \
the human reviews: what will be done to complete the goal — not a research plan.

The deliverable is a **solution report**, not an investigation roadmap.

Required markdown sections (full document every round, not a diff):
1. **Goal** — restated user objective (one short paragraph)
2. **Solution** — the decided design / outcome (2–6 sentences). State what will be \
true when the goal is complete. Do **not** say "we will first read / diagnose / \
investigate"; recon already happened.
3. **Design principles** — concise bullets for product, UX, or engineering principles \
this solution upholds or introduces (e.g. single surface for tips, no inner scroll, \
package boundary). Use `None` when the change is purely mechanical with no principle \
worth stating.
4. **Architecture changes** — structural deltas when needed: module/layout moves, \
new/removed components, dependency or data-flow shifts, API/contract changes. Prefer \
workspace-relative paths. Use `None` when the work stays within existing structure \
with no boundary or topology change.
5. **Changes** — ordered implementation steps. Each step MUST be a concrete change \
(edit / add / remove / rename / rewire) naming workspace-relative paths and the \
intended delta. Forbidden as steps: read, open, inspect, understand, trace, \
diagnose, "determine whether", "find out", or any further recon.
6. **Evidence** — brief citations from grounding (paths/symbols already seen)
7. **Risks & assumptions**
8. **Open questions** — only if truly blocking; otherwise "None"

When to fill Design principles / Architecture changes (not None):
- Goal asks to polish, redesign, restructure, unify, or change behavior across \
modules — state the governing principles and any structural moves.
- Goal is a tiny local fix (typo, one-line bug) — `None` is correct for both.

Anti-patterns (reject these shapes):
- Solution/Changes that mostly schedule more reading of files already (or still) \
reachable by recon tools.
- Steps like "Read tips.py to understand…" or "Diagnose location issues…".
- Dumping raw tool output instead of a solution.
- Padding Design principles / Architecture with vague slogans unrelated to the goal.

Good Changes example (shape only):
1. Keep tip data in `…/tui/tips.py`; render tips only from the status footer widget.
2. Remove tip mounting from welcome / startup surfaces so tips appear in one place.
3. Adjust footer CSS for spacing and narrow-terminal wrapping.

Rules:
- Output the full report in `plan_markdown` each round.
- Set `finish_planning` true when the report is stable enough for human review.
- Ground paths in evidence; do not invent paths that contradict it. Prefer \
workspace-relative paths over absolute machine paths.
- If evidence is thin, still write the best solution and list assumptions — do not \
pad with investigation steps."""


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
    """Build grounding blocks from ToolNode outputs paired with the prior AI tool_calls."""
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
            f"## User goal\n{task}\n\n## Grounding round\n{rr} / {plan_config.max_recon_rounds}\n\n"
            f"## Evidence so far (internal)\n{prior}"
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
            findings = [f"### Grounding summary\n{summary}"] if summary else []
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
        findings = "\n\n".join(state.get("findings") or []) or "(no grounding evidence)"
        user = (
            f"## User goal\n{task}\n\n"
            f"## Solution report round\n{pr} / {plan_config.max_plan_rounds}\n\n"
            f"## Grounding evidence (already collected — cite in Evidence; do not "
            f"schedule re-reading as Changes)\n{findings}\n\n"
            f"## Previous solution report draft\n"
            f"{prev or '(none — write the initial solution report: Goal, Solution, Design principles, Architecture changes, Changes, …)'}"
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
                plan_markdown=(
                    f"## Goal\n\n{task}\n\n"
                    f"## Solution\n\nComplete the goal above with the best available approach.\n\n"
                    f"## Design principles\n\nNone\n\n"
                    f"## Architecture changes\n\nNone\n\n"
                    f"## Changes\n\n1. Implement the work required to satisfy: {task}\n\n"
                    f"## Evidence\n\n(none — planner fallback)\n\n"
                    f"## Risks & assumptions\n\nReport generated after a draft failure.\n\n"
                    f"## Open questions\n\nNone.\n"
                ),
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
        body = (state.get("plan_markdown") or "").strip() or "(no solution report produced)"
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
