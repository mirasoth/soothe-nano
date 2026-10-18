"""Auto-provision PostgreSQL databases for multi-database layout.

Creates missing logical databases on first connect, then applies each database's
``sql/<database>/init.sql`` bootstrap script. Collection-specific vector tables and
LangGraph checkpoint tables are still created by their owning backends at runtime.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_VALID_DB_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresProvisioning:
    """Process-cached PostgreSQL database auto-provisioning."""

    _provisioned_cache_keys: set[str] = set()
    _provision_lock = threading.Lock()

    @staticmethod
    def validate_database_name(name: str) -> None:
        """Validate a PostgreSQL database identifier from config.

        Args:
            name: Database name to validate.

        Raises:
            ValueError: If the name is empty or contains unsafe characters.
        """
        if not name or not _VALID_DB_NAME.match(name):
            msg = f"Invalid PostgreSQL database name: {name!r}"
            raise ValueError(msg)

    @staticmethod
    def admin_dsn(base_dsn: str) -> str:
        """Return a DSN connected to the maintenance ``postgres`` database.

        Args:
            base_dsn: Base DSN without database segment.

        Returns:
            DSN targeting the ``postgres`` maintenance database.
        """
        parts = urlsplit(base_dsn.rstrip("/"))
        return urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))

    @classmethod
    def target_dsn(cls, base_dsn: str, database_name: str) -> str:
        """Build a DSN for a named database under ``base_dsn``."""
        cls.validate_database_name(database_name)
        parts = urlsplit(base_dsn.rstrip("/"))
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                f"/{database_name}",
                parts.query,
                parts.fragment,
            )
        )

    @staticmethod
    def uses_postgresql(config: SootheConfig) -> bool:
        """Return whether any configured component expects PostgreSQL."""
        if config.persistence.default_backend == "postgresql":
            return True
        if config.resolve_checkpointer_backend() == "postgresql":
            return True
        if config.resolve_durability_backend() == "postgresql":
            return True
        return any(vs.provider_type == "pgvector" for vs in config.vector_stores)

    @classmethod
    def required_database_keys(cls, config: SootheConfig) -> frozenset[str]:
        """Return configured database component keys that should exist.

        When ``postgres_base_dsn`` is set and PostgreSQL is in use, all entries in
        ``postgres_databases`` are provisioned (checkpoints, metadata, vectors, memory).
        """
        if not config.persistence.postgres_base_dsn:
            return frozenset()
        if not cls.uses_postgresql(config):
            return frozenset()
        return frozenset(config.persistence.postgres_databases.keys())

    @staticmethod
    def _cache_key(config: SootheConfig) -> str:
        base = config.persistence.postgres_base_dsn or ""
        db_items = tuple(sorted(config.persistence.postgres_databases.items()))
        return f"{base}|{db_items}"

    @classmethod
    def ensure_databases(cls, config: SootheConfig) -> list[str]:
        """Create missing PostgreSQL databases declared in config.

        Idempotent: existing databases are left unchanged. Returns the logical
        database names created during this call.

        Args:
            config: Active Soothe configuration.

        Returns:
            Database names created in this invocation (empty if already provisioned).

        Raises:
            ImportError: psycopg is not installed.
            ValueError: Invalid database names in config.
            RuntimeError: Connection or privilege failure talking to PostgreSQL.
        """
        db_keys = cls.required_database_keys(config)
        if not db_keys:
            return []

        cache_key = cls._cache_key(config)
        with cls._provision_lock:
            if cache_key in cls._provisioned_cache_keys:
                return []
            created = cls._ensure_unlocked(config, db_keys)
            cls._provisioned_cache_keys.add(cache_key)
            return created

    @classmethod
    def _ensure_unlocked(
        cls,
        config: SootheConfig,
        db_keys: frozenset[str],
    ) -> list[str]:
        try:
            import psycopg
            from psycopg import sql
        except ImportError as exc:
            msg = "psycopg is required for PostgreSQL database provisioning"
            raise ImportError(msg) from exc

        from soothe_nano.config.env import _resolve_env

        base_dsn = _resolve_env(config.persistence.postgres_base_dsn or "")
        if not base_dsn:
            return []

        admin_dsn = cls.admin_dsn(base_dsn)
        created: list[str] = []

        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    for db_key in sorted(db_keys):
                        db_name = config.persistence.postgres_databases.get(db_key)
                        if not db_name:
                            continue
                        cls.validate_database_name(db_name)
                        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                        if cur.fetchone() is not None:
                            continue
                        logger.info("Creating PostgreSQL database %s (%s)", db_name, db_key)
                        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
                        created.append(db_name)
        except Exception as exc:
            msg = f"Failed to provision PostgreSQL databases via {admin_dsn}: {exc}"
            raise RuntimeError(msg) from exc

        cls._initialize_schemas(config, db_keys, base_dsn)

        if created:
            logger.info("Provisioned PostgreSQL databases: %s", ", ".join(created))
        else:
            logger.debug(
                "PostgreSQL databases already exist for keys: %s", ", ".join(sorted(db_keys))
            )

        return created

    @classmethod
    def _initialize_schemas(
        cls,
        config: SootheConfig,
        db_keys: frozenset[str],
        base_dsn: str,
    ) -> None:
        """Apply ``init.sql`` for each configured PostgreSQL database."""
        from soothe_nano.persistence.db_init import DatabaseInit

        for db_key in sorted(db_keys):
            db_name = config.persistence.postgres_databases.get(db_key)
            if not db_name:
                continue
            dsn = cls.target_dsn(base_dsn, db_name)
            try:
                DatabaseInit.initialize_sync(dsn, db_name)
            except Exception:
                logger.warning(
                    "Could not initialize PostgreSQL schema for %s; backends will retry on connect",
                    db_name,
                    exc_info=True,
                )

    @classmethod
    async def ensure_databases_async(cls, config: SootheConfig) -> list[str]:
        """Async wrapper around :meth:`ensure_databases`."""
        return await asyncio.to_thread(cls.ensure_databases, config)

    @classmethod
    def reset_cache_for_tests(cls) -> None:
        """Clear process-level provisioning cache (tests only)."""
        with cls._provision_lock:
            cls._provisioned_cache_keys.clear()


__all__ = ["PostgresProvisioning"]
