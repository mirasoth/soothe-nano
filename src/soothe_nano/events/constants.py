"""Protocol-primitive event type string constants re-exported from the SDK.

The canonical home for these wire-visible constants is
:mod:`soothe_sdk.core.events` (the protocol-contracts layer shared with the
CLI and daemon). nano re-exports them here so its own event models can
reference them without depending on the host package.
"""

from __future__ import annotations

from soothe_sdk.core.events import (
    ERROR,
    LLM_RETRY_ATTEMPT,
    MEMORY_RECALLED,
    MEMORY_STORED,
    POLICY_CHECKED,
    POLICY_DENIED,
    STREAM_END,
)

__all__ = [
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "STREAM_END",
]
