"""Filesystem tool construction via `SootheFilesystemMiddleware`.

Single factory for FS tool instances — the middleware surface is the only
source of file tools (the former `file_ops` toolkit group was retired,
RFC §16 phase-2).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from langchain_core.tools import BaseTool
from soothe_deepagents.backends.protocol import BackendProtocol

from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware


def build_filesystem_tools(
    *,
    backend: BackendProtocol,
    tool_names: Sequence[str] | None = None,
    backup_enabled: bool = True,
    backup_dir: str | None = None,
    workspace_root: str | None = None,
    workspace_backend_factory: Callable[[str], BackendProtocol] | None = None,
    tool_token_limit_before_evict: int = 20000,
) -> list[BaseTool]:
    """Build filesystem tools via `SootheFilesystemMiddleware`.

    Args:
        backend: Filesystem backend for tool operations.
        tool_names: Optional explicit subset of filesystem tool names to expose.
        backup_enabled: Compatibility flag passed to middleware.
        backup_dir: Optional backup directory for delete operations.
        workspace_root: Effective workspace root.
        workspace_backend_factory: Optional per-workspace backend factory.
        tool_token_limit_before_evict: Eviction threshold in characters.

    Returns:
        Instantiated filesystem tools in middleware-defined order.
    """
    middleware_kwargs: dict[str, object] = {
        "backend": backend,
        "backup_enabled": backup_enabled,
        "backup_dir": backup_dir,
        "workspace_root": workspace_root,
        "workspace_backend_factory": workspace_backend_factory,
        "tool_token_limit_before_evict": tool_token_limit_before_evict,
    }
    if tool_names is not None:
        middleware_kwargs["tools"] = list(tool_names)

    middleware = SootheFilesystemMiddleware(**middleware_kwargs)
    return list(middleware.tools)
