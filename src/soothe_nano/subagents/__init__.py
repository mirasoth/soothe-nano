"""Built-in CoreAgent subagents (soothe-nano)."""

from .academic_research import events as _academic_research_events  # noqa: F401
from .browser_use import events as _browser_use_events  # noqa: F401
from .computer_use import events as _computer_use_events  # noqa: F401
from .deep_research import events as _deep_research_events  # noqa: F401
from .plan import engine as _plan_engine  # noqa: F401 — register planner wire events

__all__: list[str] = []
