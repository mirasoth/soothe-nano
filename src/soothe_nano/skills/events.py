"""Progressive skill loading events (self-registered)."""

from __future__ import annotations

from pydantic import BaseModel
from soothe_sdk.core.events import SootheEvent

from soothe_nano.events.catalog import register_event


class SkillBodyLoadedEvent(SootheEvent):
    """Emitted when a skill body enters context via Stage 3 invocation."""

    type: str = "soothe.internal.skill.body.loaded"
    skill_name: str
    body_chars: int
    thread_id: str


register_event(
    SkillBodyLoadedEvent,
    summary_template="Skill body loaded: {skill_name} ({body_chars} chars)",
)


class InternalSkillActivatedEvent(BaseModel):
    """Internal-only event for cross-middleware coordination (not wire-visible)."""

    skill_name: str
    matched_path: str
    pattern: str
    thread_id: str
