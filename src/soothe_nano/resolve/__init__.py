"""Protocol, subagent, and tool resolution for create_nano_agent.

Protocol resolution (memory, planner, policy) and infrastructure resolution
(durability, checkpointer) live here; tool/subagent resolution in
`_resolver_tools.py`; the shared checkpointer pool in `_shared_checkpointer_pool.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_nano.config import SootheConfig
from soothe_nano.core.exceptions import ConfigurationError

from ._resolver_tools import (
    SUBAGENT_FACTORIES,
    resolve_subagents,
    resolve_tools,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.types import Checkpointer

    from soothe_nano.protocols.durability import DurabilityProtocol
    from soothe_nano.protocols.memory import MemoryProtocol
    from soothe_nano.protocols.planner import PlannerProtocol
    from soothe_nano.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_FACTORIES",
    "resolve_checkpointer",
    "resolve_durability",
    "resolve_memory",
    "resolve_planner",
    "resolve_policy",
    "resolve_subagents",
    "resolve_tools",
]


# ---------------------------------------------------------------------------
# Protocol resolution (memory, planner, policy)
# ---------------------------------------------------------------------------


def _create_loop_phase_model(
    config: SootheConfig,
    role: str,
    *,
    fallback: BaseChatModel | None,
    phase: str,
) -> BaseChatModel | None:
    """Resolve a loop-phase chat model from router role."""
    try:
        return config.create_chat_model(role)
    except Exception:
        logger.warning(
            "Failed to create %s model for role=%s; falling back to planner model",
            phase,
            role,
            exc_info=True,
        )
        return fallback


def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation using MemU.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if not config.agent.protocols.memory.enabled:
        return None

    try:
        from soothe_nano.backends.memory.memu_adapter import MemUMemory

        logger.info(
            "Using MemU memory backend (chat: %s, embed: %s)",
            config.resolve_model(config.agent.protocols.memory.llm_chat_role),
            config.resolve_model(config.agent.protocols.memory.llm_embed_role),
        )

        return MemUMemory(config)

    except ImportError:
        logger.exception("MemU memory backend requires dependencies")
        raise
    except Exception:
        logger.exception("Failed to initialize MemU memory backend")
        raise


def resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol | None:
    """Resolve planner protocol for Coding CoreAgent.

    `LLMPlanner` lives in full `soothe`. Inject via `AgentBuilder.build(planner=...)`.
    """
    del config, model
    return None


def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A PolicyProtocol instance.
    """
    from soothe_nano.security import ConfigDrivenPolicy

    return ConfigDrivenPolicy(config=config)


# ---------------------------------------------------------------------------
# Infrastructure resolution (durability, checkpointer)
# ---------------------------------------------------------------------------


def resolve_durability(
    config: SootheConfig,
    *,
    metadata_pool_cls: type | None = None,
) -> DurabilityProtocol:
    """Instantiate the DurabilityProtocol implementation from config.

    Supports: postgresql, sqlite backends (binary choice).
    Uses multi-database PostgreSQL architecture (metadata database).

    Args:
        config: Soothe configuration.
        metadata_pool_cls: Optional metadata pool class (host injects its
            registry-bound subclass). Defaults to nano `SharedMetadataPool`.
    """
    backend = config.resolve_durability_backend()  # Resolve inheritance
    if backend == "postgresql":
        try:
            from soothe_nano.backends.durability.postgresql import PostgreSQLDurability
            from soothe_nano.backends.persistence import create_persist_store
            from soothe_nano.persistence.shared_metadata_pool import SharedMetadataPool

            pool_cls = metadata_pool_cls or SharedMetadataPool
            # Use dedicated metadata database.
            dsn = config.resolve_postgres_dsn_for_database("metadata")
            shared_pool = pool_cls.get_or_create_pool(config)
            persist_store = create_persist_store(
                backend="postgresql",
                dsn=dsn,
                namespace="durability",
                config=config,
                shared_pool=shared_pool,
            )
            logger.debug("Using PostgreSQL durability backend (metadata database)")
            return PostgreSQLDurability(persist_store=persist_store)
        except Exception as e:
            logger.error(
                "PostgreSQL durability requested but failed: %s. "
                "Check PostgreSQL configuration and connectivity. "
                "Ensure soothe is up to date: pip install -U soothe-nano",
                e,
            )
            raise ConfigurationError(
                f"PostgreSQL durability backend unavailable: {e}\n"
                f"Verify postgres_base_dsn and postgres_databases configuration.\n"
                f"Ensure metadata database is created and accessible."
            )

    if backend == "sqlite":
        try:
            from soothe_nano.backends.durability.sqlite import SQLiteDurability

            logger.info("Using SQLite durability backend (databases/metadata.db)")
            return SQLiteDurability()
        except Exception as e:
            logger.error(
                "SQLite durability requested but failed: %s. "
                "Check sqlite3 installation and path configuration.",
                e,
            )
            raise ConfigurationError(
                f"SQLite durability backend unavailable: {e}\nVerify database path configuration."
            )

    raise ConfigurationError(
        f"Unknown durability backend: {backend}\nSupported backends: postgresql, sqlite"
    )


def resolve_checkpointer(
    config: SootheConfig,
    *,
    checkpointer_pool_cls: type | None = None,
) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Uses persistence configuration for PostgreSQL or SQLite connection.
    Uses dedicated checkpoints database for PostgreSQL.
    No fallback to in-memory storage - persistent storage required.

    Args:
        config: Soothe configuration.
        checkpointer_pool_cls: Optional checkpointer pool class (host injects
            its registry-bound subclass). Defaults to nano
            `SharedCheckpointerPool`.

    Returns:
        A tuple of (checkpointer, connection_resource) for PostgreSQL, or just the checkpointer for SQLite.
        The connection_resource must be closed during cleanup (e.g., via runner.cleanup()).
    """
    backend = config.resolve_checkpointer_backend()  # Resolve inheritance
    if backend == "postgresql":
        from soothe_nano.resolve._shared_checkpointer_pool import SharedCheckpointerPool

        pool_cls = checkpointer_pool_cls or SharedCheckpointerPool
        pool = pool_cls.get_or_create_pool(config)
        if pool is not None:
            return (None, pool)
        logger.error("PostgreSQL checkpointer unavailable")
        raise ConfigurationError(
            "PostgreSQL checkpointer requested but failed.\n"
            "Check postgres_base_dsn and postgres_databases configuration.\n"
            "Ensure checkpoints database is created and accessible.\n"
            "No fallback - production requires persistent storage."
        )

    if backend == "sqlite":
        result = _resolve_sqlite_checkpointer(config)
        if result:
            return result
        logger.error("SQLite checkpointer unavailable")
        raise ConfigurationError(
            "SQLite checkpointer requested but failed.\n"
            "Check sqlite3 installation and path configuration.\n"
            "No fallback - persistent storage required."
        )

    raise ConfigurationError(
        f"Unknown checkpointer backend: {backend}\n"
        f"Supported: postgresql, sqlite\n"
        f"No in-memory fallback - persistent storage required."
    )


def _resolve_sqlite_checkpointer(config: SootheConfig) -> tuple[Checkpointer | None, Any] | None:
    """Resolve SQLite checkpointer database path.

    Defers AsyncSqliteSaver creation to async context (same pattern as PostgreSQL).
    Callers that construct the saver need `langgraph-checkpoint-sqlite` installed.

    Returns:
        A tuple of (None, db_path) if successful, None otherwise.
        The runner will create AsyncSqliteSaver from the path in async context.
    """
    try:
        from soothe_nano.paths import resolve_checkpoints_db_path

        db_path = str(resolve_checkpoints_db_path())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Failed to create SQLite checkpointer path: %s", exc)
        return None

    logger.info("SQLite checkpointer path resolved at %s", db_path)
    return (None, db_path)
