"""Lightweight diagnose result models (dict-contract compatible).

Delegates status aggregation and dict serialization to the Rust extension
(``soothe-nano-diagnose`` crate). Python retains the ``StrEnum`` / dataclass
facade for type safety and backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import total_ordering
from typing import Any

from soothe_nano._rust_compat import (
    aggregate_status_rust,
    check_status_severity_rust,
    compare_status_rust,
)


@total_ordering
class CheckStatus(StrEnum):
    """Diagnose check status levels."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    SKIPPED = "skipped"

    @property
    def severity(self) -> int:
        """Numeric severity for aggregation (higher = worse)."""
        rust_result = check_status_severity_rust(self.value)
        if rust_result is not None:
            return rust_result
        return {
            CheckStatus.OK: 0,
            CheckStatus.INFO: 1,
            CheckStatus.SKIPPED: 2,
            CheckStatus.WARNING: 3,
            CheckStatus.ERROR: 4,
        }[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, CheckStatus):
            rust_result = compare_status_rust(self.value, other.value)
            if rust_result is not None:
                return rust_result < 0
            return self.severity < other.severity
        return NotImplemented


@dataclass
class CheckResult:
    """Result of a single diagnose check."""

    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the shared diagnose dict contract."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class CategoryResult:
    """Results for one diagnose category."""

    category: str
    status: CheckStatus
    checks: list[CheckResult]
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the shared diagnose dict contract."""
        return {
            "category": self.category,
            "status": self.status.value,
            "checks": [check.to_dict() for check in self.checks],
            "message": self.message,
        }


def aggregate_status(statuses: list[CheckStatus]) -> CheckStatus:
    """Aggregate multiple statuses into one (worst wins)."""
    if not statuses:
        return CheckStatus.OK
    status_strs = [s.value for s in statuses]
    result_str = aggregate_status_rust(status_strs)
    return CheckStatus(result_str)
