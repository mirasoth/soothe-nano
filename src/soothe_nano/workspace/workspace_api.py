"""Public workspace types and resolution entry points."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

ResolvedWorkspaceSource = Literal["explicit", "thread", "daemon_default", "cwd", "tool_execution"]


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    """Absolute workspace path and which precedence level supplied it."""

    path: str
    source: ResolvedWorkspaceSource


class WorkspacePrecedence(Enum):
    """Which precedence chain to use for workspace resolution."""

    STREAM = "stream"
    TOOL_EXECUTION = "tool"
