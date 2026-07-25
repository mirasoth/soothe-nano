"""Protocol backend import diagnose checks."""

from __future__ import annotations

from typing import Any

from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)


def _check_import(module_path: str, name: str) -> CheckResult:
    """Check if a module can be imported."""
    try:
        __import__(module_path)
        return CheckResult(
            name=name,
            status=CheckStatus.OK,
            message=f"{name} import successful",
        )
    except ImportError as e:
        return CheckResult(
            name=name,
            status=CheckStatus.ERROR,
            message=f"{name} import failed: {e}",
            details={"module": module_path, "remediation": f"Install required package for {name}"},
        )


async def check_protocols(config: Any | None = None) -> CategoryResult:  # noqa: ARG001
    """Check protocol backends (import-only)."""
    checks = [
        _check_import("soothe_nano.backends.memory.memu_adapter", "MemU Memory"),
        _check_import("soothe_nano.backends.durability.postgresql", "PostgreSQL Durability"),
        _check_import("soothe_nano.backends.durability.sqlite", "SQLite Durability"),
        _check_import("soothe_nano.backends.vector_store.pgvector", "PGVector"),
        _check_import("soothe_nano.backends.vector_store.weaviate", "Weaviate"),
        _check_import("soothe_nano.backends.vector_store.sqlite_vec", "sqlite_vec"),
    ]
    return CategoryResult(
        category="protocols",
        status=aggregate_status([check.status for check in checks]),
        checks=checks,
    )
