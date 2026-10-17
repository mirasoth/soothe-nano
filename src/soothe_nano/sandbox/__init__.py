"""Sandbox backends for remote tool execution (ArcBox microVM)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    from soothe_nano.sandbox import arcbox as _arcbox

    return getattr(_arcbox, name)
