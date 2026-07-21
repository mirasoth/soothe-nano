"""Centralized event type string constants for CoreAgent protocol events.

A focused subset of the protocol event type strings used by nano's own event
models (see :mod:`soothe_nano.events.catalog`). The canonical full catalog of
constants lives in ``soothe.foundation.events.constants``; nano keeps only the
strings its models reference here so it does not depend on the host package.
"""

from __future__ import annotations

MEMORY_RECALLED = "soothe.internal.memory.recalled"
MEMORY_STORED = "soothe.internal.memory.stored"

POLICY_CHECKED = "soothe.internal.policy.checked"
POLICY_DENIED = "soothe.internal.policy.denied"

ERROR = "soothe.error.general.failed"

STREAM_END = "soothe.stream.end"

LLM_RETRY_ATTEMPT = "soothe.cognition.llm.retry.attempt"

__all__ = [
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "STREAM_END",
]
