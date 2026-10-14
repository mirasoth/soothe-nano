"""Operation security protocol for tool-level security checks."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator

from soothe_nano._rust_compat import (
    is_valid_operation_kind_rust,
    is_valid_operation_security_verdict_rust,
)

OperationKind = Literal[
    "filesystem_read",
    "filesystem_write",
    "shell_execute",
    "python_execute",
    "process_control",
    "generic",
]


class OperationSecurityRequest(BaseModel):
    """Normalized security request for a single operation."""

    action_type: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    operation_kind: OperationKind = "generic"
    target_path: str | None = None
    command: str | None = None

    @field_validator("operation_kind")
    @classmethod
    def _validate_operation_kind(cls, v: str) -> str:
        """Rust-backed operation kind validation."""
        if not is_valid_operation_kind_rust(v):
            raise ValueError(f"invalid operation_kind: {v}")
        return v


class OperationSecurityContext(BaseModel):
    """Context for operation security evaluation."""

    thread_id: str | None = None
    workspace: str | None = None
    security_config: Any = None
    bypass_security: bool = False


class OperationSecurityDecision(BaseModel):
    """Security verdict for an operation request."""

    verdict: Literal["allow", "deny", "need_approval"]
    reason: str
    rule_id: str | None = None

    @field_validator("verdict")
    @classmethod
    def _validate_verdict(cls, v: str) -> str:
        """Rust-backed operation security verdict validation."""
        if not is_valid_operation_security_verdict_rust(v):
            raise ValueError(f"invalid verdict: {v}")
        return v


@runtime_checkable
class OperationSecurityProtocol(Protocol):
    """Protocol for operation-level security checks."""

    def evaluate(
        self,
        request: OperationSecurityRequest,
        context: OperationSecurityContext,
    ) -> OperationSecurityDecision:
        """Evaluate whether an operation should be allowed."""
        ...
