"""Core events for the Soothe protocol (nano-owned models).

Event metadata types (``EventPriority`` / ``EventMeta`` / ``EventRegistry``),
the shared ``REGISTRY`` singleton, and ``register_event`` are owned by
:mod:`soothe_sdk.core.registry`. nano defines its protocol event models here
and registers them into that shared registry at import time.
"""

from __future__ import annotations

from typing import Any, Literal

from soothe_sdk.core.events import (
    ERROR,
    ErrorEvent,
    LifecycleEvent,
    ProtocolEvent,
)
from soothe_sdk.core.registry import (
    REGISTRY,  # noqa: F401  (re-exported for nano consumers)
    EventMeta,  # noqa: F401
    EventPriority,  # noqa: F401
    EventRegistry,  # noqa: F401
    register_event,
)
from soothe_sdk.core.verbosity import VerbosityTier

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""


def custom_event(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


class StreamEndEvent(LifecycleEvent):
    """Marks the end of an assistant stream scope (generation, phase, or turn)."""

    type: Literal["soothe.stream.end"] = "soothe.stream.end"
    scope: Literal["generation", "phase", "turn"]
    phase: str | None = None
    reason: str | None = None


class LLMRetryAttemptEvent(LifecycleEvent):
    """LLM retry attempt event for middleware visibility."""

    type: Literal["soothe.cognition.llm.retry.attempt"] = "soothe.cognition.llm.retry.attempt"
    attempt: int
    max_attempts: int
    error_type: str
    thread_id: str | None = None


class MemoryRecalledEvent(ProtocolEvent):
    type: Literal["soothe.internal.memory.recalled"] = "soothe.internal.memory.recalled"
    count: int = 0
    query: str = ""


class MemoryStoredEvent(ProtocolEvent):
    type: Literal["soothe.internal.memory.stored"] = "soothe.internal.memory.stored"
    id: str = ""
    source_thread: str = ""


class PolicyCheckedEvent(ProtocolEvent):
    type: Literal["soothe.internal.policy.checked"] = "soothe.internal.policy.checked"
    action: str = ""
    verdict: str = ""
    profile: str | None = None


class PolicyDeniedEvent(ProtocolEvent):
    type: Literal["soothe.internal.policy.denied"] = "soothe.internal.policy.denied"
    action: str = ""
    reason: str = ""
    profile: str | None = None


class ErrorGeneralEvent(ErrorEvent):
    """General failure event for stream/wire error payloads."""

    type: Literal["soothe.error.general.failed"] = ERROR  # type: ignore[assignment]
    error: str = ""
    code: str | None = None


register_event(
    StreamEndEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Stream end ({scope})",
    priority=EventPriority.HIGH,
)
register_event(
    LLMRetryAttemptEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="LLM retry {attempt}/{max_attempts} ({error_type})",
    priority=EventPriority.HIGH,
)
register_event(MemoryRecalledEvent, summary_template="{count} items recalled")
register_event(MemoryStoredEvent, summary_template="Stored memory: {id}")
register_event(PolicyCheckedEvent, summary_template="Policy: {verdict}")
register_event(PolicyDeniedEvent, summary_template="Denied: {reason}")
register_event(
    ErrorGeneralEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Error: {error}",
    priority=EventPriority.CRITICAL,
)


__all__ = [
    "REGISTRY",
    "ErrorGeneralEvent",
    "EventMeta",
    "EventPriority",
    "EventRegistry",
    "LLMRetryAttemptEvent",
    "MemoryRecalledEvent",
    "MemoryStoredEvent",
    "PolicyCheckedEvent",
    "PolicyDeniedEvent",
    "StreamChunk",
    "StreamEndEvent",
    "custom_event",
    "register_event",
]
