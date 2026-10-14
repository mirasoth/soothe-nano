//! SQLite runtime, persist stores, durability, and pure-logic helpers.

pub mod advisory_lock;
pub mod dsn;
pub mod durability;
pub mod persist_store;
pub mod retry_classify;
pub mod sql_parsing;
pub mod sqlite_runtime;
pub mod vector_math;

pub use advisory_lock::advisory_lock_key;
pub use dsn::{admin_dsn, parse_dsn, target_dsn, DsnParts};
pub use durability::{DurabilityStore, ThreadLifecycle};
pub use persist_store::{AsyncPersistStore, SQLitePersistStore};
pub use retry_classify::{
    backoff_delay, is_duplicate_schema_error, is_recoverable_connection_error,
};
pub use sql_parsing::{is_valid_db_name, parse_migration_filename, split_sql_statements};
pub use sqlite_runtime::SqliteStoreRuntime;
pub use vector_math::{cosine_similarity, ip_similarity, l2_distance, pack_vector_f32};

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
