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

_RG_ENV_VAR = "SOOTHE_RG_PATH"


@lru_cache(maxsize=1)
def get_rg_bin() -> str | None:
    """Resolve ripgrep binary path (``SOOTHE_RG_PATH`` or ``PATH``)."""
    override = os.environ.get(_RG_ENV_VAR, "").strip()
    if override:
        return override if Path(override).is_file() or shutil.which(override) else None
    return shutil.which("rg")


def reset_grep_backend_cache() -> None:
    """Clear cached ripgrep resolution (tests)."""
    get_rg_bin.cache_clear()


def is_grep_available() -> bool:
    """Return True when ripgrep is resolvable (fast path for adapters).

    Deepagents always has a Python search fallback; this flag only reflects
    whether the preferred ``rg`` binary is present.
    """
    return get_rg_bin() is not None
