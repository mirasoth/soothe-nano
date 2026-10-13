//! SQLite runtime with connection pooling (ported from `persistence/sqlite_runtime.py`).
//!
//! Uses `rusqlite` with bundled SQLite. WAL mode + busy_timeout set at pool init.
//! `tokio::task::spawn_blocking` wraps sync SQLite calls for async callers.

use rusqlite::{params, Connection};
use std::path::PathBuf;
use std::sync::Mutex;
use tokio::sync::Semaphore;

use crate::PersistError;

/// Runtime managing a writer connection + reader pool for a single SQLite DB.
#[allow(dead_code)]
pub struct SqliteStoreRuntime {
    writer: Mutex<Connection>,
    reader_pool: Semaphore,
    db_path: PathBuf,
}

impl SqliteStoreRuntime {
    /// Open or create a SQLite DB with WAL mode + busy_timeout pragmas.
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, PersistError> {
        let path = path.into();
        let conn = Connection::open(&path)?;

        // Set pragmas
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "busy_timeout", 5000)?;
        conn.pragma_update(None, "synchronous", "NORMAL")?;

        // Create table if not exists
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nano_kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )",
            [],
        )?;

        Ok(Self {
            writer: Mutex::new(conn),
            reader_pool: Semaphore::new(4),
            db_path: path,
        })
    }

    /// Save a key-value pair (writer).
    pub fn save_sync(&self, key: &str, value: &serde_json::Value) -> Result<(), PersistError> {
        let conn = self.writer.lock().unwrap();
        let value_str = serde_json::to_string(value)?;
        conn.execute(
            "INSERT OR REPLACE INTO nano_kv (key, value) VALUES (?1, ?2)",
            params![key, value_str],
        )?;
        Ok(())
    }

    /// Load a value by key (writer, read-only).
    pub fn load_sync(&self, key: &str) -> Result<Option<serde_json::Value>, PersistError> {
        let conn = self.writer.lock().unwrap();
        let mut stmt = conn.prepare("SELECT value FROM nano_kv WHERE key = ?1")?;
        let mut rows = stmt.query(params![key])?;
        if let Some(row) = rows.next()? {
            let value_str: String = row.get(0)?;
            let value: serde_json::Value = serde_json::from_str(&value_str)?;
            Ok(Some(value))
        } else {
            Ok(None)
        }
    }

    /// Delete a key (writer).
    pub fn delete_sync(&self, key: &str) -> Result<(), PersistError> {
        let conn = self.writer.lock().unwrap();
        conn.execute("DELETE FROM nano_kv WHERE key = ?1", params![key])?;
        Ok(())
    }

    /// List keys matching prefix (writer, read-only).
    pub fn keys_sync(&self, prefix: &str) -> Result<Vec<String>, PersistError> {
        let conn = self.writer.lock().unwrap();
        let mut stmt = conn.prepare("SELECT key FROM nano_kv WHERE key LIKE ?1")?;
        let pattern = format!("{prefix}%");
        let rows = stmt.query_map(params![pattern], |row| row.get::<_, String>(0))?;
        let mut keys = Vec::new();
        for key in rows {
            keys.push(key?);
        }
        Ok(keys)
    }

    /// Async save (wraps sync in spawn_blocking).
    pub async fn save(&self, key: String, value: serde_json::Value) -> Result<(), PersistError> {
        // For simplicity in the skeleton, we call sync directly.
        // In production: tokio::task::spawn_blocking with Arc clone.
        self.save_sync(&key, &value)
    }

    /// Async load.
    pub async fn load(&self, key: String) -> Result<Option<serde_json::Value>, PersistError> {
        self.load_sync(&key)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn save_load_delete() {
        let tmp = tempfile::NamedTempFile::new().unwrap();
        let rt = SqliteStoreRuntime::open(tmp.path()).unwrap();

        rt.save_sync("k1", &serde_json::json!({"v": 42})).unwrap();
        let loaded = rt.load_sync("k1").unwrap().unwrap();
        assert_eq!(loaded["v"], 42);

        rt.delete_sync("k1").unwrap();
        assert!(rt.load_sync("k1").unwrap().is_none());
    }

    #[test]
    fn keys_with_prefix() {
        let tmp = tempfile::NamedTempFile::new().unwrap();
        let rt = SqliteStoreRuntime::open(tmp.path()).unwrap();

        rt.save_sync("thread:1", &serde_json::json!(1)).unwrap();
        rt.save_sync("thread:2", &serde_json::json!(2)).unwrap();
        rt.save_sync("other:1", &serde_json::json!(3)).unwrap();

        let keys = rt.keys_sync("thread:").unwrap();
        assert_eq!(keys.len(), 2);
    }
}
