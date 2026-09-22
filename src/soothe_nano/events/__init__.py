"""Event system package — CoreAgent protocol events and registry helpers."""

from __future__ import annotations

from soothe_sdk.core.events import (
    ERROR,
    LLM_RETRY_ATTEMPT,
    MEMORY_RECALLED,
    MEMORY_STORED,
    POLICY_DENIED,
    STREAM_END,
)
from soothe_sdk.core.verbosity import VerbosityTier

from .catalog import (
    LLM_PERSISTENT_RETRY,
    MODEL_FALLBACK,
    REGISTRY,
    ErrorGeneralEvent,
    EventMeta,
    EventPriority,
    EventRegistry,
    LLMPersistentRetryEvent,
    LLMRetryAttemptEvent,
    MemoryRecalledEvent,
    MemoryStoredEvent,
    ModelFallbackEvent,
    PolicyDeniedEvent,
    StreamChunk,
    StreamEndEvent,
    custom_event,
    register_event,
)

__all__ = [
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "LLM_PERSISTENT_RETRY",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "MODEL_FALLBACK",
    "POLICY_DENIED",
    "REGISTRY",
    "STREAM_END",
    "EventMeta",
    "EventPriority",
    "EventRegistry",
    "ErrorGeneralEvent",
    "LLMPersistentRetryEvent",
    "LLMRetryAttemptEvent",
    "MemoryRecalledEvent",
    "MemoryStoredEvent",
    "ModelFallbackEvent",
    "PolicyDeniedEvent",
    "StreamChunk",
    "StreamEndEvent",
    "VerbosityTier",
    "custom_event",
    "register_event",
]
