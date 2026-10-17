"""File operations toolkit -- surgical file manipulation plugin.

Also hosts the shared catalog for filesystem tool construction so resolver
and plugin paths stay aligned.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from langchain_core.tools import BaseTool
from soothe_deepagents.backends.protocol import BackendProtocol

from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware
from soothe_nano.plugin import plugin

logger = logging.getLogger(__name__)

SURGICAL_FILE_OP_TOOL_NAMES: tuple[str, ...] = (
    "delete",
    "file_info",
    "edit_lines",
    "insert_lines",
    "delete_lines",
    "apply_diff",
)
"""Canonical surgical file-operation tool names exposed by `file_ops`."""

SURGICAL_FILE_OP_TOOL_NAME_SET: frozenset[str] = frozenset(SURGICAL_FILE_OP_TOOL_NAMES)


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


def build_surgical_file_ops_tools(
    *,
    backend: BackendProtocol,
    backup_enabled: bool = True,
    backup_dir: str | None = None,
    workspace_root: str | None = None,
    workspace_backend_factory: Callable[[str], BackendProtocol] | None = None,
    tool_token_limit_before_evict: int = 20000,
) -> list[BaseTool]:
    """Build the canonical surgical `file_ops` tool set."""
    # deepagents FilesystemMiddleware requires `read_file` in any explicit
    # allowlist; include it for construction, then drop it from returned tools.
    tools = build_filesystem_tools(
        backend=backend,
        tool_names=("read_file", *SURGICAL_FILE_OP_TOOL_NAMES),
        backup_enabled=backup_enabled,
        backup_dir=backup_dir,
        workspace_root=workspace_root,
        workspace_backend_factory=workspace_backend_factory,
        tool_token_limit_before_evict=tool_token_limit_before_evict,
    )
    return [tool for tool in tools if getattr(tool, "name", None) in SURGICAL_FILE_OP_TOOL_NAME_SET]


@plugin(
    name="file_ops", version="2.0.0", description="File system operations", trust_level="built-in"
)
class FileOpsPlugin:
    """File operations tools plugin.

    Tools are provided by SootheFilesystemMiddleware for consistent
    implementation patterns (schema validation, path validation, backend usage).
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools with workspace from config.

        Args:
            context: Plugin context with config and logger.
        """
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.workspace.workspace_paths import (
            WORKSPACE_BACKUP_DIR,
            filesystem_virtual_mode_from_soothe_config,
            max_file_size_mb_for_filesystem_backend,
        )
        from soothe_nano.workspace.workspace_runtime import resolve_process_workspace_root

        sc = context.soothe_config
        workspace_root = context.config.get("workspace_root") or str(
            resolve_process_workspace_root()
        )
        fs_config = dict(context.config.get("filesystem_middleware", {}))
        virtual_mode = filesystem_virtual_mode_from_soothe_config(sc)
        max_file_size_mb = fs_config.get(
            "max_file_size_mb", max_file_size_mb_for_filesystem_backend(sc)
        )
        backup_dir = fs_config.get("backup_dir") or WORKSPACE_BACKUP_DIR

        backend = FilesystemBackend(
            root_dir=workspace_root or None,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
            backup_dir=backup_dir,
        )

        self._tools = build_surgical_file_ops_tools(
            backend=backend,
            backup_enabled=fs_config.get("backup_enabled", True),
            backup_dir=backup_dir,
            workspace_root=workspace_root or None,
            tool_token_limit_before_evict=fs_config.get("tool_token_limit_before_evict", 20000),
        )

        context.logger.info(
            "Loaded %d file_ops surgical tools (workspace=%s)",
            len(self._tools),
            workspace_root,
        )

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of file operation tool instances.
        """
        return self._tools
