"""Skill discovery helpers for built-in and user-installed skills."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from soothe_deepagents.backends.filesystem import FilesystemBackend
from soothe_deepagents.middleware.skills import list_skills

_BUILTIN_SKILLS_DIR_NAME = "builtin_skills"

# Host packages (e.g. fj) register extra roots here. Process-local.
_EXTRA_SKILL_ROOTS: list[tuple[Path, str]] = []
_EXTRA_SKILL_ROOTS_LOCK = threading.Lock()


def register_builtin_skill_root(
    root: str | Path,
    *,
    source: str = "builtin",
) -> Callable[[], None]:
    """Register a host-packaged skill root (directory of skill folders).

    Registered roots appear in :func:`iter_skill_roots` between nano's own
    ``builtin_skills`` and ``~/.soothe/skills``, so user installs still win.

    Args:
        root: Directory containing ``<skill-name>/SKILL.md`` children.
        source: Source label stored on index entries (default ``builtin``).

    Returns:
        Unregister callback. Duplicate resolved paths are ignored.
    """
    path = Path(root).expanduser().resolve()
    with _EXTRA_SKILL_ROOTS_LOCK:
        if not any(existing == path for existing, _ in _EXTRA_SKILL_ROOTS):
            _EXTRA_SKILL_ROOTS.append((path, source))

    def _unregister() -> None:
        with _EXTRA_SKILL_ROOTS_LOCK:
            _EXTRA_SKILL_ROOTS[:] = [
                (existing, label) for existing, label in _EXTRA_SKILL_ROOTS if existing != path
            ]

    return _unregister


def iter_skill_roots() -> list[tuple[Path, str]]:
    """Return skill roots in last-wins precedence order.

    Order:
    1. ``~/.agents/skills`` (user)
    2. Package ``soothe_nano/skills/builtin_skills`` (builtin)
    3. Host-registered roots via :func:`register_builtin_skill_root` (builtin)
    4. ``$SOOTHE_HOME/skills`` (user)
    """
    from soothe_nano.config import SOOTHE_HOME

    skills_pkg = Path(__file__).resolve().parent
    roots: list[tuple[Path, str]] = [
        (Path.home() / ".agents" / "skills", "user"),
        (skills_pkg / _BUILTIN_SKILLS_DIR_NAME, "builtin"),
    ]
    with _EXTRA_SKILL_ROOTS_LOCK:
        roots.extend(_EXTRA_SKILL_ROOTS)
    roots.append((SOOTHE_HOME / "skills", "user"))
    return roots


def is_builtin_skill_directory(skill_dir: str | Path) -> bool:
    """Return True for nano or host-registered package-bundled skill directories."""
    resolved = Path(skill_dir).expanduser().resolve()
    package_builtins = Path(__file__).resolve().parent / _BUILTIN_SKILLS_DIR_NAME
    try:
        if resolved == package_builtins.resolve() or resolved.is_relative_to(
            package_builtins.resolve()
        ):
            return True
    except (ValueError, OSError):
        pass

    with _EXTRA_SKILL_ROOTS_LOCK:
        extras = list(_EXTRA_SKILL_ROOTS)
    for root, source in extras:
        if source != "builtin":
            continue
        try:
            if resolved == root or resolved.is_relative_to(root):
                return True
        except (ValueError, OSError):
            continue
    return False


def get_built_in_skills_paths(workspace: str | None = None) -> list[str]:
    """Return absolute paths for discovered skill directories.

    A valid skill directory contains a `SKILL.md` file. The search includes:
    - User skills in `~/.agents/skills/`
    - Package-bundled built-ins (`soothe_nano/skills/builtin_skills/`)
    - Host-registered builtin skill roots
    - User skills in `~/.soothe/skills/` (``SOOTHE_HOME/skills``)
    - Project skills in `<workspace>/.soothe/skills/` (if workspace provided)

    When the same skill name exists in multiple roots, later roots win
    (last-wins dedup). Workspace overrides ``~/.soothe`` which overrides
    built-ins which override ``~/.agents``.

    Args:
        workspace: Optional workspace directory path for project-local skills.

    Returns:
        Sorted absolute paths to skill directories.
    """
    candidate_roots = [root for root, _source in iter_skill_roots()]

    if workspace:
        ws_path = Path(workspace).expanduser().resolve()
        candidate_roots.append(ws_path / ".soothe" / "skills")

    by_name: dict[str, str] = {}
    for root in candidate_roots:
        if not root.exists() or not root.is_dir():
            continue
        backend = FilesystemBackend(root_dir=root, virtual_mode=True)
        for skill in list_skills(backend, "/"):
            # Virtual backend paths look like ``/skill-name/SKILL.md``.
            rel = str(skill["path"]).lstrip("/")
            skill_dir = (root / Path(rel).parent).resolve()
            by_name[skill["name"].lower()] = str(skill_dir)

    return sorted(by_name.values())
