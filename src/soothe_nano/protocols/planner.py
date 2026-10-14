"""PlannerProtocol -- goal decomposition and plan lifecycle."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator

from soothe_nano._rust_compat import (
    is_valid_execution_hint_rust,
    is_valid_goal_directive_action_rust,
    is_valid_plan_status_rust,
    is_valid_step_status_rust,
    planner_outcome_text_preview_rust,
    step_result_to_evidence_string_rust,
)
from soothe_nano.protocols.concurrency import ConcurrencyPolicy


def planner_outcome_text_preview(outcome: dict[str, Any]) -> str | None:
    """Resolve bounded planner-facing text from an outcome dict."""
    return planner_outcome_text_preview_rust(outcome)


class PlanStep(BaseModel):
    """A single step in a plan.

    Args:
        id: Unique step identifier.
        description: What this step should accomplish.
        execution_hint: Preferred execution method.
        subagent: Delegate name when routing through a subagent (legacy planner Plan path).
        status: Current step status.
        result: Output from execution (set after completion).
        depends_on: IDs of steps that must complete before this one.
        current_activity: Latest activity text for this step (for TUI rendering).
    """

    id: str
    description: str
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    subagent: str | None = None
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    result: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    current_activity: str | None = None

    @field_validator("execution_hint")
    @classmethod
    def _validate_execution_hint(cls, v: str) -> str:
        """Rust-backed execution-hint validation."""
        if not is_valid_execution_hint_rust(v):
            raise ValueError(f"invalid execution_hint: {v}")
        return v

    @field_validator("status")
    @classmethod
    def _validate_step_status(cls, v: str) -> str:
        """Rust-backed step-status validation."""
        if not is_valid_step_status_rust(v):
            raise ValueError(f"invalid step status: {v}")
        return v


class Plan(BaseModel):
    """A structured decomposition of a goal into executable steps.

    Args:
        id: Unique plan identifier (P_1, P_2, etc.).
        goal: The original goal text.
        steps: Ordered list of plan steps.
        current_index: Index of the current/next step to execute.
        status: Overall plan status.
        concurrency: Parallel execution configuration.
        general_activity: Latest non-step activity (for TUI rendering).
    """

    id: str = ""
    goal: str
    steps: list[PlanStep]
    current_index: int = 0
    status: Literal["active", "completed", "failed", "revised"] = "active"
    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    general_activity: str | None = None

    # Unified planning metadata
    is_plan_only: bool = Field(default=False, description="User wants planning without execution")
    reasoning: str | None = Field(
        default=None, description="Optional planner rationale or strategy summary when populated"
    )

    @field_validator("status")
    @classmethod
    def _validate_plan_status(cls, v: str) -> str:
        """Rust-backed plan-status validation."""
        if not is_valid_plan_status_rust(v):
            raise ValueError(f"invalid plan status: {v}")
        return v


class StepResult(BaseModel):
    """Result of executing a plan step.

    Args:
        step_id: The step that was executed.
        success: Whether the step succeeded.
        outcome: Structured metadata from tool execution.
        error: Error message if failed.
        duration_ms: Execution time in milliseconds.
        thread_id: Thread used for execution.
    """

    step_id: str
    success: bool
    outcome: dict = Field(default_factory=dict)  # outcome metadata
    error: str | None = None
    duration_ms: int | None = None
    thread_id: str | None = None

    def to_evidence_string(self, *, truncate: bool = True) -> str:
        """Convert to evidence string for reflection and planning.

        Args:
            truncate: If True, generate concise summary.
                     If False, return detailed summary.

        Returns:
            Human-readable evidence string
        """
        return step_result_to_evidence_string_rust(self.model_dump(), truncate=truncate)


class PlanContext(BaseModel):
    """Context available to the planner when creating or revising a plan.

    Args:
        recent_messages: Recent conversation messages for context.
        available_capabilities: Names of available tools and subagents.
        completed_steps: Results from already-completed steps.
        routing_classification: Pre-computed intent routing classification.
        workspace: Current workspace directory path.
        working_memory_excerpt: Reserved; not embedded in Plan-phase human text.
        thread_id: Thread id for observability (Langfuse session on plan LLM calls).
    """

    recent_messages: list[str] = Field(default_factory=list)
    available_capabilities: list[str] = Field(default_factory=list)
    completed_steps: list[StepResult] = Field(default_factory=list)
    routing_classification: Any | None = Field(default=None)
    workspace: str | None = None  # Current workspace directory
    working_memory_excerpt: str | None = None
    thread_id: str | None = Field(
        default=None,
        description="Thread id for observability (e.g. Langfuse session_id on plan LLM calls).",
    )


class StepReport(BaseModel):
    """Report from a single executed step.

    Args:
        step_id: The step that was executed.
        description: Step description.
        status: Final step status.
        result: Output text (truncated).
        duration_ms: Execution time in milliseconds.
        depends_on: IDs of steps this step depended on.
    """

    step_id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    result: str = ""
    duration_ms: int = 0
    depends_on: list[str] = Field(default_factory=list)


class GoalReport(BaseModel):
    """Aggregate report from a completed goal.

    Args:
        goal_id: Goal identifier.
        description: Goal description.
        step_reports: Reports from all steps.
        summary: Synthesized summary of results.
        status: Final goal status.
        duration_ms: Total execution time.
        reflection_assessment: Planner reflection on this goal.
        cross_validation_notes: Cross-validation findings.
    """

    goal_id: str
    description: str
    step_reports: list[StepReport] = Field(default_factory=list)
    summary: str = ""
    status: Literal["completed", "failed"] = "completed"
    duration_ms: int = 0
    reflection_assessment: str = ""
    cross_validation_notes: str = ""


class GoalDirective(BaseModel):
    """A single goal management directive from reflection.

    Args:
        action: 'create' | 'decompose' | 'adjust_priority' | 'add_dependency' | 'fail' | 'complete'
        goal_id: Target goal ID (for existing goals).
        description: Goal description (for create).
        priority: Priority value (for create/adjust_priority).
        parent_id: Parent goal ID (for decomposition).
        depends_on: Dependency list (for create/add_dependency).
        rationale: Why this directive was issued.
    """

    action: Literal["create", "decompose", "adjust_priority", "add_dependency", "fail", "complete"]
    goal_id: str = ""
    description: str = ""
    priority: int | None = None
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = ""

    @field_validator("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        """Rust-backed goal-directive action validation."""
        if not is_valid_goal_directive_action_rust(v):
            raise ValueError(f"invalid goal directive action: {v}")
        return v


class Reflection(BaseModel):
    """Planner's assessment of plan progress.

    Args:
        assessment: Description of current progress.
        should_revise: Whether the plan needs revision.
        feedback: Specific feedback for revision (if needed).
        blocked_steps: Step IDs blocked by dependency failures.
        failed_details: Map of failed step ID to truncated error output.
        goal_directives: List of goal management actions.
    """

    assessment: str
    should_revise: bool
    feedback: str
    blocked_steps: list[str] = Field(default_factory=list)
    failed_details: dict[str, str] = Field(default_factory=dict)
    goal_directives: list[GoalDirective] = Field(default_factory=list)


@runtime_checkable
class PlannerProtocol(Protocol):
    """Marker protocol for planner implementations attached to CoreAgent."""
