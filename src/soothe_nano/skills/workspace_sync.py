"""Mirror external skill directories into the workspace for virtual-mode filesystem access."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_nano.skills.builtins import SkillRoots

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


class WorkspaceSkillMirror:
    """Mirrors external skills into ``<workspace>/.soothe/skills``.

    Binds a config + workspace pair so the public methods stop threading
    both through every call. Built-in package skills are never copied;
    skills already under the workspace are skipped.
    """

    def __init__(self, config: SootheConfig, workspace: str | Path) -> None:
        self._config = config
        self._workspace = Path(workspace).expanduser().resolve()

    @property
    def workspace(self) -> Path:
        return self._workspace

    def mirror_root(self) -> Path:
        """Return ``<workspace>/.soothe/skills`` (created by callers when syncing)."""
        return self._workspace / ".soothe" / "skills"

    def is_under_workspace(self, path: Path) -> bool:
        """Return True when ``path`` resolves inside the bound workspace."""
        try:
            path.resolve().relative_to(self._workspace.resolve())
        except ValueError:
            return False
        else:
            return True

    def directories_for_resolution(self) -> list[str]:
        """Skill directory search order; workspace mirror paths are last (win on name clash)."""
        dirs: list[str] = list(SkillRoots.builtin_paths(str(self._workspace)))
        if self._config.skills:
            dirs.extend(self._config.skills)
        # Add .agents/skills (Claude-style) before .soothe/skills
        agents_skills = self._workspace / ".agents" / "skills"
        if agents_skills.is_dir():
            for skill_md in agents_skills.glob("*/SKILL.md"):
                dirs.append(str(skill_md.parent.resolve()))
        mirror = self.mirror_root()
        if mirror.is_dir():
            for skill_md in mirror.glob("*/SKILL.md"):
                dirs.append(str(skill_md.parent.resolve()))
        return dirs

    def sync_skill(
        self,
        src: Path,
        *,
        skill_name: str,
    ) -> Path:
        """Copy ``src`` skill tree to ``<workspace>/.soothe/skills/<skill_name>``.

        Args:
            src: Host skill directory (contains ``SKILL.md``).
            skill_name: Canonical skill name (directory name under the mirror).

        Returns:
            Resolved destination directory path.
        """
        dest_root = self.mirror_root()
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / skill_name
        src_resolved = src.resolve()

        if self._mirror_is_current(src_resolved, dest):
            return dest.resolve()

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src_resolved, dest)
        return dest.resolve()

    def collect_external(self) -> dict[str, Path]:
        """Map skill name → host source dir for skills outside the workspace (non-builtin).

        Last-wins across discovery order matches ``SkillCatalog.resolve_skill``.
        """
        from soothe_nano.skills.catalog import SkillCatalog

        by_name: dict[str, Path] = {}
        all_dirs: list[str] = list(SkillRoots.builtin_paths(str(self._workspace)))
        if self._config.skills:
            all_dirs.extend(self._config.skills)
        for dir_path in all_dirs:
            if SkillRoots.is_builtin_directory(dir_path):
                continue
            src = Path(dir_path).expanduser().resolve()
            if not src.is_dir():
                continue
            if self.is_under_workspace(src):
                continue
            meta = SkillCatalog.parse_skill_directory(dir_path)
            if meta is None:
                continue
            skill_name = str(meta.get("name") or src.name).strip()
            if not skill_name:
                continue
            by_name[skill_name] = src
        return by_name

    def sync_all(self) -> dict[str, str]:
        """Mirror external skills into ``<workspace>/.soothe/skills/<name>``.

        Returns:
            Map of skill name → mirrored absolute path under the workspace.
        """
        mirrored: dict[str, str] = {}
        for skill_name, src in self.collect_external().items():
            try:
                dest = self.sync_skill(src, skill_name=skill_name)
            except OSError:
                logger.warning(
                    "Failed to mirror skill %s from %s into workspace",
                    skill_name,
                    src,
                    exc_info=True,
                )
                continue
            mirrored[skill_name] = str(dest)
            logger.debug("Mirrored skill %s: %s -> %s", skill_name, src, dest)
        return mirrored

    def sync_specific(self, skill_name: str) -> Path | None:
        """Mirror a single external skill into ``<workspace>/.soothe/skills/<skill_name>``.

        Returns ``None`` if the skill is not found, is built-in, or is already
        under the workspace.
        """
        from soothe_nano.skills.catalog import SkillCatalog

        # Resolve the skill to get its metadata and path
        catalog = SkillCatalog(self._config, str(self._workspace))
        meta = catalog.resolve_skill(skill_name)
        if meta is None:
            logger.debug("Skill %s not found; skipping sync", skill_name)
            return None

        # Get the source path from metadata
        path_str = meta.get("path")
        if not path_str:
            logger.debug("Skill %s has no path; skipping sync", skill_name)
            return None

        src = Path(path_str).expanduser().resolve()

        # Skip built-in skills (reference text is inlined in prompts)
        if SkillRoots.is_builtin_directory(path_str):
            logger.debug("Skill %s is built-in; skipping sync", skill_name)
            return None

        # Skip skills already under the workspace
        if self.is_under_workspace(src):
            logger.debug("Skill %s is already under workspace; skipping sync", skill_name)
            return None

        # Skip if not a valid directory
        if not src.is_dir():
            logger.debug("Skill %s source is not a directory: %s", skill_name, src)
            return None

        try:
            dest = self.sync_skill(src, skill_name=skill_name)
            logger.debug("Mirrored skill %s: %s -> %s", skill_name, src, dest)
            return dest
        except OSError:
            logger.warning(
                "Failed to mirror skill %s from %s into workspace",
                skill_name,
                src,
                exc_info=True,
            )
            return None

    @staticmethod
    def _tree_max_mtime(root: Path) -> float:
        latest = root.stat().st_mtime
        for entry in root.rglob("*"):
            if entry.is_file():
                latest = max(latest, entry.stat().st_mtime)
        return latest

    @classmethod
    def _mirror_is_current(cls, src: Path, dest: Path) -> bool:
        if not dest.is_dir():
            return False
        try:
            return cls._tree_max_mtime(dest) >= cls._tree_max_mtime(src)
        except OSError:
            return False
