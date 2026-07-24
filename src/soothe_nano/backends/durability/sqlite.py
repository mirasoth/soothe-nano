"""DurabilityProtocol implementation using SQLite backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe_nano.backends.durability.base import BasePersistStoreDurability
from soothe_nano.backends.persistence.sqlite_store import SQLitePersistStore

if TYPE_CHECKING:
    from soothe_sdk.protocols.persistence import AsyncPersistStore


class SQLiteDurability(BasePersistStoreDurability):
    """Durability protocol implementation backed by SQLite.

    Wraps SQLitePersistStore via the BasePersistStoreDurability composition pattern.
    """

    def __init__(
        self,
        persist_store: AsyncPersistStore | None = None,
        db_path: str | None = None,
    ) -> None:
        """Initialize SQLite durability backend.

        Args:
            persist_store: Optional AsyncPersistStore instance. If None, creates SQLitePersistStore.
            db_path: Database file path. Used only when persist_store is None.
                Defaults to metadata.db for ThreadInfo storage.
        """
        if persist_store is None:
            from soothe_sdk.paths import resolve_metadata_db_path

            actual_path = db_path or str(resolve_metadata_db_path())
            persist_store = SQLitePersistStore(actual_path, namespace="durability")
        super().__init__(persist_store)
