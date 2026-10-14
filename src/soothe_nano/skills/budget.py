"""Budgeted skill-listing formatter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from soothe_nano.skills.index import SkillIndexEntry


class BudgetTelemetry(TypedDict):
    """Outcome of a budgeted listing: counts, mode, and char usage."""

    included_count: int
    truncated_count: int
    mode: str  # "full" | "truncated" | "names_only"
    budget_chars: int
    actual_chars: int


def format_skills_within_budget(
    entries: Sequence[SkillIndexEntry],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, BudgetTelemetry]:
    """Format skill listing within a character budget.

    Modes: ``full`` (under budget), ``truncated`` (over budget; built-ins keep
    full descriptions, others share the remainder), ``names_only`` (extreme
    case; non-built-ins become names only).

    Returns:
        Tuple of (formatted_text, telemetry).
    """
    from soothe_nano._rust_compat import format_skills_within_budget_rust

    tuples = [
        (e.name, e.description or "", (e.when_to_use or "").strip(), e.source) for e in entries
    ]
    text, tel = format_skills_within_budget_rust(
        tuples,
        budget_chars=budget_chars,
        per_entry_cap_chars=per_entry_cap_chars,
        min_per_entry_chars=min_per_entry_chars,
    )
    return text, BudgetTelemetry(
        included_count=tel["included_count"],
        truncated_count=tel["truncated_count"],
        mode=tel["mode"],
        budget_chars=tel["budget_chars"],
        actual_chars=tel["actual_chars"],
    )
