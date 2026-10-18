"""Workspace path resolution bound to a root and sandbox policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from soothe_nano.workspace.workspace_runtime import WorkspaceRuntime

# Product layout under the workspace (not soothe-deepagents defaults).
WORKSPACE_BACKUP_DIR = ".soothe/backups"

_UNIX_HOST_ROOT_TOP_NAMES: frozenset[str] = frozenset(
    {
        "Applications",
        "bin",
        "cores",
        "dev",
        "etc",
        "home",
        "Library",
        "opt",
        "private",
        "sbin",
        "sys",
        "System",
        "tmp",
        "usr",
        "Users",
        "var",
        "Volumes",
    }
)


def _config_workspace_root(config: Any | None) -> str | None:
    """Return configured `filesystem_middleware.workspace_root` when set."""
    if config is None:
        return None
    fs = getattr(config, "filesystem_middleware", None)
    root = getattr(fs, "workspace_root", None) if fs is not None else None
    if isinstance(root, str) and root.strip():
        return root
    return None


def _posix_first_segment_name(expanded: Path) -> str | None:
    parts = expanded.parts
    if not parts or parts[0] != "/":
        return None
    if len(parts) < 2:
        return None
    return parts[1]


class WorkspacePaths:
    """Path resolution bound to a workspace root, sandbox mode, and size cap."""

    def __init__(
        self,
        root: Path | str,
        *,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        self._root = Path(root)
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb

    @classmethod
    def from_config(cls, config: Any | None) -> WorkspacePaths:
        """Build from host config: configured root or process default."""
        root_text = _config_workspace_root(config)
        root = (
            Path(root_text).expanduser().resolve()
            if root_text
            else WorkspaceRuntime.process_workspace_root()
        )
        virtual_mode = False
        max_file_size_mb = 10
        if config is not None:
            security = getattr(config, "security", None)
            if security is not None:
                virtual_mode = not getattr(security, "allow_paths_outside_workspace", True)
            fs = getattr(config, "filesystem_middleware", None)
            if fs is not None and hasattr(fs, "max_file_size_mb"):
                max_file_size_mb = int(fs.max_file_size_mb)
        return cls(root, virtual_mode=virtual_mode, max_file_size_mb=max_file_size_mb)

    @property
    def root(self) -> Path:
        """Workspace root path."""
        return self._root

    @property
    def virtual_mode(self) -> bool:
        """Whether paths are sandboxed to the workspace."""
        return self._virtual_mode

    @property
    def max_file_size_mb(self) -> int:
        """Max file size (MB) for filesystem backends."""
        return self._max_file_size_mb

    def should_use_virtual_path_resolution(self, file_path: str) -> bool:
        """True when a leading-`/` path should use virtual sandbox resolution."""
        if not file_path.strip().startswith("/"):
            return False
        expanded = Path(file_path.strip()).expanduser()
        try:
            expanded.resolve().relative_to(self._root.resolve())
        except ValueError:
            pass
        else:
            return False
        first = _posix_first_segment_name(expanded)
        if first is None:
            return True
        return first not in _UNIX_HOST_ROOT_TOP_NAMES

    def resolve_os_path(self, path: str) -> Path:
        """Resolve *path* to the on-disk path the unified filesystem would use."""
        from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend

        backend = NormalizedPathBackend(
            root_dir=self._root.resolve(),
            virtual_mode=self._virtual_mode,
            max_file_size_mb=self._max_file_size_mb,
        )
        return backend.resolve_os_path(path)

    def join_normalized_path(self, normalized: str) -> Path:
        """Convert a validator-normalized logical path to an on-disk path."""
        path = Path(normalized)
        if path.is_absolute():
            return path.resolve()
        return (self._root / normalized).resolve()

    def resolve_backup_dir(
        self,
        configured: str | Path | None = None,
        *,
        backend: Any | None = None,
    ) -> str:
        """Resolve product backup directory for tool/backend use.

        Defaults to workspace `.soothe/backups`. Returns a virtual absolute path
        when the backend is in virtual mode; otherwise a host path under the
        workspace root.
        """
        raw = str(configured).strip() if configured is not None else ""
        rel = raw or WORKSPACE_BACKUP_DIR
        path = Path(rel)
        virtual = bool(getattr(backend, "virtual_mode", False)) if backend is not None else False
        if virtual:
            if path.is_absolute():
                cwd = getattr(backend, "cwd", None)
                if cwd is not None:
                    try:
                        rel_to_cwd = path.resolve().relative_to(Path(str(cwd)).resolve())
                        return "/" + rel_to_cwd.as_posix()
                    except ValueError:
                        return str(path)
                return str(path)
            return "/" + rel.replace("\\", "/").lstrip("/")

        if path.is_absolute():
            return str(path)

        cwd = getattr(backend, "cwd", None) if backend is not None else None
        root: Path | None = None
        if cwd is not None:
            root = Path(str(cwd))
        else:
            root = self._root
        return str(root / path)
