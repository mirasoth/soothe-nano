"""Plan subagent package.

Intake planner: readonly grounding → solution report for human review.
"""

from __future__ import annotations

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from .engine import (  # noqa: F401 — register soothe.subagent.planner.* on import
    PLANNER_READONLY_TOOL_NAMES,
    SUBAGENT_PLANNER_PROGRESS,
    PlannerProgressEvent,
    PlanRefinement,
    PlanSubagentConfig,
    build_plan_engine,
    create_plan_subagent,
    get_planner_readonly_tools,
)

__all__ = [
    "PLANNER_READONLY_TOOL_NAMES",
    "PlanPlugin",
    "PlanRefinement",
    "PlanSubagentConfig",
    "PlannerProgressEvent",
    "SUBAGENT_PLANNER_PROGRESS",
    "build_plan_engine",
    "create_plan_subagent",
    "get_planner_readonly_tools",
]


@plugin(
    name="planner",
    version="1.0.0",
    description="Solution-report planner subagent",
    trust_level="built-in",
)
class PlanPlugin:
    """Built-in planner subagent plugin."""

    async def on_load(self, context: Any) -> None:
        """Record load."""
        context.logger.info("Loaded planner subagent v1.0.0")

    @subagent(
        name="planner",
        description=(
            "Write a reviewable solution report for the user goal using readonly "
            "workspace tools: Solution, Design principles / Architecture changes when "
            "needed, and concrete Changes (not an investigation roadmap) for "
            "Approve / Reject / comments."
        ),
        triggers=["planner", "solution report", "propose plan", "roadmap", "break down"],
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        """Create plan subagent runnable."""
        ctx = {
            "work_dir": getattr(context, "work_dir", ""),
        }
        return create_plan_subagent(model, config, ctx)
