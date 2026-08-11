"""ComputerUse subagent wire events (curated subagent event types)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SubagentEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_nano.events.catalog import register_event

# Event type constants defined locally (self-contained pattern)
SUBAGENT_COMPUTER_USE_STARTED = "soothe.subagent.computer_use.started"
SUBAGENT_COMPUTER_USE_COMPLETED = "soothe.subagent.computer_use.completed"
SUBAGENT_COMPUTER_USE_STEP_COMPLETED = "soothe.subagent.computer_use.step.completed"


class ComputerUseStartedEvent(SubagentEvent):
    """ComputerUse run started."""

    type: Literal["soothe.subagent.computer_use.started"] = SUBAGENT_COMPUTER_USE_STARTED
    task_preview: str = ""

    model_config = ConfigDict(extra="allow")


class ComputerUseCompletedEvent(SubagentEvent):
    """ComputerUse run finished."""

    type: Literal["soothe.subagent.computer_use.completed"] = SUBAGENT_COMPUTER_USE_COMPLETED
    duration_ms: int = 0
    success: bool = True
    summary: str = ""

    model_config = ConfigDict(extra="allow")


class ComputerUseStepCompletedEvent(SubagentEvent):
    """One desktop automation step completed (metadata only)."""

    type: Literal["soothe.subagent.computer_use.step.completed"] = (
        SUBAGENT_COMPUTER_USE_STEP_COMPLETED
    )
    step_index: int = 0
    tool_name: str = ""
    action_preview: str = ""
    coordinate: str = ""
    screenshot_path: str = ""
    status: str = "done"
    duration_ms: int = 0

    model_config = ConfigDict(extra="allow")


# Foundation register_event → NORMAL client-wire visibility for stream forwards.
register_event(
    ComputerUseStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="ComputerUse: {task_preview}",
)
register_event(
    ComputerUseCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="ComputerUse: {summary}",
)
register_event(
    ComputerUseStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{tool_name}: {action_preview}",
)

__all__ = [
    "SUBAGENT_COMPUTER_USE_COMPLETED",
    "SUBAGENT_COMPUTER_USE_STARTED",
    "SUBAGENT_COMPUTER_USE_STEP_COMPLETED",
    "ComputerUseCompletedEvent",
    "ComputerUseStartedEvent",
    "ComputerUseStepCompletedEvent",
]
