"""Workspace management package."""

from soothe_nano.workspace.workspace_api import (
    ResolvedWorkspace,
    ResolvedWorkspaceSource,
    WorkspacePrecedence,
)
from soothe_nano.workspace.workspace_filesystem import (
    FrameworkFilesystem,
    NormalizedPathBackend,
    WorkspaceAwareBackend,
    WorkspaceBackendRegistry,
)
from soothe_nano.workspace.workspace_paths import (
    WORKSPACE_BACKUP_DIR,
    WorkspacePaths,
)
from soothe_nano.workspace.workspace_policy import WorkspaceResolver
from soothe_nano.workspace.workspace_runtime import (
    WorkspaceContext,
    WorkspaceRuntime,
)

__all__ = [
    "FrameworkFilesystem",
    "NormalizedPathBackend",
    "ResolvedWorkspace",
    "ResolvedWorkspaceSource",
    "WORKSPACE_BACKUP_DIR",
    "WorkspaceAwareBackend",
    "WorkspaceBackendRegistry",
    "WorkspaceContext",
    "WorkspacePaths",
    "WorkspacePrecedence",
    "WorkspaceResolver",
    "WorkspaceRuntime",
]
