"""Resolved paths for CoreAgent runtime SQLite stores under ``SOOTHE_DATA_DIR``."""

from __future__ import annotations

from pathlib import Path


def resolve_metadata_db_path() -> Path:
    """Return the ThreadInfo metadata database path."""
    from soothe_sdk.paths import SOOTHE_DATA_DIR

    return Path(SOOTHE_DATA_DIR) / "metadata.db"


__all__ = [
    "resolve_metadata_db_path",
]
