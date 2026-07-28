"""planner subagent wire events."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_nano.events.catalog import register_event

SUBAGENT_PLANNER_PROGRESS = "soothe.subagent.planner.progress"


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

__all__ = [
    "SUBAGENT_PLANNER_PROGRESS",
    "PlannerProgressEvent",
]
