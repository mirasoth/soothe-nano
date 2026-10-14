"""Workspace management package."""

from soothe_nano.workspace.workspace_api import (
    ResolvedWorkspace,
    WorkspacePrecedence,
    resolve_workspace_for_stream,
    resolve_workspace_for_tool_execution,
)
from soothe_nano.workspace.workspace_filesystem import (
    FrameworkFilesystem,
    NormalizedPathBackend,
    WorkspaceAwareBackend,
    get_workspace_backend,
)
from soothe_nano.workspace.workspace_runtime import (
    WorkspaceContext,
    get_virtual_home,
    get_virtual_home_relative_path,
    get_virtual_mode,
)

__all__ = [
    "FrameworkFilesystem",
    "NormalizedPathBackend",
    "ResolvedWorkspace",
    "WorkspaceAwareBackend",
    "WorkspaceContext",
    "WorkspacePrecedence",
    "get_virtual_home",
    "get_virtual_home_relative_path",
    "get_virtual_mode",
    "get_workspace_backend",
    "resolve_workspace_for_stream",
    "resolve_workspace_for_tool_execution",
]
