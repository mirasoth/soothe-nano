"""Workspace resolution chains (stream + tool execution)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from soothe_nano.workspace.workspace_api import ResolvedWorkspace, WorkspacePrecedence

logger = logging.getLogger(__name__)


class WorkspaceResolver:
    """Stateless workspace resolution chains.

    Entry points: `resolve_stream` (one agent stream), `resolve_tool_execution`
    (current tool/agent turn), `resolve` (precedence-dispatched), and
    `effective_tool_workspace` (tool construction / filesystem operations).
    """

    @staticmethod
    def _coerce_workspace(value: Any) -> Path | None:
        if isinstance(value, Path):
            return value
        if isinstance(value, str) and value.strip():
            return Path(value.strip())
        return None

    @staticmethod
    def _normalize_candidate(raw: str | Path | None) -> Path | None:
        if raw is None:
            return None
        if isinstance(raw, Path):
            text = str(raw).strip()
            if not text:
                return None
            return raw.expanduser().resolve()
        text = str(raw).strip()
        if not text:
            return None
        return Path(text).expanduser().resolve()

    @classmethod
    def _from_configurable(cls, configurable: Any) -> Path | None:
        if not isinstance(configurable, dict):
            return None
        return cls._coerce_workspace(configurable.get("workspace"))

    @classmethod
    def _from_messages(cls, messages: Any) -> Path | None:
        if not isinstance(messages, (list, tuple)):
            return None
        for msg in reversed(messages):
            ws = cls._coerce_workspace(getattr(msg, "workspace", None))
            if ws is not None:
                return ws
            if isinstance(msg, dict):
                additional = msg.get("additional_kwargs")
                if isinstance(additional, dict):
                    ws = cls._coerce_workspace(additional.get("workspace"))
                    if ws is not None:
                        return ws
                ws = cls._coerce_workspace(msg.get("workspace"))
                if ws is not None:
                    return ws
        return None

    @classmethod
    def _from_state_dict(cls, state: dict[str, Any] | None) -> Path | None:
        if not isinstance(state, dict):
            return None
        direct = cls._coerce_workspace(state.get("workspace"))
        if direct is not None:
            return direct
        return cls._from_messages(state.get("messages"))

    @staticmethod
    def _runtime_config(runtime: Any) -> dict[str, Any] | None:
        cfg = getattr(runtime, "config", None)
        return cfg if isinstance(cfg, dict) else None

    @staticmethod
    def _runtime_state(runtime: Any) -> dict[str, Any] | None:
        state = getattr(runtime, "state", None)
        return state if isinstance(state, dict) else None

    @classmethod
    def resolve_stream(
        cls,
        *,
        explicit: str | Path | None = None,
        thread_workspace: str | Path | None = None,
        installation_default: str | Path | None = None,
    ) -> ResolvedWorkspace:
        """Pick workspace for one agent stream."""
        if (p := cls._normalize_candidate(explicit)) is not None:
            return ResolvedWorkspace(path=str(p), source="explicit")
        if (p := cls._normalize_candidate(thread_workspace)) is not None:
            return ResolvedWorkspace(path=str(p), source="thread")
        if (p := cls._normalize_candidate(installation_default)) is not None:
            return ResolvedWorkspace(path=str(p), source="daemon_default")
        return ResolvedWorkspace(path=str(Path.cwd().resolve()), source="cwd")

    @classmethod
    def resolve_tool_execution(
        cls,
        *,
        runtime: Any | None = None,
        config: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        fallback: str | Path | None = None,
        use_langgraph_config: bool = True,
    ) -> Path | None:
        """Resolve effective workspace for the current tool or agent turn."""
        effective_config = config if config is not None else cls._runtime_config(runtime)
        effective_state = state if state is not None else cls._runtime_state(runtime)

        if isinstance(effective_config, dict):
            ws = cls._from_configurable(effective_config.get("configurable"))
            if ws is not None:
                return ws

        ws = cls._from_state_dict(effective_state)
        if ws is not None:
            return ws

        if use_langgraph_config:
            try:
                from langgraph.config import get_config

                lg_config = get_config()
                if isinstance(lg_config, dict):
                    ws = cls._from_configurable(lg_config.get("configurable"))
                    if ws is not None:
                        return ws
            except Exception:  # noqa: S110
                pass

        from soothe_nano.workspace.workspace_runtime import WorkspaceRuntime

        current = WorkspaceRuntime.get().workspace
        if current is not None:
            return current

        return cls._coerce_workspace(fallback)

    @classmethod
    def resolve(cls, precedence: WorkspacePrecedence, **sources: Any) -> ResolvedWorkspace:
        """Resolve workspace using the requested precedence chain."""
        if precedence == WorkspacePrecedence.STREAM:
            return cls.resolve_stream(
                explicit=sources.get("explicit"),
                thread_workspace=sources.get("thread_workspace"),
                installation_default=sources.get("installation_default"),
            )
        if precedence == WorkspacePrecedence.TOOL_EXECUTION:
            path = cls.resolve_tool_execution(
                runtime=sources.get("runtime"),
                config=sources.get("config"),
                state=sources.get("state"),
                fallback=sources.get("fallback"),
                use_langgraph_config=sources.get("use_langgraph_config", True),
            )
            if path is not None:
                return ResolvedWorkspace(path=str(path), source="tool_execution")
            return ResolvedWorkspace(path=str(Path.cwd().resolve()), source="cwd")
        msg = f"Unknown precedence: {precedence}"
        raise ValueError(msg)

    @classmethod
    def effective_tool_workspace(
        cls,
        config: Any | None = None,
        *,
        runtime: Any | None = None,
    ) -> Path:
        """Workspace root for tool construction and filesystem operations."""
        from soothe_nano.workspace.workspace_paths import WorkspacePaths

        paths = WorkspacePaths.from_config(config)
        fallback = paths.root
        resolved = cls.resolve_tool_execution(
            runtime=runtime,
            fallback=fallback,
            use_langgraph_config=True,
        )
        if resolved is not None:
            return resolved.resolve()
        return fallback
