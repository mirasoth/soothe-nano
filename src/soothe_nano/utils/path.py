"""Path expansion and resolution utilities."""

from __future__ import annotations

from pathlib import Path

from soothe_nano._rust_compat import expand_env_vars_rust


def expand_path(path: str | Path) -> Path:
    """Expand and resolve a filesystem path.

    Handles:
    - Home directory expansion (~ and ~user)
    - Environment variable expansion ($VAR and ${VAR})
    - Relative path resolution to absolute path
    - Symlink resolution

    Args:
        path: Path string or Path object to expand.

    Returns:
        Expanded and resolved absolute Path.
    """
    path_str = str(path)
    expanded = expand_env_vars_rust(path_str)
    return Path(expanded).expanduser().resolve()
