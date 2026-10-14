"""Mtime-based skill index for fast process-level skill discovery.

Indexes skills under ``~/.agents/skills``, package-bundled
``skills/builtin/``, host-registered roots, and ``~/.soothe/skills``.
Uses stat-only invalidation: re-parses SKILL.md only when mtime changes.
Persists cache to ~/.soothe/cache/skill_index.json for fast restarts.

Core indexing logic (frontmatter parsing, discovery, cache I/O) is
implemented in Rust (``soothe-nano-skills`` crate) and exposed via the
``_rust`` extension. This module provides the Python-facing API that
delegates to Rust while keeping ``iter_skill_roots()`` in Python (it
returns Python ``Path`` objects and depends on process-local state).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soothe_nano._rust_compat import get_rust_module
from soothe_nano.skills.builtins import iter_skill_roots

logger = logging.getLogger(__name__)

_CACHE_FILE = Path.home() / ".soothe" / "cache" / "skill_index.json"

# Package-bundled built-in skills directory (kept for tests / introspection)
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent / "builtin"

_rust = get_rust_module()
_RustSkillIndex = _rust.SkillIndex if _rust is not None else None


@dataclass(frozen=True, slots=True)
class SkillIndexEntry:
    """Lightweight skill metadata cached by the index."""

    name: str
    description: str
    tags: str
    source: str  # "builtin" | "agents" | "project" | "user"
    path: str
    mtime: float
    paths: tuple[str, ...] | None = None  # conditional activation patterns
    when_to_use: str | None = None  # multi-line guidance for listing
    core: bool | None = None  # True=core tier, False=deferred, None=inherit


@dataclass
class SkillIndex:
    """Mtime-aware skill index; re-parses SKILL.md only when mtime changes.

    Scans community, built-in, host-registered, and user skill directories.
    On name clashes across roots, the later root wins
    (``~/.soothe/skills`` > host builtins > nano builtins > ``~/.agents/skills``).
    Workspace/project skills are resolved by the loop at runtime, not here.
    """

    _entries: dict[str, SkillIndexEntry] = field(default_factory=dict)
    _loaded: bool = field(default=False)

    def entries(self) -> list[SkillIndexEntry]:
        """Return all indexed entries sorted by name."""
        self._ensure_loaded()
        return sorted(self._entries.values(), key=lambda e: e.name.lower())

    def resolve(self, name: str) -> SkillIndexEntry | None:
        """Resolve a skill by name (case-insensitive)."""
        self._ensure_loaded()
        return self._entries.get(name.lower())

    def rebuild_if_stale(self) -> list[SkillIndexEntry]:
        """Stat all skill directories; re-parse only changed entries.

        Returns the full list of current entries after refresh.
        """
        roots = [(str(root), source) for root, source in iter_skill_roots()]
        cache_path = str(_CACHE_FILE)

        if _RustSkillIndex is not None:
            rust_index = _RustSkillIndex()
            if self._loaded:
                # Restore entries from our cache into the Rust index so it can
                # compare mtimes without re-parsing unchanged skills.
                rust_index.load_cache(cache_path)
            rust_entries = rust_index.rebuild_if_stale(roots, cache_path)
            self._entries = {e.name.lower(): _rust_entry_to_py(e) for e in rust_entries}
            self._loaded = True
            return self.entries()

        # Fallback: pure-Python path (should not normally execute)
        return self._rebuild_if_stale_python(roots, cache_path)

    def wire_entries(self) -> list[dict[str, Any]]:
        """Return wire-safe dicts (no path) for RPC serialization."""
        result: list[dict[str, Any]] = []
        for entry in self.entries():
            d: dict[str, Any] = {
                "name": entry.name,
                "description": entry.description,
                "source": entry.source,
            }
            if entry.tags:
                d["tags"] = entry.tags
            if entry.paths is not None:
                d["paths"] = list(entry.paths)
            if entry.when_to_use is not None:
                d["when_to_use"] = entry.when_to_use
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load_cache()
            self.rebuild_if_stale()

    def _load_cache(self) -> None:
        """Load persisted index from disk if available."""
        if _RustSkillIndex is not None:
            rust_index = _RustSkillIndex()
            rust_index.load_cache(str(_CACHE_FILE))
            # Extract entries from the Rust index into our Python dict
            for entry in rust_index.entries():
                py_entry = _rust_entry_to_py(entry)
                self._entries[py_entry.name.lower()] = py_entry
            self._loaded = True
            return

        # Fallback: pure-Python path
        self._load_cache_python()

    def _persist(self) -> None:
        """Write current index to disk cache."""
        # Rust path: persist is handled internally by rebuild_if_stale.
        # This method is only called from the pure-Python fallback path.
        self._persist_python()

    # ------------------------------------------------------------------
    # Pure-Python fallback (kept for resilience; not normally exercised)
    # ------------------------------------------------------------------

    def _rebuild_if_stale_python(
        self, roots: list[tuple[str, str]], cache_path: str
    ) -> list[SkillIndexEntry]:
        """Pure-Python rebuild fallback."""
        import os

        current_skills: dict[str, tuple[Path, float, str]] = {}
        for root_str, source in roots:
            root = Path(root_str)
            if not root.is_dir():
                continue
            try:
                entries = os.scandir(root)
            except OSError:
                continue
            with entries:
                for dir_entry in entries:
                    if not dir_entry.is_dir(follow_symlinks=True):
                        continue
                    skill_md = Path(dir_entry.path) / "SKILL.md"
                    try:
                        st = skill_md.stat()
                    except OSError:
                        continue
                    skill_name_key = self._discover_skill_name_key(skill_md, dir_entry.name)
                    current_skills[skill_name_key] = (
                        Path(dir_entry.path).resolve(),
                        st.st_mtime,
                        source,
                    )

        changed = False
        new_entries: dict[str, SkillIndexEntry] = {}
        for key, (skill_dir, mtime, source) in current_skills.items():
            existing = self._entries.get(key)
            if existing and existing.mtime >= mtime and existing.path == str(skill_dir):
                new_entries[key] = existing
            else:
                entry = self._parse_skill_dir(skill_dir, mtime, source=source)
                if entry:
                    new_entries[entry.name.lower()] = entry
                    changed = True

        if set(self._entries.keys()) != set(new_entries.keys()):
            changed = True

        self._entries = new_entries
        self._loaded = True

        if changed:
            self._persist_python()

        return self.entries()

    def _discover_skill_name_key(self, skill_md: Path, fallback_dir_name: str) -> str:
        """Return lowercase dedupe key from frontmatter ``name`` when available."""
        fallback = str(fallback_dir_name).strip().lower()
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            return fallback
        try:
            from soothe_deepagents.middleware.skills import parse_skill_metadata

            meta = parse_skill_metadata(text, str(skill_md), fallback_dir_name)
        except Exception:  # noqa: BLE001
            return fallback
        if meta and meta.get("name"):
            return str(meta["name"]).strip().lower()
        return fallback

    def _parse_skill_dir(
        self, skill_dir: Path, mtime: float, *, source: str = "user"
    ) -> SkillIndexEntry | None:
        """Parse SKILL.md frontmatter and build an index entry."""
        from soothe_deepagents.middleware.skills import parse_skill_metadata

        md_file = skill_dir / "SKILL.md"
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            return None

        try:
            meta = parse_skill_metadata(text, str(md_file), skill_dir.name)
        except Exception:
            logger.debug("parse_skill_metadata raised for %s", md_file, exc_info=True)
            return None
        if meta is None:
            return None

        paths = meta.get("paths")
        return SkillIndexEntry(
            name=meta["name"],
            description=meta["description"],
            tags=meta.get("tags") or "",
            source=source,
            path=str(skill_dir),
            mtime=mtime,
            paths=tuple(paths) if isinstance(paths, list) else None,
            when_to_use=meta.get("when_to_use") or None,
            core=meta.get("core"),
        )

    def _load_cache_python(self) -> None:
        """Load persisted index from disk if available (pure Python)."""
        import json

        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return

        if not isinstance(data, list):
            return

        for raw in data:
            try:
                raw.setdefault("paths", None)
                raw.setdefault("when_to_use", None)
                raw.setdefault("core", None)
                entry = SkillIndexEntry(**raw)
                self._entries[entry.name.lower()] = entry
            except (TypeError, KeyError):
                continue

    def _persist_python(self) -> None:
        """Write current index to disk cache (pure Python)."""
        import json
        from dataclasses import asdict

        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(e) for e in self._entries.values()]
            _CACHE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:
            logger.debug("Failed to persist skill index cache", exc_info=True)


def _rust_entry_to_py(entry: Any) -> SkillIndexEntry:
    """Convert a Rust ``SkillIndexEntry`` to the Python dataclass."""
    paths = entry.paths
    return SkillIndexEntry(
        name=entry.name,
        description=entry.description,
        tags=entry.tags,
        source=entry.source,
        path=entry.path,
        mtime=entry.mtime,
        paths=tuple(paths) if paths is not None else None,
        when_to_use=entry.when_to_use,
        core=entry.core,
    )


def _make_wire_entry(entry: SkillIndexEntry) -> dict[str, Any]:
    """Convert an index entry to the wire format expected by existing RPC consumers."""
    d: dict[str, Any] = {
        "name": entry.name,
        "description": entry.description,
        "source": entry.source,
    }
    if entry.tags:
        d["tags"] = entry.tags
    if entry.paths is not None:
        d["paths"] = list(entry.paths)
    if entry.when_to_use is not None:
        d["when_to_use"] = entry.when_to_use
    return d
