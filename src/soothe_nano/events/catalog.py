"""Nano-owned Soothe protocol event models, registered into the shared sdk registry at import time."""

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
"""Deepagents-canonical stream chunk: `(namespace, mode, data)`."""

# Event type constants for nano-owned protocol events.
MODEL_FALLBACK = "soothe.cognition.llm.model_fallback"
LLM_PERSISTENT_RETRY = "soothe.cognition.llm.persistent_retry"


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


class ModelFallbackEvent(LifecycleEvent):
    """Model fallback triggered after repeated capacity errors.

    Emitted by ``PersistentRetryRunner`` when the model is switched to a
    fallback after ``fallback_model_threshold`` consecutive 529/overloaded
    errors. Carries enough context for downstream consumers (TUI, daemon
    health) to surface the degradation.
    """

    type: Literal["soothe.cognition.llm.model_fallback"] = "soothe.cognition.llm.model_fallback"
    from_model: str = ""
    to_model: str = ""
    to_role: str | None = None
    consecutive_capacity_errors: int = 0
    thread_id: str | None = None


class LLMPersistentRetryEvent(LifecycleEvent):
    """Persistent retry attempt event for 24/7 resilience visibility.

    Emitted by ``PersistentRetryRunner`` on each persistent-retry backoff
    cycle so the daemon and TUI can surface ongoing retry activity during
    provider capacity cascades.
    """

    type: Literal["soothe.cognition.llm.persistent_retry"] = "soothe.cognition.llm.persistent_retry"
    attempt: int
    error_type: str
    backoff_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    total_cap_seconds: float = 0.0
    thread_id: str | None = None
    query_source: str = ""


class MemoryRecalledEvent(ProtocolEvent):
    type: Literal["soothe.internal.memory.recalled"] = "soothe.internal.memory.recalled"
    count: int = 0
    query: str = ""


class MemoryStoredEvent(ProtocolEvent):
    type: Literal["soothe.internal.memory.stored"] = "soothe.internal.memory.stored"
    id: str = ""
    source_thread: str = ""


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
register_event(
    ModelFallbackEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Model fallback: {from_model} → {to_model} ({consecutive_capacity_errors} capacity errors)",
    priority=EventPriority.HIGH,
)
register_event(
    LLMPersistentRetryEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Persistent retry #{attempt} ({error_type}) backoff={backoff_seconds:.1f}s",
    priority=EventPriority.NORMAL,
)
register_event(MemoryRecalledEvent, summary_template="{count} items recalled")
register_event(MemoryStoredEvent, summary_template="Stored memory: {id}")
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
    "LLM_PERSISTENT_RETRY",
    "LLMPersistentRetryEvent",
    "LLMRetryAttemptEvent",
    "MODEL_FALLBACK",
    "MemoryRecalledEvent",
    "MemoryStoredEvent",
    "ModelFallbackEvent",
    "PolicyDeniedEvent",
    "StreamChunk",
    "StreamEndEvent",
    "custom_event",
    "register_event",
]
