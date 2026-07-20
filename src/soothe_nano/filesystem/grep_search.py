"""Thin grep helpers over deepagents ``FilesystemBackend`` search.

Historically this module owned an ``ag``/``rg`` subprocess stack. Search now
lives in ``soothe_deepagents``; nano keeps only env aliases and a small
compatibility façade used by tests and adapters.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from soothe_deepagents.backends.filesystem import FilesystemBackend
from soothe_deepagents.backends.protocol import GrepMatch, GrepResult

_RG_ENV_VAR = "SOOTHE_RG_PATH"
GREP_UNAVAILABLE_ERROR = (
    "No ripgrep (`rg`) binary found. Install ripgrep or set SOOTHE_RG_PATH. "
    "Python fallback search is always available via FilesystemBackend.grep."
)


@lru_cache(maxsize=1)
def get_rg_bin() -> str | None:
    """Resolve ripgrep binary path (``SOOTHE_RG_PATH`` or ``PATH``)."""
    override = os.environ.get(_RG_ENV_VAR, "").strip()
    if override:
        return override if Path(override).is_file() or shutil.which(override) else None
    return shutil.which("rg")


def get_ag_bin() -> str | None:
    """Legacy alias — silver searcher is no longer used; always ``None``."""
    return None


def reset_grep_backend_cache() -> None:
    """Clear cached ripgrep resolution (tests)."""
    get_rg_bin.cache_clear()


def is_grep_available() -> bool:
    """Return True when ripgrep is resolvable (fast path for adapters).

    Deepagents always has a Python search fallback; this flag only reflects
    whether the preferred ``rg`` binary is present.
    """
    return get_rg_bin() is not None


def run_grep(
    pattern: str,
    *,
    path: str | Path,
    output_mode: str = "content",
    glob: str | None = None,
    timeout_s: float = 30.0,  # noqa: ARG001 — kept for call-site compatibility
) -> GrepResult | list[str] | str | None:
    """Search via ``FilesystemBackend.grep`` (ripgrep + Python fallback).

    Args:
        pattern: Literal text pattern.
        path: File or directory to search.
        output_mode: ``content``, ``files_with_matches``, or ``count``.
        glob: Optional filename glob filter.
        timeout_s: Unused; retained for API compatibility.

    Returns:
        Shape depends on ``output_mode`` (same contract as ``LocalFilesystem.grep``),
        or ``None`` when the backend returns an error with no matches.
    """
    target = Path(path).expanduser().resolve()
    if target.is_file():
        root = target.parent
        search_path = target.name
        backend = FilesystemBackend(root_dir=root, virtual_mode=True)
        result = backend.grep(pattern, path=search_path, glob=glob)
    else:
        backend = FilesystemBackend(root_dir=target, virtual_mode=True)
        result = backend.grep(pattern, path=".", glob=glob)

    if result.error and not result.matches:
        return None

    matches: list[GrepMatch] = list(result.matches or [])

    if output_mode == "files_with_matches":
        seen: list[str] = []
        for match in matches:
            p = match.get("path", "") if isinstance(match, dict) else ""
            if p and p not in seen:
                seen.append(p)
        return seen

    if output_mode == "count":
        counts: dict[str, int] = {}
        for match in matches:
            p = match.get("path", "") if isinstance(match, dict) else ""
            if p:
                counts[p] = counts.get(p, 0) + 1
        return "\n".join(f"{p}:{n}" for p, n in sorted(counts.items()))

    # content
    return GrepResult(error=result.error, matches=matches)


def grep_result_as_dict(result: GrepResult) -> dict[str, Any]:
    """Serialize ``GrepResult`` for debugging / legacy callers."""
    return {
        "error": result.error,
        "matches": list(result.matches or []),
    }
