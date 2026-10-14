//! PyO3 bindings for `soothe-nano-persist`.

use pyo3::prelude::*;
use soothe_nano_persist::SqliteStoreRuntime;

#[pyclass(name = "SqliteStoreRuntime")]
pub struct PySqliteStoreRuntime {
    inner: SqliteStoreRuntime,
}

#[pymethods]
impl PySqliteStoreRuntime {
    /// Open or create a SQLite DB at `path` with WAL mode + busy_timeout.
    #[new]
    fn new(path: &str) -> PyResult<Self> {
        let runtime = SqliteStoreRuntime::open(path)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(Self { inner: runtime })
    }

    /// Save a key-value pair (JSON-serializable value).
    fn save_sync(&self, key: &str, value: &str) -> PyResult<()> {
        let json_val: serde_json::Value = serde_json::from_str(value)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        self.inner
            .save_sync(key, &json_val)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Load a value by key. Returns JSON string or None.
    fn load_sync(&self, key: &str) -> PyResult<Option<String>> {
        let result = self
            .inner
            .load_sync(key)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        match result {
            Some(val) => {
                let s = serde_json::to_string(&val)
                    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
                Ok(Some(s))
            }
            None => Ok(None),
        }
    }

    /// Delete a key.
    fn delete_sync(&self, key: &str) -> PyResult<()> {
        self.inner
            .delete_sync(key)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// List keys matching prefix.
    fn keys_sync(&self, prefix: &str) -> PyResult<Vec<String>> {
        self.inner
            .keys_sync(prefix)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySqliteStoreRuntime>()?;
    Ok(())
}
