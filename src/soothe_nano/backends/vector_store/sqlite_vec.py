"""SQLite vector store using the sqlite-vec extension.

Uses the process-scoped `SqliteStoreRuntime` for connection management.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import struct
import uuid
from typing import Any

from soothe_sdk.paths import resolve_vectors_db_path
from soothe_sdk.protocols.vector_store import VectorRecord

logger = logging.getLogger(__name__)


def _pack_vector(vector: list[float]) -> bytes:
    """Pack a list of floats into F32 binary format for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _l2_distance(a: list[float], b: list[float]) -> float:
    """Compute L2 (Euclidean) distance between two vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=False)))


def _ip_similarity(a: list[float], b: list[float]) -> float:
    """Compute inner product (dot product) similarity."""
    return sum(x * y for x, y in zip(a, b, strict=False))


class SQLiteVecStore:
    """`VectorStoreProtocol` backed by SQLite with the sqlite-vec extension.

    Uses sqlite-vec virtual tables for vector similarity search, falling back
    to Python-side brute-force similarity when the extension is unavailable.

    Example:
        >>> store = SQLiteVecStore(collection="docs")
        >>> await store.insert([vec], payloads=[{"text": "hi"}])

    Args:
        collection: Collection name (becomes table name prefix).
        db_path: Path to SQLite database. Defaults to `$SOOTHE_DATA_DIR/databases/vectors.db`.
        vector_size: Dimension of vectors (default: 1536).
        distance: Distance metric (`cosine`, `l2`, `ip`).
        reader_pool_size: Number of reader connections for concurrent reads.
    """

    def __init__(
        self,
        collection: str = "soothe_vectors",
        db_path: str | None = None,
        vector_size: int = 1536,
        distance: str = "cosine",
        reader_pool_size: int = 8,
    ) -> None:
        """Initialize SQLiteVecStore."""
        from soothe_nano.config.models import SqliteRuntimeConfig
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        self._collection = collection
        self._db_path = db_path or str(resolve_vectors_db_path())
        self._vector_size = vector_size
        self._distance = distance
        self._has_vec_ext = False
        self._has_vec0 = False

        self._runtime = SqliteRuntimeRegistry.acquire(
            self._db_path,
            SqliteRuntimeConfig(reader_pool_size=reader_pool_size),
            configure_connection=self._configure_vec_connection,
        )
        self._runtime.run_write_sync(self._create_table_sync)
        logger.info(
            "SQLite vector store initialized path=%s collection=%s has_vec_ext=%s",
            self._db_path,
            self._collection,
            self._has_vec_ext,
        )

    def _configure_vec_connection(self, conn: sqlite3.Connection) -> None:
        """Load sqlite-vec extension on each Runtime connection."""
        self._load_vec_extension(conn)

    def _load_vec_extension(self, conn: sqlite3.Connection) -> None:
        """Load sqlite-vec extension on a connection."""
        try:
            import sqlite_vec

            conn.enable_load_extension(True)
            conn.load_extension(sqlite_vec.loadable_path())
            conn.enable_load_extension(False)
            self._has_vec_ext = True
            self._has_vec0 = False
            logger.debug("sqlite-vec extension loaded successfully (SQL functions available)")
        except ImportError:
            logger.warning(
                "sqlite-vec not installed. Install with: pip install sqlite-vec. "
                "Falling back to Python-side similarity (non-persistent vector storage)."
            )
            self._has_vec_ext = False
        except Exception as e:
            logger.warning("Failed to load sqlite-vec extension: %s", e)
            self._has_vec_ext = False

    def _table_name(self) -> str:
        """Get the table name for this collection."""
        return f"vec_{self._collection}"

    def _create_table_sql(self) -> str:
        """Generate table creation SQL."""
        table = self._table_name()
        return f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                vector_size INTEGER NOT NULL,
                payload TEXT DEFAULT '{{}}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """

    def _create_table_sync(self, conn: sqlite3.Connection) -> None:
        conn.execute(self._create_table_sql())

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None:
        """Create or ensure the collection table exists.

        Args:
            vector_size: Dimension of vectors.
            distance: Distance metric (`cosine`, `l2`, `ip`).
        """
        self._vector_size = vector_size
        self._distance = distance
        await self._runtime.run_write(lambda conn: conn.execute(self._create_table_sql()))

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors with optional payloads and IDs.

        Args:
            vectors: Embedding vectors to insert.
            payloads: Optional metadata per vector. Defaults to empty dicts.
            ids: Optional IDs. If None, UUIDs are generated.
        """
        payloads = payloads or [{}] * len(vectors)
        ids = ids or [str(uuid.uuid4()) for _ in vectors]
        table = self._table_name()
        rows = [
            (vid, _pack_vector(vec), len(vec), json.dumps(payload))
            for vid, vec, payload in zip(ids, vectors, payloads, strict=False)
        ]

        def _insert(conn: sqlite3.Connection) -> None:
            conn.executemany(
                f"INSERT OR REPLACE INTO {table} (id, embedding, vector_size, payload) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )

        await self._runtime.run_write(_insert)

    async def search(
        self,
        query: str,  # noqa: ARG002
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours by vector similarity.

        Args:
            query: Unused text query (reserved for future hybrid search).
            vector: Query embedding vector.
            limit: Maximum number of results.
            filters: Optional payload equality filters (all must match).

        Returns:
            Matching records ordered by similarity.
        """
        table = self._table_name()
        packed = _pack_vector(vector)

        def _search(conn: sqlite3.Connection) -> list[VectorRecord]:
            try:
                rows = conn.execute(
                    f"""
                    SELECT id, payload, vec_distance_cosine(embedding, ?) as dist
                    FROM {table}
                    ORDER BY dist ASC
                    LIMIT ?
                    """,
                    (packed, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return self._brute_force_search(conn, table, vector, limit, filters)

            results = []
            for row in rows:
                payload = json.loads(row["payload"]) if row["payload"] else {}
                if filters and not self._match_filters(payload, filters):
                    continue
                score = 1.0 - row["dist"]
                results.append(VectorRecord(id=row["id"], payload=payload, score=score))
            return results

        return await self._runtime.run_read(_search)

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID.

        Args:
            record_id: The record's unique ID.
        """
        table = self._table_name()

        def _delete(conn: sqlite3.Connection) -> None:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))

        await self._runtime.run_write(_delete)

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update a record's vector and/or payload.

        Args:
            record_id: The record's unique ID.
            vector: New embedding vector (None to leave unchanged).
            payload: New payload (None to leave unchanged).
        """
        if vector is not None:
            payloads = [payload] if payload is not None else [{}]
            await self.insert([vector], payloads, [record_id])
        elif payload is not None:
            table = self._table_name()
            payload_json = json.dumps(payload)

            def _update(conn: sqlite3.Connection) -> None:
                conn.execute(
                    f"UPDATE {table} SET payload = ? WHERE id = ?",
                    (payload_json, record_id),
                )

            await self._runtime.run_write(_update)

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record by ID.

        Args:
            record_id: The record's unique ID.

        Returns:
            The record, or None if not found.
        """
        table = self._table_name()

        def _get(conn: sqlite3.Connection) -> VectorRecord | None:
            row = conn.execute(
                f"SELECT id, embedding, payload FROM {table} WHERE id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload"]) if row["payload"] else {}
            return VectorRecord(id=row["id"], payload=payload)

        return await self._runtime.run_read(_get)

    async def list_records(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List records matching optional filters.

        Args:
            filters: Optional payload equality filters (all must match).
            limit: Maximum number of records to return.

        Returns:
            Matching records.
        """
        table = self._table_name()
        limit_clause = f" LIMIT {limit}" if limit else ""

        def _list(conn: sqlite3.Connection) -> list[VectorRecord]:
            try:
                rows = conn.execute(
                    f"SELECT id, payload FROM {table}{limit_clause}",
                ).fetchall()
            except sqlite3.OperationalError:
                return []

            results = []
            for row in rows:
                payload = json.loads(row["payload"]) if row["payload"] else {}
                if filters and not self._match_filters(payload, filters):
                    continue
                results.append(VectorRecord(id=row["id"], payload=payload))
            return results

        return await self._runtime.run_read(_list)

    async def delete_collection(self) -> None:
        """Drop the collection table and all its data."""
        table = self._table_name()

        def _drop(conn: sqlite3.Connection) -> None:
            conn.execute(f"DROP TABLE IF EXISTS {table}")

        await self._runtime.run_write(_drop)

    async def reset(self) -> None:
        """Clear all records from the collection without dropping the table."""
        table = self._table_name()

        def _reset(conn: sqlite3.Connection) -> None:
            conn.execute(f"DELETE FROM {table}")

        await self._runtime.run_write(_reset)

    async def close(self) -> None:
        """Release the process Runtime reference for this database file."""
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        await SqliteRuntimeRegistry.release(self._db_path)
        logger.info("SQLite vector store closed (collection=%s)", self._collection)

    def _brute_force_search(
        self,
        conn: sqlite3.Connection,
        table: str,
        vector: list[float],
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[VectorRecord]:
        """Brute-force vector search with Python-side similarity computation.

        Used when sqlite-vec virtual tables are unavailable. Scans up to 1000 rows
        and scores them with the configured distance metric.
        """
        rows = conn.execute(
            f"SELECT id, embedding, vector_size, payload FROM {table} LIMIT 1000",
        ).fetchall()

        sim_func = {
            "cosine": _cosine_similarity,
            "l2": lambda a, b: -_l2_distance(a, b),
            "ip": _ip_similarity,
        }.get(self._distance, _cosine_similarity)

        results = []
        for row in rows:
            vec_size = row["vector_size"]
            emb = list(struct.unpack(f"{vec_size}f", row["embedding"]))
            score = sim_func(vector, emb)
            payload = json.loads(row["payload"]) if row["payload"] else {}
            if filters and not self._match_filters(payload, filters):
                continue
            results.append(VectorRecord(id=row["id"], payload=payload, score=score))

        reverse = self._distance != "l2"
        results.sort(key=lambda r: r.score or 0, reverse=reverse)
        return results[:limit]

    @staticmethod
    def _match_filters(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Return whether *payload* satisfies all filter equality conditions."""
        return all(payload.get(key) == value for key, value in filters.items())
