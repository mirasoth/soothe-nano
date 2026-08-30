"""Unified filesystem interface for Soothe.

Composes `LocalFilesystem`, `WorkspaceFilesystem`, factory helpers, and the
LangChain adapter over soothe-deepagents backends. Protocol result types
(`ReadResult`, `GrepResult`, etc.) come from `soothe_deepagents.backends.protocol`.
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
from .factory import (
    FilesystemConfig,
    FilesystemFactory,
    FilesystemType,
    PathValidationConfig,
    SecurityConfig,
    create_filesystem,
)
from .langchain_adapter import LangChainAdapter
from .local import LocalFilesystem
from .unified import UnifiedFilesystem
from .workspace import WorkspaceFilesystem

__all__ = [
    # Core interface
    "UnifiedFilesystem",
    # Implementations
    "LocalFilesystem",
    "WorkspaceFilesystem",
    # Adapters
    "LangChainAdapter",
    # Factory and configuration
    "FilesystemFactory",
    "FilesystemConfig",
    "FilesystemType",
    "PathValidationConfig",
    "SecurityConfig",
    "create_filesystem",
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
