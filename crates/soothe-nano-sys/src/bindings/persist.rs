//! PyO3 bindings for `soothe-nano-persist`.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use soothe_nano_persist::SqliteStoreRuntime;
use std::sync::Arc;

#[pyclass(name = "SqliteStoreRuntime")]
pub struct PySqliteStoreRuntime {
    inner: Arc<SqliteStoreRuntime>,
}

#[pymethods]
impl PySqliteStoreRuntime {
    #[staticmethod]
    fn open(path: &str) -> PyResult<Self> {
        let runtime =
            SqliteStoreRuntime::open(path).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        Ok(Self {
            inner: Arc::new(runtime),
        })
    }

    fn save_sync(&self, key: &str, value: &str) -> PyResult<()> {
        let val: serde_json::Value =
            serde_json::from_str(value).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        self.inner
            .save_sync(key, &val)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    }

    fn load_sync(&self, py: Python<'_>, key: &str) -> PyResult<PyObject> {
        let result = self
            .inner
            .load_sync(key)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        match result {
            Some(value) => {
                let json_str = serde_json::to_string(&value)
                    .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                let json_mod = py.import_bound("json")?;
                let result = json_mod.call_method("loads", (json_str,), None)?;
                Ok(result.into())
            }
            None => Ok(py.None()),
        }
    }

    fn delete_sync(&self, key: &str) -> PyResult<()> {
        self.inner
            .delete_sync(key)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySqliteStoreRuntime>()?;
    Ok(())
}
