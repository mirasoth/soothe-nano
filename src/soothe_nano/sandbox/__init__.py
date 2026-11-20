"""Sandbox backends for remote tool execution.

Multi-backend architecture: the :class:`SandboxBackendFactory` dispatches
backend construction by ``type`` discriminator, so new backends (Docker,
Kata, gVisor, …) can be added without modifying the agent builder.

Built-in backend: ``arcbox`` (ArcBox microVM via the arcbox SDK).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe_nano.sandbox.factory import (
    SandboxBackendFactory,
    create_sandbox_backend,
)

if TYPE_CHECKING:
    from soothe_nano.sandbox.arcbox import (
        ArcBoxBackend,
        ArcBoxClient,
        ArcBoxError,
        ArcBoxFileNotFoundError,
        ArcBoxIsDirectoryError,
        ArcBoxTimeoutError,
        CommandRunResult,
    )

__all__ = [
    "ArcBoxBackend",
    "ArcBoxClient",
    "ArcBoxError",
    "ArcBoxFileNotFoundError",
    "ArcBoxIsDirectoryError",
    "ArcBoxTimeoutError",
    "CommandRunResult",
    "SandboxBackendFactory",
    "create_sandbox_backend",
]


def __getattr__(name: str) -> Any:
    # Factory exports are always available (no heavy deps).
    if name in ("SandboxBackendFactory", "create_sandbox_backend"):
        return globals()[name]

    # ArcBox-specific symbols are lazy-loaded only when accessed.
    _arcbox_exports = {
        "ArcBoxBackend",
        "ArcBoxClient",
        "ArcBoxError",
        "ArcBoxFileNotFoundError",
        "ArcBoxIsDirectoryError",
        "ArcBoxTimeoutError",
        "CommandRunResult",
    }
    if name in _arcbox_exports:
        from soothe_nano.sandbox import arcbox as _arcbox

        return getattr(_arcbox, name)

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
