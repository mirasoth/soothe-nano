"""Per-async-task workspace state and process-level defaults."""

from __future__ import annotations

import os
import tempfile
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkspaceContext:
    """Per-async-task workspace state."""

    workspace: Path | None = None
    virtual_mode: bool = False
    virtual_home: Path | None = None


class WorkspaceRuntime:
    """Owns the per-async-task workspace ContextVar and process defaults."""

    _context: ContextVar[WorkspaceContext] = ContextVar(
        "soothe_workspace_context",
        default=WorkspaceContext(),
    )

    @classmethod
    def set(
        cls,
        *,
        workspace: Path | str | None = None,
        virtual_mode: bool = False,
    ) -> Token[WorkspaceContext]:
        """Set workspace context for the current async task."""
        ws_path = Path(workspace) if isinstance(workspace, str) else workspace
        virtual_home = ws_path / ".soothe" if virtual_mode and ws_path else None
        ctx = WorkspaceContext(
            workspace=ws_path,
            virtual_mode=virtual_mode,
            virtual_home=virtual_home,
        )
        return cls._context.set(ctx)

    @classmethod
    def get(cls) -> WorkspaceContext:
        """Get workspace context for the current async task."""
        return cls._context.get()

    @classmethod
    def reset(cls, token: Token[WorkspaceContext] | None = None) -> None:
        """Clear workspace context at stream end."""
        if token is not None:
            try:
                cls._context.reset(token)
            except ValueError:
                cls._context.set(WorkspaceContext())
        else:
            cls._context.set(WorkspaceContext())

    @classmethod
    def set_virtual_mode(cls, virtual_mode: bool, workspace: Path) -> None:
        """Set virtual mode context for the current async task."""
        cls.set(workspace=workspace, virtual_mode=virtual_mode)

    @classmethod
    def clear_virtual_mode(cls) -> None:
        """Clear virtual mode context at stream end."""
        cls.reset()

    @classmethod
    def virtual_home(cls) -> Path:
        """Home directory for the current context."""
        ctx = cls.get()
        if ctx.virtual_home is not None:
            return ctx.virtual_home
        from soothe_nano.config import SOOTHE_HOME

        return Path(SOOTHE_HOME)

    @classmethod
    def virtual_mode(cls) -> bool:
        """Whether virtual mode is enabled for the current context."""
        return cls.get().virtual_mode

    @classmethod
    def virtual_home_relative_path(cls, host_path: Path) -> str | None:
        """Convert a host-absolute path to virtual-home-relative if under virtual home."""
        ctx = cls.get()
        if ctx.virtual_home is None:
            return None
        try:
            rel = host_path.resolve().relative_to(ctx.virtual_home.resolve())
            return f"/.soothe/{rel.as_posix()}"
        except ValueError:
            return None

    @classmethod
    def process_workspace_root(cls) -> Path:
        """Process-default workspace root when no explicit workspace is bound."""
        env_workspace = os.environ.get("SOOTHE_WORKSPACE")
        if env_workspace:
            return Path(env_workspace).expanduser().resolve()
        workspace = Path(tempfile.gettempdir()) / "soothe-workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace.resolve()
