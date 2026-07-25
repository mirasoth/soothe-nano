"""Vector store backends diagnose checks."""

from __future__ import annotations

from typing import Any

from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)


def _uses_provider(config: Any | None, provider_type: str) -> bool:
    if config is None or not hasattr(config, "vector_stores"):
        return False
    return any(vs.provider_type == provider_type for vs in config.vector_stores)


def _check_pgvector(config: Any | None) -> CheckResult:
    """Check PGVector vector store if configured."""
    if config is None:
        return CheckResult(
            name="pgvector",
            status=CheckStatus.INFO,
            message="Skipped (no config loaded)",
        )

    if not _uses_provider(config, "pgvector"):
        return CheckResult(
            name="pgvector",
            status=CheckStatus.INFO,
            message="PGVector not configured",
        )

    try:
        from soothe_nano.backends.vector_store.pgvector import PGVectorStore  # noqa: F401

        return CheckResult(
            name="pgvector",
            status=CheckStatus.OK,
            message="PGVector backend ready",
            details={"note": "Connection depends on PostgreSQL (see persistence checks)"},
        )
    except ImportError as e:
        return CheckResult(
            name="pgvector",
            status=CheckStatus.ERROR,
            message=f"PGVector import failed: {e}",
            details={"remediation": "Install pgvector package"},
        )


def _check_weaviate(config: Any | None) -> CheckResult:
    """Check Weaviate vector store if configured."""
    if config is None:
        return CheckResult(
            name="weaviate",
            status=CheckStatus.INFO,
            message="Skipped (no config loaded)",
        )

    if not _uses_provider(config, "weaviate"):
        return CheckResult(
            name="weaviate",
            status=CheckStatus.INFO,
            message="Weaviate not configured",
        )

    try:
        from soothe_nano.backends.vector_store.weaviate import WeaviateVectorStore  # noqa: F401

        return CheckResult(
            name="weaviate",
            status=CheckStatus.OK,
            message="Weaviate backend ready",
            details={"note": "Connection requires running Weaviate instance"},
        )
    except ImportError as e:
        return CheckResult(
            name="weaviate",
            status=CheckStatus.ERROR,
            message=f"Weaviate import failed: {e}",
            details={"remediation": "Install weaviate-client package"},
        )


def _check_sqlite_vec(config: Any | None) -> CheckResult:
    """Check sqlite_vec vector store if configured."""
    if config is None:
        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.INFO,
            message="Skipped (no config loaded)",
        )

    if not _uses_provider(config, "sqlite_vec"):
        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.INFO,
            message="sqlite_vec not configured",
        )

    try:
        from soothe_nano.backends.vector_store.sqlite_vec import SQLiteVecStore  # noqa: F401

        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.OK,
            message="sqlite_vec backend ready",
        )
    except ImportError as e:
        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.ERROR,
            message=f"sqlite_vec import failed: {e}",
            details={"remediation": "Install sqlite-vec package"},
        )


async def check_vector_stores(config: Any | None = None) -> CategoryResult:
    """Check vector store backends."""
    checks = [
        _check_pgvector(config),
        _check_weaviate(config),
        _check_sqlite_vec(config),
    ]
    return CategoryResult(
        category="vector_stores",
        status=aggregate_status([check.status for check in checks]),
        checks=checks,
    )
