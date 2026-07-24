"""Unit tests for SqliteStoreRuntime / Registry (IG-647 / RFC-801)."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from soothe_nano.config.models import SqliteRuntimeConfig
from soothe_nano.persistence.sqlite_runtime import (
    SqliteRuntimeRegistry,
    SqliteStoreRuntime,
)


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    SqliteRuntimeRegistry.close_all_sync()
    SqliteRuntimeRegistry.set_default_config(None)
    yield
    SqliteRuntimeRegistry.close_all_sync()
    SqliteRuntimeRegistry.set_default_config(None)


def test_run_write_creates_table_and_commits(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    runtime = SqliteStoreRuntime(db, SqliteRuntimeConfig(reader_pool_size=2))

    def _init(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ("a", "1"))

    runtime.run_write_sync(_init)

    def _load(conn: sqlite3.Connection) -> str | None:
        row = conn.execute("SELECT v FROM kv WHERE k = ?", ("a",)).fetchone()
        return row[0] if row else None

    assert runtime.run_read_sync(_load) == "1"
    runtime.close_sync()


def test_write_rollback_on_error(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    runtime = SqliteStoreRuntime(db)

    def _init(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")

    runtime.run_write_sync(_init)

    def _fail(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ("a", "1"))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        runtime.run_write_sync(_fail)

    def _count(conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0])

    assert runtime.run_read_sync(_count) == 0
    runtime.close_sync()


def test_reader_leases_are_distinct_under_concurrency(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    runtime = SqliteStoreRuntime(db, SqliteRuntimeConfig(reader_pool_size=4))
    runtime.run_write_sync(
        lambda c: c.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY)")
    )

    barrier = threading.Barrier(4)

    def _hold(conn: sqlite3.Connection) -> int:
        barrier.wait(timeout=5)
        return id(conn)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(runtime.run_read_sync, _hold) for _ in range(4)]
        ids = [f.result(timeout=10) for f in as_completed(futures)]

    assert len(set(ids)) == 4
    runtime.close_sync()


def test_busy_timeout_and_wal_pragmas(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    runtime = SqliteStoreRuntime(db, SqliteRuntimeConfig(busy_timeout_ms=12_345))

    def _check(conn: sqlite3.Connection) -> tuple[str, int]:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        return str(mode).lower(), int(timeout)

    mode, timeout = runtime.run_read_sync(_check)
    assert mode == "wal"
    assert timeout == 12_345
    runtime.close_sync()


def test_registry_refcount_closes_once(tmp_path: Path) -> None:
    db = tmp_path / "shared.db"
    a = SqliteRuntimeRegistry.acquire(db)
    b = SqliteRuntimeRegistry.acquire(db)
    assert a is b

    SqliteRuntimeRegistry.release_sync(db)
    a.run_write_sync(lambda c: c.execute("CREATE TABLE IF NOT EXISTS x (i INTEGER)"))

    SqliteRuntimeRegistry.release_sync(db)
    with pytest.raises(RuntimeError, match="closed"):
        a.run_write_sync(lambda c: None)


@pytest.mark.asyncio
async def test_async_run_write_read(tmp_path: Path) -> None:
    db = tmp_path / "async.db"
    runtime = SqliteStoreRuntime(db)

    await runtime.run_write(
        lambda c: c.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    )
    await runtime.run_write(lambda c: c.execute("INSERT INTO kv VALUES (?, ?)", ("k", "v")))

    value = await runtime.run_read(
        lambda c: c.execute("SELECT v FROM kv WHERE k = ?", ("k",)).fetchone()[0]
    )
    assert value == "v"
    await runtime.close()
