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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soothe_nano._rust_compat import get_rust_module
from soothe_nano.skills.builtins import iter_skill_roots

_CACHE_FILE = Path.home() / ".soothe" / "cache" / "skill_index.json"

# Package-bundled built-in skills directory (kept for tests / introspection)
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent / "builtin"

_rust = get_rust_module()
_RustSkillIndex = _rust.SkillIndex


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

        rust_index = _RustSkillIndex()
        if self._loaded:
            rust_index.load_cache(cache_path)
        rust_entries = rust_index.rebuild_if_stale(roots, cache_path)
        self._entries = {e.name.lower(): _rust_entry_to_py(e) for e in rust_entries}
        self._loaded = True
        return self.entries()

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
        rust_index = _RustSkillIndex()
        rust_index.load_cache(str(_CACHE_FILE))
        for entry in rust_index.entries():
            py_entry = _rust_entry_to_py(entry)
            self._entries[py_entry.name.lower()] = py_entry
        self._loaded = True


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
