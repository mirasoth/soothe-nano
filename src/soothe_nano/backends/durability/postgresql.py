"""PostgreSQL durability backend: thread lifecycle and metadata persisted as JSONB."""

from __future__ import annotations

from soothe_nano.backends.durability.base import BasePersistStoreDurability
from soothe_nano.protocols.persistence import AsyncPersistStore


class PostgreSQLDurability(BasePersistStoreDurability):
    """DurabilityProtocol backed by PostgreSQL.

    ThreadInfo objects are serialized as JSONB via `PostgreSQLPersistStore`.

    Example:
        >>> store = PostgreSQLPersistStore(dsn=dsn, namespace="durability")
        >>> backend = PostgreSQLDurability(store)
    """

    def __init__(self, persist_store: AsyncPersistStore) -> None:
        """Initialize with PostgreSQL persist store.

        Args:
            persist_store: An AsyncPersistStore instance backed by PostgreSQL.
        """
        super().__init__(persist_store)
