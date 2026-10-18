"""Skills catalog: discovery, resolution, and invocation for Soothe."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_nano.config import SootheConfig
from soothe_nano.skills.builtins import SkillRoots
from soothe_nano.skills.workspace_sync import WorkspaceSkillMirror

if TYPE_CHECKING:
    from soothe_nano.skills.index import SkillIndex

logger = logging.getLogger(__name__)


@dataclass
class SkillInvocationEnvelope:
    """Envelope for a skill invocation turn queued to the agent.

    Attributes:
        prompt: Composed skill invocation prompt sent as agent input.
        skill_context: Skill reference only (for execute-step ``<SKILL_CONTEXT>``).
        message_kwargs: Additional kwargs with ``soothe_skill`` marker.
    """

    prompt: str
    skill_context: str
    message_kwargs: dict[str, Any] = field(default_factory=dict)


class SlashSkillLine:
    """``/skill:<name> [args]`` wire-line protocol."""

    @staticmethod
    def format(skill_name: str, args: str | None = None) -> str:
        """Build the canonical user query line for a skill turn (no SKILL.md body).

        Daemon and TUI submit this plain string as loop input; the runner expands it
        into the full skill envelope before the model sees the turn.

        Raises:
            ValueError: If ``skill_name`` is empty after stripping.
        """
        name = str(skill_name or "").strip()
        if not name:
            msg = "skill_name is required for SlashSkillLine.format"
            raise ValueError(msg)
        tail = str(args or "").strip()
        if tail:
            return f"/skill:{name} {tail}"
        return f"/skill:{name}"

    @staticmethod
    def parse(text: str) -> tuple[str, str] | None:
        """Parse a user line that selects a skill via ``/skill:<name>``.

        The prefix match is case-insensitive. The skill token is normalized to
        lowercase so it matches wire/catalog names consistently with the CLI TUI.

        Returns:
            ``(skill_name_lower, trailing_args)`` when the trimmed text begins with
            ``/skill:`` and a non-empty name follows; otherwise ``None``.
        """
        s = text.strip()
        if len(s) < len("/skill:") + 1:
            return None
        if s[: len("/skill:")].lower() != "/skill:":
            return None
        rest = s[len("/skill:") :].strip()
        if not rest:
            return None
        parts = rest.split(maxsplit=1)
        if not parts[0]:
            return None
        skill_token = parts[0].lower()
        tail = parts[1] if len(parts) > 1 else ""
        return (skill_token, tail)


class SkillCatalog:
    """Skill resolution and invocation composition bound to config + workspace."""

    def __init__(
        self,
        config: SootheConfig,
        workspace: str | Path | None = None,
    ) -> None:
        self._config = config
        ws = workspace if workspace is not None else str(Path.cwd().resolve())
        self._workspace = str(ws)
        self._mirror = WorkspaceSkillMirror(config, ws)

    @property
    def workspace(self) -> str:
        return self._workspace

    # ------------------------------------------------------------------
    # Skill directory parsing (deepagents public skill APIs)
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        """Remove frontmatter block, returning only the body content."""
        from soothe_deepagents.middleware.skills import strip_skill_frontmatter

        return strip_skill_frontmatter(text)

    @staticmethod
    def parse_skill_directory(skill_dir: str | Path) -> dict[str, Any] | None:
        """Parse a skill directory's SKILL.md via deepagents ``parse_skill_metadata``.

        Returns:
            Metadata dict with ``name``, ``description``, ``path``, and optional
            fields, or ``None`` if the directory is invalid.
        """
        from soothe_deepagents.middleware.skills import parse_skill_metadata

        skill_path = Path(skill_dir)
        md_file = skill_path / "SKILL.md"
        if not md_file.exists():
            return None

        try:
            text_content = md_file.read_text(encoding="utf-8")
        except OSError:
            logger.debug("Failed to read SKILL.md in %s", skill_dir)
            return None

        meta = parse_skill_metadata(text_content, str(md_file), skill_path.name)
        if meta is None:
            # Soft product fallback: name from directory, description from body.
            body = SkillCatalog._strip_frontmatter(text_content)
            description = ""
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    description = stripped.lstrip("#").strip()
                    break
                if stripped:
                    description = stripped
                    break
            if not description:
                return None
            return {
                "name": skill_path.name,
                "description": description,
                "path": str(skill_path.resolve()),
                "source": "",
                "version": "",
                "tags": "",
                "tools": None,
                "default_model": None,
                "requires": None,
                "paths": None,
                "when_to_use": None,
                "core": None,
            }

        return {
            "name": meta["name"],
            "description": meta["description"],
            "path": str(skill_path.resolve()),
            "source": meta.get("metadata", {}).get("source", ""),
            "version": meta.get("metadata", {}).get("version", ""),
            "tags": meta.get("tags") or "",
            "tools": meta.get("allowed_tools") or None,
            "default_model": meta.get("metadata", {}).get("default_model"),
            "requires": meta.get("metadata", {}).get("requires"),
            "paths": meta.get("paths"),
            "when_to_use": meta.get("when_to_use"),
            "core": meta.get("core"),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wire_entries(
        self,
        *,
        skill_index: SkillIndex | None = None,
        mcp_registry: Any | None = None,
    ) -> list[dict[str, str]]:
        """Return wire-safe skill metadata sorted by name.

        When ``skill_index`` is provided, global user skills are served from the
        cached index (fast, stat-only invalidation) and only workspace-local skills
        are scanned from the filesystem. Without an index, falls back to a full
        filesystem scan.

        Args:
            skill_index: Optional ``SkillIndex`` instance for incremental loading.
            mcp_registry: Optional ``MCPRegistry`` to include MCP server prompts.

        Returns:
            List of ``{name, description, source, version?}`` dicts sorted
            alphabetically by name. No ``path`` field is included.
        """
        if skill_index is not None:
            entries = self._wire_entries_from_index(skill_index)
        else:
            entries = self._wire_entries_full_scan()

        if mcp_registry is not None:
            self._merge_mcp_prompt_entries(entries, mcp_registry)

        return entries

    def resolve_skill(self, skill_name: str) -> dict[str, Any] | None:
        """Resolve skill name to metadata with path (last-wins precedence).

        Searches skill directories in order: built-in first, then user/project
        directories from config. The last matching entry wins, allowing user
        overrides of built-in skills.

        Returns:
            Metadata dict with ``path`` field for daemon-side file access,
            or ``None`` if the skill is not found.
        """
        all_dirs = self._mirror.directories_for_resolution()

        # Last-wins: iterate all, keep last match
        result: dict[str, Any] | None = None
        for dir_path in all_dirs:
            meta = self.parse_skill_directory(dir_path)
            if meta is None:
                continue
            if meta["name"] == skill_name:
                meta["source"] = self._source_label_for_path(dir_path)
                result = meta

        return result

    def read_markdown(self, meta: dict[str, Any]) -> str | None:
        """Read SKILL.md content from resolved metadata.

        Returns:
            Full SKILL.md content (frontmatter + body), or ``None`` if read fails.
        """
        path_str = meta.get("path")
        if not path_str:
            return None

        md_file = Path(path_str) / "SKILL.md"
        try:
            return md_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Failed to read SKILL.md at %s", md_file)
            return None

    def build_context_text(self, meta: dict[str, Any], markdown: str) -> str:
        """Compose skill reference text (name, folder path, description, SKILL.md body).

        Used for execute-step ``<SKILL_CONTEXT>`` blocks; excludes the short user instruction
        prefix that ``build_invocation_envelope`` places ahead of the reference.
        """
        body = self._strip_frontmatter(markdown)
        name = meta.get("name", "")
        description = meta.get("description", "")
        skill_dir = str(meta.get("path") or "").strip()
        source = str(meta.get("source") or "").strip().lower()

        reference_parts: list[str] = []
        if name:
            reference_parts.append(f"Skill: {name}")
        if skill_dir and source != "builtin" and not SkillRoots.is_builtin_directory(skill_dir):
            reference_parts.append(
                f"Skill folder: {skill_dir}\n"
                "(Additional files may live under this directory — use filesystem tools to "
                "read them when SKILL.md is not sufficient.)"
            )
        if description:
            reference_parts.append(f"Description: {description}")
        if body.strip():
            reference_parts.append(body.strip())
        return "\n\n".join(reference_parts)

    def build_invocation_envelope(
        self,
        meta: dict[str, Any],
        markdown: str,
        args: str | None = None,
    ) -> SkillInvocationEnvelope:
        """Compose skill invocation envelope for agent turn.

        Args:
            meta: Skill metadata dict (``name``, ``description``, etc.).
            markdown: Full SKILL.md content (frontmatter + body).
            args: Optional trailing user text after ``/skill:``; placed first in the composed
                prompt so short instructions are not buried after SKILL.md content.
        """
        reference_text = self.build_context_text(meta, markdown)
        name = meta.get("name", "")

        user_instruction = (args or "").strip()
        composed: list[str] = []
        if user_instruction:
            composed.append(
                "User instruction (short — prioritize this over long skill reference text):\n"
                f"{user_instruction}"
            )
        if reference_text:
            composed.append(
                "Skill reference (instructions, constraints, workflow — use to carry out "
                "the user instruction):\n" + reference_text
            )
        prompt = "\n\n".join(composed) if composed else reference_text

        message_kwargs = {
            "additional_kwargs": {
                "soothe_skill": name,
            },
        }

        return SkillInvocationEnvelope(
            prompt=prompt,
            skill_context=reference_text,
            message_kwargs=message_kwargs,
        )

    def try_expand_slash_line(self, text: str) -> SkillInvocationEnvelope | None:
        """If ``text`` is a ``/skill:`` line, resolve the skill and build the model envelope.

        When resolution fails (unknown skill, unreadable SKILL.md), returns ``None``
        so callers can fall back to treating ``text`` as a normal user message.
        """
        parsed = SlashSkillLine.parse(text)
        if parsed is None:
            return None
        skill_name, args = parsed
        meta = self.resolve_skill(skill_name)
        if meta is None:
            return None
        md = self.read_markdown(meta)
        if md is None or not str(md).strip():
            return None
        return self.build_invocation_envelope(meta, md, args)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _source_label_for_path(self, skill_dir: str | Path) -> str:
        """Return the source label for a skill directory relative to the workspace.

        Labels mirror the index path so the fallback (no-index) scan is consistent:

        - ``builtin``  — package-bundled or host-registered skill root
        - ``agents``   — ``<workspace>/.agents/skills/<skill>``
        - ``project``  — ``<workspace>/.soothe/skills/<skill>``
        - ``user``     — any other user/config-provided directory
        """
        resolved = Path(skill_dir).expanduser().resolve()
        if SkillRoots.is_builtin_directory(resolved):
            return "builtin"
        try:
            ws = Path(self._workspace).expanduser().resolve()
        except (OSError, ValueError):
            return "user"
        agents_root = ws / ".agents" / "skills"
        project_root = self._mirror.mirror_root()
        try:
            if resolved == agents_root or resolved.is_relative_to(agents_root):
                return "agents"
            if resolved == project_root or resolved.is_relative_to(project_root):
                return "project"
        except (ValueError, OSError):
            pass
        return "user"

    def _wire_entries_from_index(
        self,
        skill_index: SkillIndex,
    ) -> list[dict[str, str]]:
        """Build wire entries using cached index for global skills + filesystem for workspace."""
        entries: list[dict[str, str]] = []
        seen_names: set[str] = set()

        # Global user skills from index (fast path)
        for idx_entry in skill_index.rebuild_if_stale():
            entry: dict[str, Any] = {
                "name": idx_entry.name,
                "description": idx_entry.description,
                "source": idx_entry.source,
            }
            if idx_entry.tags:
                entry["tags"] = idx_entry.tags
            if idx_entry.paths is not None:
                entry["paths"] = list(idx_entry.paths)
            if idx_entry.when_to_use is not None:
                entry["when_to_use"] = idx_entry.when_to_use
            seen_names.add(idx_entry.name)
            entries.append(entry)

        # Workspace-local skills (filesystem scan, small set)
        ws_path = Path(self._workspace)

        # Scan .agents/skills (Claude-style) and .soothe/skills (last-wins)
        project_skill_roots = [
            (ws_path / ".agents" / "skills", "agents"),
            (self._mirror.mirror_root(), "project"),
        ]

        for skill_root, source_label in project_skill_roots:
            if not skill_root.is_dir():
                continue
            for skill_md in skill_root.glob("*/SKILL.md"):
                meta = self.parse_skill_directory(str(skill_md.parent.resolve()))
                if meta is None:
                    continue
                name = meta["name"]
                # Workspace wins over global (last-wins)
                if name in seen_names:
                    entries = [e for e in entries if e["name"] != name]
                seen_names.add(name)
                entry = {
                    "name": name,
                    "description": meta["description"],
                    "source": source_label,
                }
                if meta.get("version"):
                    entry["version"] = meta["version"]
                if meta.get("paths"):
                    entry["paths"] = meta["paths"]
                if meta.get("when_to_use"):
                    entry["when_to_use"] = meta["when_to_use"]
                entries.append(entry)

        entries.sort(key=lambda e: e["name"].lower())
        return entries

    def _wire_entries_full_scan(self) -> list[dict[str, str]]:
        """Legacy full-scan path (no index available)."""
        all_dirs = self._mirror.directories_for_resolution()

        entries: list[dict[str, str]] = []
        seen_names: set[str] = set()

        for dir_path in all_dirs:
            meta = self.parse_skill_directory(dir_path)
            if meta is None:
                continue

            source = self._source_label_for_path(dir_path)

            entry: dict[str, Any] = {
                "name": meta["name"],
                "description": meta["description"],
                "source": source,
            }
            if meta.get("version"):
                entry["version"] = meta["version"]
            if meta.get("paths"):
                entry["paths"] = meta["paths"]
            if meta.get("when_to_use"):
                entry["when_to_use"] = meta["when_to_use"]

            if meta["name"] in seen_names:
                entries = [e for e in entries if e["name"] != meta["name"]]
            seen_names.add(meta["name"])
            entries.append(entry)

        entries.sort(key=lambda e: e["name"].lower())
        return entries

    @staticmethod
    def _merge_mcp_prompt_entries(
        entries: list[dict[str, Any]],
        mcp_registry: Any,
    ) -> None:
        """Append MCP server prompt descriptors into skill wire entries in-place."""
        try:
            server_prompts = mcp_registry.prompts()
        except Exception:  # noqa: BLE001
            return
        seen = {e["name"] for e in entries}
        for server_name, prompts in server_prompts.items():
            for p in prompts:
                name = p.get("name", "")
                if not name or name in seen:
                    continue
                entry: dict[str, Any] = {
                    "name": name,
                    "description": p.get("description") or f"MCP prompt from {server_name}",
                    "source": f"mcp:{server_name}",
                }
                seen.add(name)
                entries.append(entry)
        entries.sort(key=lambda e: e["name"].lower())
