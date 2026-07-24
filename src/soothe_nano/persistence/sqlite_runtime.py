"""Process-scoped SQLite store runtime.

One Runtime per database file: serialized writes with BEGIN IMMEDIATE,
leased reader connections, uniform WAL / busy_timeout pragmas.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from soothe_nano.config.models import SqliteRuntimeConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _apply_connection_pragmas(conn: sqlite3.Connection, *, busy_timeout_ms: int) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")


def _is_memory_db_path(db_path: Path | str) -> bool:
    raw = str(db_path)
    return raw == ":memory:" or Path(raw).name == ":memory:"


class SqliteStoreRuntime:
    """Owns connections for one SQLite database file.

    Args:
        db_path: Absolute or resolvable path to the ``.db`` file, or ``:memory:``.
        config: Optional pool / timeout settings.
        configure_connection: Optional hook run after pragmas (e.g. load extensions).
    """

    def __init__(
        self,
        db_path: Path | str,
        config: SqliteRuntimeConfig | None = None,
        *,
        configure_connection: Callable[[sqlite3.Connection], None] | None = None,
    ) -> None:
        import uuid

        self._is_memory = _is_memory_db_path(db_path)
        if self._is_memory:
            # Unique shared-cache memory DB so writer + readers see the same data,
            # and distinct Runtime instances do not leak state across tests.
            self.db_path = Path(":memory:")
            self._connect_target = f"file:soothe_rt_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._connect_uri = True
        else:
            self.db_path = Path(db_path).expanduser().resolve()
            self._connect_target = str(self.db_path)
            self._connect_uri = False
        self._config = config or SqliteRuntimeConfig()
        self._configure_connection = configure_connection
        self._writer_conn: sqlite3.Connection | None = None
        self._reader_pool: list[sqlite3.Connection] = []
        self._writer_lock = threading.Lock()
        self._pool_lock = threading.Lock()
        self._reader_semaphore = threading.Semaphore(self._config.reader_pool_size)
        self._closed = False
        self._init_lock = threading.Lock()

    def _ensure_not_closed(self) -> None:
        if self._closed:
            msg = f"SqliteStoreRuntime is closed: {self.db_path}"
            raise RuntimeError(msg)

    def _open_connection(self) -> sqlite3.Connection:
        if not self._is_memory:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self._connect_target,
            uri=self._connect_uri,
            check_same_thread=False,
            timeout=max(1.0, self._config.busy_timeout_ms / 1000.0),
        )
        # Autocommit mode: Runtime issues BEGIN IMMEDIATE for writes.
        conn.isolation_level = None
        _apply_connection_pragmas(conn, busy_timeout_ms=self._config.busy_timeout_ms)
        conn.row_factory = sqlite3.Row
        if self._configure_connection is not None:
            self._configure_connection(conn)
        return conn

    def _ensure_writer(self) -> sqlite3.Connection:
        self._ensure_not_closed()
        if self._writer_conn is not None:
            return self._writer_conn
        with self._init_lock:
            if self._writer_conn is None:
                self._writer_conn = self._open_connection()
                logger.info("SqliteStoreRuntime writer opened path=%s", self.db_path)
            return self._writer_conn

    def _ensure_reader_pool(self) -> None:
        self._ensure_not_closed()
        with self._pool_lock:
            if self._reader_pool:
                return
            for _ in range(self._config.reader_pool_size):
                self._reader_pool.append(self._open_connection())
            logger.info(
                "SqliteStoreRuntime reader pool ready path=%s size=%d",
                self.db_path,
                self._config.reader_pool_size,
            )

    def _acquire_reader(self) -> sqlite3.Connection:
        self._ensure_reader_pool()
        self._reader_semaphore.acquire()
        try:
            with self._pool_lock:
                if self._reader_pool:
                    return self._reader_pool.pop()
            return self._open_connection()
        except Exception:
            self._reader_semaphore.release()
            raise

    def _release_reader(self, conn: sqlite3.Connection) -> None:
        try:
            with self._pool_lock:
                if not self._closed and len(self._reader_pool) < self._config.reader_pool_size:
                    self._reader_pool.append(conn)
                    return
            conn.close()
        finally:
            self._reader_semaphore.release()

    def run_write_sync(self, sync_fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``sync_fn`` under an exclusive IMMEDIATE write transaction."""
        with self._writer_lock:
            conn = self._ensure_writer()
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = sync_fn(conn)
                conn.commit()
                return result
            except Exception:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise

    def run_read_sync(self, sync_fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``sync_fn`` on a leased reader connection."""
        conn = self._acquire_reader()
        try:
            return sync_fn(conn)
        finally:
            self._release_reader(conn)

    async def run_write(self, sync_fn: Callable[[sqlite3.Connection], T]) -> T:
        """Async wrapper around ``run_write_sync``."""
        return await asyncio.to_thread(self.run_write_sync, sync_fn)

    async def run_read(self, sync_fn: Callable[[sqlite3.Connection], T]) -> T:
        """Async wrapper around ``run_read_sync``."""
        return await asyncio.to_thread(self.run_read_sync, sync_fn)

    def close_sync(self) -> None:
        """Close connections; optionally truncate WAL."""
        with self._writer_lock:
            with self._pool_lock:
                self._closed = True
                if (
                    self._config.wal_checkpoint_on_shutdown
                    and self._writer_conn is not None
                    and self.db_path.is_file()
                ):
                    try:
                        self._writer_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    except sqlite3.Error:
                        logger.warning("WAL checkpoint failed path=%s", self.db_path, exc_info=True)
                for conn in self._reader_pool:
                    try:
                        conn.close()
                    except sqlite3.Error:
                        pass
                self._reader_pool.clear()
                if self._writer_conn is not None:
                    try:
                        self._writer_conn.close()
                    except sqlite3.Error:
                        pass
                    self._writer_conn = None
                logger.info("SqliteStoreRuntime closed path=%s", self.db_path)

    async def close(self) -> None:
        """Async close."""
        await asyncio.to_thread(self.close_sync)


class SqliteRuntimeRegistry:
    """Process-wide path → ``SqliteStoreRuntime`` registry with refcounts."""

    _lock = threading.Lock()
    _runtimes: dict[str, SqliteStoreRuntime] = {}
    _refcounts: dict[str, int] = {}
    _default_config: SqliteRuntimeConfig | None = None

    @classmethod
    def set_default_config(cls, config: SqliteRuntimeConfig | None) -> None:
        """Set process default Runtime config (daemon startup)."""
        with cls._lock:
            cls._default_config = config

    @classmethod
    def acquire(
        cls,
        db_path: Path | str,
        config: SqliteRuntimeConfig | None = None,
        *,
        configure_connection: Callable[[sqlite3.Connection], None] | None = None,
    ) -> SqliteStoreRuntime:
        """Return Runtime for ``db_path``, incrementing the refcount.

        ``:memory:`` always returns a fresh unshared Runtime (not registered).
        ``configure_connection`` is applied only when creating a new Runtime
        (e.g. loading sqlite-vec on vector store connections).
        """
        if _is_memory_db_path(db_path):
            cfg = config or cls._default_config or SqliteRuntimeConfig()
            return SqliteStoreRuntime(
                ":memory:",
                cfg,
                configure_connection=configure_connection,
            )

        path = str(Path(db_path).expanduser().resolve())
        with cls._lock:
            runtime = cls._runtimes.get(path)
            if runtime is None:
                cfg = config or cls._default_config or SqliteRuntimeConfig()
                runtime = SqliteStoreRuntime(
                    path,
                    cfg,
                    configure_connection=configure_connection,
                )
                cls._runtimes[path] = runtime
                cls._refcounts[path] = 0
            cls._refcounts[path] += 1
            return runtime

    @classmethod
    def release_sync(cls, db_path: Path | str) -> None:
        """Decrement refcount; close Runtime when it hits zero."""
        path = str(Path(db_path).expanduser().resolve())
        to_close: SqliteStoreRuntime | None = None
        with cls._lock:
            if path not in cls._refcounts:
                return
            cls._refcounts[path] -= 1
            if cls._refcounts[path] <= 0:
                cls._refcounts.pop(path, None)
                to_close = cls._runtimes.pop(path, None)
        if to_close is not None:
            to_close.close_sync()

    @classmethod
    async def release(cls, db_path: Path | str) -> None:
        await asyncio.to_thread(cls.release_sync, db_path)

    @classmethod
    def close_all_sync(cls) -> None:
        """Force-close every Runtime (daemon shutdown)."""
        with cls._lock:
            runtimes = list(cls._runtimes.values())
            cls._runtimes.clear()
            cls._refcounts.clear()
        for runtime in runtimes:
            runtime.close_sync()

    @classmethod
    async def close_all(cls) -> None:
        await asyncio.to_thread(cls.close_all_sync)


__all__ = [
    "SqliteRuntimeConfig",
    "SqliteRuntimeRegistry",
    "SqliteStoreRuntime",
]
