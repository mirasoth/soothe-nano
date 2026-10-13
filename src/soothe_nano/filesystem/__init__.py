"""Unified filesystem interface for Soothe.

Composes `LocalFilesystem` and `WorkspaceFilesystem` over the shared
`UnifiedFilesystem` protocol. Protocol result types (`ReadResult`, `GrepResult`,
etc.) come from `soothe_deepagents.backends.protocol`.
"""

from __future__ import annotations

from .exceptions import (
    DirectoryNotEmptyError,
    FilesystemError,
    FileTooLargeError,
    InvalidPathError,
    NotADirectoryError,
    NotAFileError,
    PathNotFoundError,
    PathTraversalError,
    PermissionDeniedError,
)
from .local import LocalFilesystem
from .unified import UnifiedFilesystem
from .workspace import WorkspaceFilesystem

__all__ = [
    # Core interface
    "UnifiedFilesystem",
    # Implementations
    "LocalFilesystem",
    "WorkspaceFilesystem",
    # Exceptions
    "FilesystemError",
    "PathNotFoundError",
    "PermissionDeniedError",
    "PathTraversalError",
    "InvalidPathError",
    "FileTooLargeError",
    "DirectoryNotEmptyError",
    "NotADirectoryError",
    "NotAFileError",
]
