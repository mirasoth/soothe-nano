"""WorkspaceContextMiddleware for thread-aware workspace."""

from __future__ import annotations

from contextvars import Token
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime


def _virtual_mode_without_soothe_config() -> bool:
    """Resolve virtual_mode from the live backend/context — never soothe_config."""
    from soothe_nano.workspace.workspace_runtime import get_workspace_context

    ctx = get_workspace_context()
    # Prefer the filesystem backend's construction-time sandbox mode when available.
    try:
        from soothe_nano.workspace.workspace_filesystem import FrameworkFilesystem

        backend = FrameworkFilesystem.get()
        backend_mode = getattr(backend, "virtual_mode", None)
        if isinstance(backend_mode, bool):
            return backend_mode
    except Exception:  # noqa: BLE001 — backend may be uninitialized in unit tests
        pass
    return bool(ctx.virtual_mode)


class WorkspaceContextMiddleware(AgentMiddleware):
    """Set workspace context for tool execution.

    Reads workspace from config.configurable / state and sets ContextVar for
    FrameworkFilesystem. Does **not** depend on injecting ``soothe_config``.

    Thread Safety:
        Python's contextvars.ContextVar provides async-safe context isolation.
        Each async task (thread execution) has its own context, preventing
        cross-thread contamination even with concurrent execution.

    Example:
        config.configurable = {
            "thread_id": "thread-123",
            "workspace": "/home/user/project-a"
        }

        → set_workspace_context("/home/user/project-a", virtual_mode=...)
        → Tools resolve paths against /home/user/project-a
        → reset_workspace_context(token) after execution
    """

    # Opt into general-purpose subagent inheritance (deepagents generic flag).
    propagate_to_general_purpose = True

    def __init__(self) -> None:
        self._workspace_token: Token[Any] | None = None

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Set workspace context before agent execution.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            State updates (workspace mirrored in state).
        """
        from langgraph.config import get_config

        from soothe_nano.workspace.workspace_api import (
            resolve_workspace_for_tool_execution,
        )
        from soothe_nano.workspace.workspace_runtime import set_workspace_context

        config: dict[str, Any] = {}
        try:
            raw_config = get_config()
            if isinstance(raw_config, dict):
                config = raw_config
        except Exception:
            pass

        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        config_workspace = configurable.get("workspace") if isinstance(configurable, dict) else None
        state_workspace = state.get("workspace") if isinstance(state, dict) else None

        workspace_path = resolve_workspace_for_tool_execution(
            config=config or None,
            state=state,
            use_langgraph_config=True,
        )
        if workspace_path is None and config_workspace:
            workspace_path = Path(str(config_workspace)).expanduser().resolve()
        if workspace_path is None and state_workspace:
            workspace_path = Path(str(state_workspace)).expanduser().resolve()
        if workspace_path is None:
            return None

        self._workspace_token = set_workspace_context(
            workspace=Path(workspace_path),
            virtual_mode=_virtual_mode_without_soothe_config(),
        )

        return {"workspace": str(workspace_path)}

    async def aafter_agent(
        self,
        state: AgentState,  # noqa: ARG002
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Clear workspace context after agent execution.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            None.
        """
        from soothe_nano.workspace.workspace_runtime import reset_workspace_context

        reset_workspace_context(self._workspace_token)
        self._workspace_token = None
        return None
