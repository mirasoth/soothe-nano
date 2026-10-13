//! Persist store trait + SQLite implementation
//! (ported from `backends/persistence/sqlite_store.py`).

use async_trait::async_trait;
use serde_json::Value;
use std::sync::Arc;

use crate::{PersistError, SqliteStoreRuntime};

/// Async persist store trait (mirrors `soothe_sdk.protocols.persistence`).
#[async_trait]
pub trait AsyncPersistStore: Send + Sync {
    async fn save(&self, key: &str, value: Value) -> Result<(), PersistError>;
    async fn load(&self, key: &str) -> Result<Option<Value>, PersistError>;
    async fn delete(&self, key: &str) -> Result<(), PersistError>;
    async fn keys(&self, prefix: &str) -> Result<Vec<String>, PersistError>;
}

/// SQLite-backed persist store.
pub struct SQLitePersistStore {
    runtime: Arc<SqliteStoreRuntime>,
}

impl SQLitePersistStore {
    pub fn new(runtime: Arc<SqliteStoreRuntime>) -> Self {
        Self { runtime }
    }
}

#[async_trait]
impl AsyncPersistStore for SQLitePersistStore {
    async fn save(&self, key: &str, value: Value) -> Result<(), PersistError> {
        self.runtime.save(key.to_string(), value).await
    }

    async fn load(&self, key: &str) -> Result<Option<Value>, PersistError> {
        self.runtime.load(key.to_string()).await
    }

    async fn delete(&self, key: &str) -> Result<(), PersistError> {
        self.runtime.delete_sync(key)
    }

    async fn keys(&self, prefix: &str) -> Result<Vec<String>, PersistError> {
        self.runtime.keys_sync(prefix)
    }
}
