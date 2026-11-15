"""BrowserUse subagent wire events (curated subagent event types)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe_nano.core.events import SubagentEvent
from soothe_nano.core.verbosity import VerbosityTier
from soothe_nano.events.catalog import register_event

# Event type constants defined locally (self-contained pattern)
SUBAGENT_BROWSER_USE_STARTED = "soothe.subagent.browser_use.started"
SUBAGENT_BROWSER_USE_COMPLETED = "soothe.subagent.browser_use.completed"


class BrowserUseStartedEvent(SubagentEvent):
    """BrowserUse run started."""

    type: Literal["soothe.subagent.browser_use.started"] = SUBAGENT_BROWSER_USE_STARTED
    task_preview: str = ""

    model_config = ConfigDict(extra="allow")


class BrowserUseCompletedEvent(SubagentEvent):
    """BrowserUse run finished."""

    type: Literal["soothe.subagent.browser_use.completed"] = SUBAGENT_BROWSER_USE_COMPLETED
    duration_ms: int = 0
    success: bool = True
    summary: str = ""

    model_config = ConfigDict(extra="allow")


# Foundation register_event → NORMAL client-wire visibility for stream forwards.
register_event(
    BrowserUseStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="BrowserUse: {task_preview}",
)
register_event(
    BrowserUseCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="BrowserUse: {summary}",
)

__all__ = [
    "SUBAGENT_BROWSER_USE_COMPLETED",
    "SUBAGENT_BROWSER_USE_STARTED",
    "BrowserUseCompletedEvent",
    "BrowserUseStartedEvent",
]
