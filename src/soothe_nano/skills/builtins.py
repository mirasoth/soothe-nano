"""Skill discovery helpers for built-in and user-installed skills."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from soothe_deepagents.backends.filesystem import FilesystemBackend
from soothe_deepagents.middleware.skills import list_skills

_BUILTIN_SKILLS_DIR_NAME = "builtin"


class SkillRoots:
    """Process-level skill root registry (user, builtin, host-registered).

    Host packages register extra roots via :meth:`register`; registered roots
    appear in :meth:`roots` between nano's own ``builtin`` directory and
    ``~/.soothe/skills``, so user installs still win on name clashes.
    """

    # Host packages (e.g. fj) register extra roots here. Process-local.
    _EXTRA_ROOTS: ClassVar[list[tuple[Path, str]]] = []
    _LOCK: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def register(
        cls,
        root: str | Path,
        *,
        source: str = "builtin",
    ) -> Callable[[], None]:
        """Register a host-packaged skill root (directory of skill folders).

        Args:
            root: Directory containing ``<skill-name>/SKILL.md`` children.
            source: Source label stored on index entries (default ``builtin``).

        Returns:
            Unregister callback. Duplicate resolved paths are ignored.
        """
        path = Path(root).expanduser().resolve()
        with cls._LOCK:
            if not any(existing == path for existing, _ in cls._EXTRA_ROOTS):
                cls._EXTRA_ROOTS.append((path, source))

        def _unregister() -> None:
            with cls._LOCK:
                cls._EXTRA_ROOTS[:] = [
                    (existing, label) for existing, label in cls._EXTRA_ROOTS if existing != path
                ]

        return _unregister

    @classmethod
    def roots(cls) -> list[tuple[Path, str]]:
        """Return skill roots in last-wins precedence order.

        Order:
        1. ``~/.agents/skills`` (user)
        2. Package ``soothe_nano/skills/builtin`` (builtin)
        3. Host-registered roots via :meth:`register` (builtin)
        4. ``$SOOTHE_HOME/skills`` (user)
        """
        from soothe_nano.config import SOOTHE_HOME

        skills_pkg = Path(__file__).resolve().parent
        found: list[tuple[Path, str]] = [
            (Path.home() / ".agents" / "skills", "user"),
            (skills_pkg / _BUILTIN_SKILLS_DIR_NAME, "builtin"),
        ]
        with cls._LOCK:
            found.extend(cls._EXTRA_ROOTS)
        found.append((SOOTHE_HOME / "skills", "user"))
        return found

    @classmethod
    def is_builtin_directory(cls, skill_dir: str | Path) -> bool:
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

        with cls._LOCK:
            extras = list(cls._EXTRA_ROOTS)
        for root, source in extras:
            if source != "builtin":
                continue
            try:
                if resolved == root or resolved.is_relative_to(root):
                    return True
            except (ValueError, OSError):
                continue
        return False

    @classmethod
    def builtin_paths(cls, workspace: str | None = None) -> list[str]:
        """Return absolute paths for discovered skill directories.

        A valid skill directory contains a `SKILL.md` file. The search includes:
        - User skills in `~/.agents/skills/`
        - Package-bundled built-ins (`soothe_nano/skills/builtin/`)
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
        candidate_roots = [root for root, _source in cls.roots()]

        if workspace:
            ws_path = Path(workspace).expanduser().resolve()
            candidate_roots.append(ws_path / ".agents" / "skills")
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
