"""Base event classes for Soothe events.

This module provides the base event classes that all specific events inherit from.
Module-specific events are defined in their respective modules and registered via
``register_event()``.

Progress events use type strings ``soothe.<domain>.<component>.<action>``.
Domains in active use include cognition, internal, subagent, system, mcp, loop,
stream, error, tool, output, protocol, and skillify. Community plugins may
introduce additional ``soothe.subagent.<plugin>.*`` types when they load.

The Pydantic event base classes stay in Python (framework-coupled). The event
type string constants are delegated to the Rust ``core`` crate via
``_rust_compat``; Python literals are retained as the fallback when the
extension is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from soothe_nano._rust_compat import get_rust_module


class SootheEvent(BaseModel):
    """Base class for all Soothe progress events."""

    type: str

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for wire-format emission."""
        return self.model_dump(exclude_none=True)

    def emit(self, logger: logging.Logger) -> None:
        """Emit this event via the LangGraph stream writer.

        Note: This method requires host-side implementation.
        For SDK use, events are typically sent via WebSocket.

        SDK-side event base class: provides type definition and serialization.
        Host-side implementation provides actual emit.
        """
        pass


class LifecycleEvent(SootheEvent):
    """Loop and session lifecycle events."""


class ProtocolEvent(SootheEvent):
    """Core protocol activity events."""


class SubagentEvent(SootheEvent):
    """Subagent activity events."""


class OutputEvent(SootheEvent):
    """Content destined for user display."""


class ErrorEvent(SootheEvent):
    """Error events."""

    error: str


# ── Event type constants ─────────────────────────────────────────
# Wire-safe event type strings for CLI/TUI event processing.
# Delegated to the Rust ``core`` crate when the extension is available;
# Python literals are the fallback.

_rust = get_rust_module()

# Plan events
PLAN_CREATED = getattr(_rust, "PLAN_CREATED", "soothe.cognition.plan.created")

# Agent loop events (DEBUG level; wire ``mode=custom`` types)
STRANGE_LOOP_STARTED = getattr(
    _rust, "STRANGE_LOOP_STARTED", "soothe.cognition.strange_loop.started"
)
STRANGE_LOOP_COMPLETED = getattr(
    _rust, "STRANGE_LOOP_COMPLETED", "soothe.cognition.strange_loop.completed"
)
STRANGE_LOOP_STEP_STARTED = getattr(
    _rust, "STRANGE_LOOP_STEP_STARTED", "soothe.cognition.strange_loop.step.started"
)
STRANGE_LOOP_STEP_QUEUED = getattr(
    _rust, "STRANGE_LOOP_STEP_QUEUED", "soothe.cognition.strange_loop.step.queued"
)
STRANGE_LOOP_STEP_COMPLETED = getattr(
    _rust, "STRANGE_LOOP_STEP_COMPLETED", "soothe.cognition.strange_loop.step.completed"
)
STRANGE_LOOP_PLAN_DECISION = getattr(
    _rust, "STRANGE_LOOP_PLAN_DECISION", "soothe.cognition.strange_loop.plan.decision"
)
STRANGE_LOOP_PLAN_PHASE = getattr(
    _rust, "STRANGE_LOOP_PLAN_PHASE", "soothe.cognition.strange_loop.plan.phase"
)
# Wired specialist lifecycle (orphan SubAgent card)
WIRED_SUBAGENT_STARTED = getattr(
    _rust, "WIRED_SUBAGENT_STARTED", "soothe.cognition.wired_subagent.started"
)
WIRED_SUBAGENT_COMPLETED = getattr(
    _rust, "WIRED_SUBAGENT_COMPLETED", "soothe.cognition.wired_subagent.completed"
)
WIRED_SUBAGENT_FAILED = getattr(
    _rust, "WIRED_SUBAGENT_FAILED", "soothe.cognition.wired_subagent.failed"
)
WIRED_SUBAGENT_CANCELLED = getattr(
    _rust, "WIRED_SUBAGENT_CANCELLED", "soothe.cognition.wired_subagent.cancelled"
)
INTENT_CLASSIFIED = getattr(_rust, "INTENT_CLASSIFIED", "soothe.cognition.intent.classified")

# Clarification relay events
LOOP_CLARIFICATION_REQUESTED = getattr(
    _rust, "LOOP_CLARIFICATION_REQUESTED", "soothe.loop.clarification.requested"
)
LOOP_CLARIFICATION_ANSWERED = getattr(
    _rust, "LOOP_CLARIFICATION_ANSWERED", "soothe.loop.clarification.answered"
)
LOOP_CLARIFICATION_DEFERRED = getattr(
    _rust, "LOOP_CLARIFICATION_DEFERRED", "soothe.loop.clarification.deferred"
)

# Stream termination
STREAM_END = getattr(_rust, "STREAM_END", "soothe.stream.end")

# Display card wire frames (RFC-413) — top-level or ``event``/``custom`` ``data.type``
CARD_CREATED = getattr(_rust, "CARD_CREATED", "soothe.card.created")
CARD_UPDATED = getattr(_rust, "CARD_UPDATED", "soothe.card.updated")
CARD_FINALIZED = getattr(_rust, "CARD_FINALIZED", "soothe.card.finalized")
CARD_REPLAY_BEGIN = getattr(_rust, "CARD_REPLAY_BEGIN", "soothe.card.replay.begin")
CARD_REPLAY_END = getattr(_rust, "CARD_REPLAY_END", "soothe.card.replay.end")
CARD_WIRE_TYPES = frozenset({CARD_CREATED, CARD_UPDATED, CARD_FINALIZED})
CARD_REPLAY_WIRE_TYPES = frozenset({CARD_REPLAY_BEGIN, CARD_REPLAY_END})

# Protocol-primitive events (wire-visible constants shared across packages;
# canonical home is the SDK as the protocol-contracts layer. nano and the
# host re-export these rather than redefine the literals.)
ERROR = getattr(_rust, "ERROR", "soothe.error.general.failed")
LLM_RETRY_ATTEMPT = getattr(_rust, "LLM_RETRY_ATTEMPT", "soothe.cognition.llm.retry.attempt")
MEMORY_RECALLED = getattr(_rust, "MEMORY_RECALLED", "soothe.internal.memory.recalled")
MEMORY_STORED = getattr(_rust, "MEMORY_STORED", "soothe.internal.memory.stored")
POLICY_CHECKED = getattr(_rust, "POLICY_CHECKED", "soothe.internal.policy.checked")
POLICY_DENIED = getattr(_rust, "POLICY_DENIED", "soothe.internal.policy.denied")

# Agent loop configuration constants
DEFAULT_STRANGE_LOOP_MAX_ITERATIONS = getattr(_rust, "DEFAULT_STRANGE_LOOP_MAX_ITERATIONS", 10)


__all__ = [
    "ErrorEvent",
    "LifecycleEvent",
    "OutputEvent",
    "ProtocolEvent",
    "SootheEvent",
    "SubagentEvent",
    # Event type constants - plan
    "PLAN_CREATED",
    # Agent loop (DEBUG)
    "STRANGE_LOOP_STARTED",
    "STRANGE_LOOP_COMPLETED",
    "STRANGE_LOOP_STEP_STARTED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "STRANGE_LOOP_PLAN_DECISION",
    "STRANGE_LOOP_PLAN_PHASE",
    "WIRED_SUBAGENT_STARTED",
    "WIRED_SUBAGENT_COMPLETED",
    "WIRED_SUBAGENT_FAILED",
    "WIRED_SUBAGENT_CANCELLED",
    # Clarification relay
    "LOOP_CLARIFICATION_REQUESTED",
    "LOOP_CLARIFICATION_ANSWERED",
    "LOOP_CLARIFICATION_DEFERRED",
    "STREAM_END",
    # Display card wire (RFC-413)
    "CARD_CREATED",
    "CARD_UPDATED",
    "CARD_FINALIZED",
    "CARD_REPLAY_BEGIN",
    "CARD_REPLAY_END",
    "CARD_WIRE_TYPES",
    "CARD_REPLAY_WIRE_TYPES",
    # Protocol-primitive constants (canonical home; re-exported by nano + host)
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    # Constants
    "DEFAULT_STRANGE_LOOP_MAX_ITERATIONS",
]
