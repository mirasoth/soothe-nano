"""Workspace resolution helpers for tool execution (nano-owned).

The multi-tenant / container-translation workspace policy helpers
(``normalize_user_id``, ``user_id_for_hash``, ``compute_scoped_workspace_dir_name``,
``validate_client_workspace``, ``translate_client_path_to_container``,
``translate_container_path_to_client``) were removed — the host owns canonical
copies in its own workspace-scoped / resolution modules. This module keeps only
``resolve_workspace_for_tool_execution`` and its private helpers, which have
real in-nano callers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _coerce_workspace(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return None


def _workspace_from_configurable(configurable: Any) -> Path | None:
    if not isinstance(configurable, dict):
        return None
    return _coerce_workspace(configurable.get("workspace"))


def _workspace_from_messages(messages: Any) -> Path | None:
    if not isinstance(messages, (list, tuple)):
        return None
    for msg in reversed(messages):
        ws = _coerce_workspace(getattr(msg, "workspace", None))
        if ws is not None:
            return ws
        if isinstance(msg, dict):
            additional = msg.get("additional_kwargs")
            if isinstance(additional, dict):
                ws = _coerce_workspace(additional.get("workspace"))
                if ws is not None:
                    return ws
            ws = _coerce_workspace(msg.get("workspace"))
            if ws is not None:
                return ws
    return None


def _workspace_from_state_dict(state: dict[str, Any] | None) -> Path | None:
    if not isinstance(state, dict):
        return None
    direct = _coerce_workspace(state.get("workspace"))
    if direct is not None:
        return direct
    return _workspace_from_messages(state.get("messages"))


def _runtime_config(runtime: Any) -> dict[str, Any] | None:
    cfg = getattr(runtime, "config", None)
    return cfg if isinstance(cfg, dict) else None


def _runtime_state(runtime: Any) -> dict[str, Any] | None:
    state = getattr(runtime, "state", None)
    return state if isinstance(state, dict) else None


def resolve_workspace_for_tool_execution(
    *,
    runtime: Any | None = None,
    config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    fallback: str | Path | None = None,
    use_langgraph_config: bool = True,
) -> Path | None:
    """Resolve effective workspace for the current tool or agent turn."""
    effective_config = config if config is not None else _runtime_config(runtime)
    effective_state = state if state is not None else _runtime_state(runtime)

    if isinstance(effective_config, dict):
        ws = _workspace_from_configurable(effective_config.get("configurable"))
        if ws is not None:
            return ws

    ws = _workspace_from_state_dict(effective_state)
    if ws is not None:
        return ws

    if use_langgraph_config:
        try:
            from langgraph.config import get_config

            lg_config = get_config()
            if isinstance(lg_config, dict):
                ws = _workspace_from_configurable(lg_config.get("configurable"))
                if ws is not None:
                    return ws
        except Exception:  # noqa: S110
            pass

    from soothe_nano.workspace.workspace_runtime import get_workspace_context

    current = get_workspace_context().workspace
    if current is not None:
        return current

    return _coerce_workspace(fallback)


__all__ = ["resolve_workspace_for_tool_execution"]
