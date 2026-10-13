//! SQLite runtime, persist stores, durability.
//!
//! Ports: `persistence/sqlite_runtime.py`, `backends/persistence/sqlite_store.py`,
//! `backends/persistence/postgres_store.py`, `backends/durability/`.

pub mod durability;
pub mod persist_store;
pub mod sqlite_runtime;

pub use durability::{DurabilityStore, ThreadLifecycle};
pub use persist_store::{AsyncPersistStore, SQLitePersistStore};
pub use sqlite_runtime::SqliteStoreRuntime;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum PersistError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("serialization error: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("key not found: {0}")]
    NotFound(String),
    #[error("pool exhausted")]
    PoolExhausted,
}
