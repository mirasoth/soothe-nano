"""Early termination heuristics for deep_research loops."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soothe_nano._rust_compat import subagents_check_termination_rust

from .protocol import SourceResult


@dataclass
class TerminationDecision:
    """Result of early termination check."""

    should_terminate: bool
    reason: str
    confidence: float = 0.0


class LoopTerminationChecker:
    """Decides whether a research loop has gathered enough to stop early."""

    def __init__(
        self,
        min_results: int = 3,
        min_source_diversity: int = 2,
        max_duplicate_ratio: float = 0.5,
        min_content_length: int = 200,
    ):
        self.min_results = min_results
        self.min_source_diversity = min_source_diversity
        self.max_duplicate_ratio = max_duplicate_ratio
        self.min_content_length = min_content_length

    def check_termination(
        self,
        state: dict[str, Any],
        iteration: int,
        current_results: list[SourceResult],
    ) -> TerminationDecision:
        """Whether to stop after this iteration, with a reason."""
        accumulated = state.get("references_gathered", [])

        # Extract source names from accumulated refs
        accumulated_names: list[str] = []
        for ref in accumulated:
            if isinstance(ref, dict):
                name = ref.get("source_name")
                if name:
                    accumulated_names.append(str(name))
            elif hasattr(ref, "source_name"):
                accumulated_names.append(str(ref.source_name))

        current_contents = [r.content for r in current_results]
        current_source_names = [r.source_name for r in current_results]

        rust_result = subagents_check_termination_rust(
            self.min_results,
            self.min_source_diversity,
            self.max_duplicate_ratio,
            self.min_content_length,
            accumulated_names,
            current_contents,
            current_source_names,
            iteration,
        )
        return TerminationDecision(
            should_terminate=rust_result.should_terminate,
            reason=rust_result.reason,
            confidence=rust_result.confidence,
        )

    def _extract_source_names(
        self,
        accumulated: list[Any],
        current: list[SourceResult],
    ) -> set[str]:
        """Extract unique source names from accumulated and current results."""
        names: set[str] = set()

        for ref in accumulated:
            if isinstance(ref, dict):
                name = ref.get("source_name")
                if name:
                    names.add(name)
            elif hasattr(ref, "source_name"):
                names.add(ref.source_name)

        for result in current:
            names.add(result.source_name)

        return names

    def _extract_source_names_from_refs(self, refs: list[Any]) -> set[str]:
        """Extract source names from reference list."""
        names: set[str] = set()
        for ref in refs:
            if isinstance(ref, dict):
                name = ref.get("source_name")
                if name:
                    names.add(name)
            elif hasattr(ref, "source_name"):
                names.add(ref.source_name)
        return names

    def _compute_avg_content_length(self, results: list[SourceResult]) -> float:
        """Compute average content length from results."""
        if not results:
            return 0.0
        total = sum(len(r.content) for r in results)
        return total / len(results)


def should_terminate_early(
    state: dict[str, Any],
    iteration: int,
    current_results: list[SourceResult],
    config: Any | None = None,
) -> TerminationDecision:
    """Convenience function for early termination check."""
    min_results = 3
    min_diversity = 2

    if config:
        min_results = getattr(config, "min_results_for_termination", 3)
        min_diversity = getattr(config, "min_source_diversity", 2)

    checker = LoopTerminationChecker(
        min_results=min_results,
        min_source_diversity=min_diversity,
    )

    return checker.check_termination(state, iteration, current_results)
