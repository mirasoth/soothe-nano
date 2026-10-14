//! Thread lifecycle persistence.

use crate::{AsyncPersistStore, PersistError};
use std::sync::Arc;

/// Thread lifecycle record.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ThreadLifecycle {
    pub thread_id: String,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_thread_id: Option<String>,
}

/// Durability store backed by `AsyncPersistStore`.
pub struct DurabilityStore {
    store: Arc<dyn AsyncPersistStore>,
}

impl DurabilityStore {
    pub fn new(store: Arc<dyn AsyncPersistStore>) -> Self {
        Self { store }
    }

    pub async fn save_thread(&self, lifecycle: &ThreadLifecycle) -> Result<(), PersistError> {
        let key = format!("thread:{}", lifecycle.thread_id);
        let value = serde_json::to_value(lifecycle).map_err(PersistError::Serde)?;
        self.store.save(&key, value).await
    }

    pub async fn load_thread(
        &self,
        thread_id: &str,
    ) -> Result<Option<ThreadLifecycle>, PersistError> {
        let key = format!("thread:{thread_id}");
        let value = self.store.load(&key).await?;
        match value {
            Some(v) => {
                let lc: ThreadLifecycle = serde_json::from_value(v).map_err(PersistError::Serde)?;
                Ok(Some(lc))
            }
            None => Ok(None),
        }
    }

    pub async fn delete_thread(&self, thread_id: &str) -> Result<(), PersistError> {
        let key = format!("thread:{thread_id}");
        self.store.delete(&key).await
    }

    pub async fn list_threads(&self) -> Result<Vec<String>, PersistError> {
        self.store.keys("thread:").await
    }
}
