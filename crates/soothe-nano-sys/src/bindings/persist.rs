//! PyO3 bindings for `soothe-nano-persist`.

use pyo3::prelude::*;
use pyo3::types::PyBytes;
use soothe_nano_persist::{
    advisory_lock_key, is_duplicate_schema_error, is_recoverable_connection_error,
    split_sql_statements, SqliteStoreRuntime,
};

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

// --- Free functions ---

/// Split an SQL script into individual statements.
#[pyfunction]
fn split_sql_statements_rust(sql: &str) -> Vec<String> {
    split_sql_statements(sql)
}

/// Check if an error message indicates a duplicate schema error.
#[pyfunction]
fn is_duplicate_schema_error_rust(exc_msg: &str) -> bool {
    is_duplicate_schema_error(exc_msg)
}

/// Check if an error message indicates a recoverable connection error.
#[pyfunction]
fn is_recoverable_connection_error_rust(exc_msg: &str) -> bool {
    is_recoverable_connection_error(exc_msg)
}

/// Compute a stable 63-bit advisory lock key from a database name.
#[pyfunction]
fn advisory_lock_key_rust(database: &str) -> i64 {
    advisory_lock_key(database)
}

/// Build a DSN targeting the `postgres` maintenance database.
#[pyfunction]
fn postgres_admin_dsn_rust(base_dsn: &str) -> Option<String> {
    soothe_nano_persist::admin_dsn(base_dsn)
}

/// Build a DSN targeting a named database under `base_dsn`.
#[pyfunction]
fn postgres_target_dsn_rust(base_dsn: &str, database_name: &str) -> Option<String> {
    soothe_nano_persist::target_dsn(base_dsn, database_name)
}

/// Validate a PostgreSQL database name.
#[pyfunction]
fn is_valid_db_name_rust(name: &str) -> bool {
    soothe_nano_persist::is_valid_db_name(name)
}

/// Parse a migration filename. Returns (version, name) or None.
#[pyfunction]
fn parse_migration_filename_rust(filename: &str) -> Option<(String, String)> {
    soothe_nano_persist::parse_migration_filename(filename).map(|p| (p.version, p.name))
}

/// Compute exponential backoff delay for a retry attempt.
#[pyfunction]
fn backoff_delay_rust(attempt: usize, base_delay: f64, max_delay: f64) -> f64 {
    soothe_nano_persist::backoff_delay(attempt, base_delay, max_delay)
}

/// Compute cosine similarity between two vectors.
#[pyfunction]
fn cosine_similarity_rust(a: Vec<f32>, b: Vec<f32>) -> f64 {
    soothe_nano_persist::cosine_similarity(&a, &b) as f64
}

/// Compute L2 (Euclidean) distance between two vectors.
#[pyfunction]
fn l2_distance_rust(a: Vec<f32>, b: Vec<f32>) -> f64 {
    soothe_nano_persist::l2_distance(&a, &b) as f64
}

/// Compute inner product (dot product) similarity.
#[pyfunction]
fn ip_similarity_rust(a: Vec<f32>, b: Vec<f32>) -> f64 {
    soothe_nano_persist::ip_similarity(&a, &b) as f64
}

/// Pack a list of floats into F32 binary format (little-endian). Returns bytes.
#[pyfunction]
fn pack_vector_f32_rust(py: Python<'_>, vector: Vec<f32>) -> PyObject {
    let packed = soothe_nano_persist::pack_vector_f32(&vector);
    PyBytes::new_bound(py, &packed).into()
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySqliteStoreRuntime>()?;
    m.add_function(wrap_pyfunction!(split_sql_statements_rust, m)?)?;
    m.add_function(wrap_pyfunction!(is_duplicate_schema_error_rust, m)?)?;
    m.add_function(wrap_pyfunction!(is_recoverable_connection_error_rust, m)?)?;
    m.add_function(wrap_pyfunction!(advisory_lock_key_rust, m)?)?;
    m.add_function(wrap_pyfunction!(postgres_admin_dsn_rust, m)?)?;
    m.add_function(wrap_pyfunction!(postgres_target_dsn_rust, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_db_name_rust, m)?)?;
    m.add_function(wrap_pyfunction!(parse_migration_filename_rust, m)?)?;
    m.add_function(wrap_pyfunction!(backoff_delay_rust, m)?)?;
    m.add_function(wrap_pyfunction!(cosine_similarity_rust, m)?)?;
    m.add_function(wrap_pyfunction!(l2_distance_rust, m)?)?;
    m.add_function(wrap_pyfunction!(ip_similarity_rust, m)?)?;
    m.add_function(wrap_pyfunction!(pack_vector_f32_rust, m)?)?;
    Ok(())
}
