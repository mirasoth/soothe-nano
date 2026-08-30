"""SQLite-backed key-value store implementing the `AsyncPersistStore` protocol.

Uses the process-scoped `SqliteStoreRuntime` for serialized writes and pooled reads.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from soothe_sdk.paths import resolve_persist_db_path

logger = logging.getLogger(__name__)


class SQLitePersistStore:
    """SQLite key-value store with namespace isolation.

    Delegates connection management to `SqliteStoreRuntime` (one writer +
    pooled readers per database file). Provides the same namespace isolation
    semantics as `PostgreSQLPersistStore`.

    Example:
        >>> store = SQLitePersistStore(namespace="durability")
        >>> await store.save("thread:abc", {"status": "active"})
    """

    def __init__(
        self,
        db_path: str | None = None,
        namespace: str = "default",
        reader_pool_size: int = 5,
    ) -> None:
        """Initialize SQLite persist store.

        Args:
            db_path: Path to SQLite database file. Defaults to
                `$SOOTHE_DATA_DIR/databases/persist.db`.
            namespace: Namespace for key isolation.
            reader_pool_size: Reader pool size for the Runtime.
        """
        from soothe_nano.config.models import SqliteRuntimeConfig
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        self._namespace = namespace
        self._db_path = db_path or str(resolve_persist_db_path())
        self._runtime = SqliteRuntimeRegistry.acquire(
            self._db_path,
            SqliteRuntimeConfig(reader_pool_size=reader_pool_size),
        )
        self._runtime.run_write_sync(self._create_table_sync)
        logger.info(
            "SQLite persist store initialized: path=%s namespace=%s pool_size=%d",
            self._db_path,
            namespace,
            reader_pool_size,
        )

    def _create_table_sync(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS soothe_kv (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_soothe_kv_namespace ON soothe_kv(namespace)")

    async def save(self, key: str, data: Any) -> None:
        """Persist data under the given key (upsert).

        Args:
            key: Storage key.
            data: JSON-serializable data.
        """
        serialized = json.dumps(data, ensure_ascii=False)
        namespace = self._namespace
        await self._runtime.run_write(
            lambda conn: self._save_sync(conn, namespace, key, serialized)
        )

    def _save_sync(
        self, conn: sqlite3.Connection, namespace: str, key: str, serialized: str
    ) -> None:
        conn.execute(
            """
            INSERT INTO soothe_kv (namespace, key, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(namespace, key) DO UPDATE
                SET data = excluded.data, updated_at = CURRENT_TIMESTAMP
            """,
            (namespace, key, serialized),
        )

    async def load(self, key: str) -> Any | None:
        """Load data for the given key.

        Args:
            key: Storage key.

        Returns:
            The stored data, or None if not found.
        """
        namespace = self._namespace

        def _read(conn: sqlite3.Connection) -> str | None:
            return self._load_sync(conn, namespace, key)

        row_data = await self._runtime.run_read(_read)
        if row_data is None:
            return None
        return json.loads(row_data)

    def _load_sync(self, conn: sqlite3.Connection, namespace: str, key: str) -> str | None:
        row = conn.execute(
            "SELECT data FROM soothe_kv WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        if row is None:
            return None
        return row["data"]

    async def delete(self, key: str) -> None:
        """Delete data for the given key.

        Args:
            key: Storage key.
        """
        namespace = self._namespace
        await self._runtime.run_write(lambda conn: self._delete_sync(conn, namespace, key))

    def _delete_sync(self, conn: sqlite3.Connection, namespace: str, key: str) -> None:
        conn.execute(
            "DELETE FROM soothe_kv WHERE namespace = ? AND key = ?",
            (namespace, key),
        )

    async def list_keys(self, namespace: str | None = None) -> list[str]:
        """List all keys in the given namespace.

        Args:
            namespace: Optional namespace. If None, uses the store's default namespace.

        Returns:
            Keys in the namespace.
        """
        ns = namespace or self._namespace

        def _read(conn: sqlite3.Connection) -> list[str]:
            return self._list_keys_sync(conn, ns)

        return await self._runtime.run_read(_read)

    def _list_keys_sync(self, conn: sqlite3.Connection, namespace: str) -> list[str]:
        rows = conn.execute(
            "SELECT key FROM soothe_kv WHERE namespace = ?", (namespace,)
        ).fetchall()
        return [row["key"] for row in rows]

    async def close(self) -> None:
        """Release the process Runtime reference for this database file."""
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        await SqliteRuntimeRegistry.release(self._db_path)
        logger.info("SQLite persist store closed")
