"""Effort levels for academic_research — normal and thorough."""

from __future__ import annotations

from pydantic import BaseModel, Field

from soothe_nano._rust_compat import (
    subagents_effort_follow_up_hint_rust,
    subagents_effort_plan_hint_rust,
    subagents_normalize_effort_rust,
    subagents_parse_effort_from_text_rust,
)

from .protocol import AcademicResearchConfig, AcademicResearchEffortLevel


class AcademicResearchEffortProfile(BaseModel):
    """Hard caps for one effort level."""

    effort: AcademicResearchEffortLevel
    max_sub_questions: int = Field(ge=1, le=20)
    max_initial_queries: int = Field(ge=1, le=20)
    max_follow_up_queries: int = Field(ge=0, le=10)
    max_loops: int = Field(ge=1, le=10)
    crawl_top_n: int = Field(ge=1, le=10)

    @property
    def plan_hint(self) -> str:
        return subagents_effort_plan_hint_rust(self.effort)

    @property
    def reflect_follow_up_hint(self) -> str:
        return subagents_effort_follow_up_hint_rust(self.effort)


_PROFILES: dict[AcademicResearchEffortLevel, AcademicResearchEffortProfile] = {
    "normal": AcademicResearchEffortProfile(
        effort="normal",
        max_sub_questions=3,
        max_initial_queries=4,
        max_follow_up_queries=1,
        max_loops=2,
        crawl_top_n=3,
    ),
    "thorough": AcademicResearchEffortProfile(
        effort="thorough",
        max_sub_questions=5,
        max_initial_queries=8,
        max_follow_up_queries=2,
        max_loops=4,
        crawl_top_n=5,
    ),
}


def profile_for_effort(effort: AcademicResearchEffortLevel) -> AcademicResearchEffortProfile:
    """Return the profile for a validated effort level."""
    return _PROFILES[effort]


def normalize_effort(raw: str | None) -> AcademicResearchEffortLevel:
    """Coerce config/context value to a valid effort level."""
    return subagents_normalize_effort_rust(raw)  # type: ignore[return-value]


def parse_effort_from_text(text: str) -> AcademicResearchEffortLevel | None:
    """Parse ``effort: thorough`` from topic text."""
    return subagents_parse_effort_from_text_rust(text)  # type: ignore[return-value]


def resolve_effort(
    config: AcademicResearchConfig,
    *,
    topic: str = "",
    context_effort: str | None = None,
    context_max_loops: int | None = None,
) -> tuple[AcademicResearchEffortLevel, AcademicResearchEffortProfile]:
    """Resolve effort and profile."""
    effort: AcademicResearchEffortLevel = "normal"
    if parsed := parse_effort_from_text(topic):
        effort = parsed
    elif context_effort:
        effort = normalize_effort(context_effort)
    else:
        effort = normalize_effort(getattr(config, "effort", "normal"))

    profile = _PROFILES[effort]
    if context_max_loops is not None and context_max_loops != profile.max_loops:
        profile = profile.model_copy(update={"max_loops": context_max_loops})
    return effort, profile
