//! PyO3 bindings for `soothe-nano-filesystem`.

use pyo3::prelude::*;
use soothe_nano_filesystem::discovery_hints::{
    format_glob_timeout_error, GLOB_DISCOVERY_FALLBACK_HINT, GREP_DISCOVERY_FALLBACK_HINT,
};
use soothe_nano_filesystem::LocalFilesystem;

#[pyclass(name = "LocalFilesystem")]
pub struct PyLocalFilesystem {
    inner: LocalFilesystem,
}

#[pymethods]
impl PyLocalFilesystem {
    #[new]
    fn new(workspace: &str) -> Self {
        Self {
            inner: LocalFilesystem::new(workspace),
        }
    }

    /// Read file contents with optional offset/limit (line-based).
    #[pyo3(signature = (path, offset = 0, limit = None))]
    fn read(&self, path: &str, offset: usize, limit: Option<usize>) -> PyResult<String> {
        let result = self
            .inner
            .read(path, offset, limit)
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        serde_json::to_string(&result)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    /// Write content to a file (creates or overwrites).
    fn write(&self, path: &str, content: &str) -> PyResult<u64> {
        let result = self
            .inner
            .write(path, content)
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        Ok(result.bytes_written)
    }

    /// Edit a file by replacing old_string with new_string (must be unique).
    fn edit(&self, path: &str, old_string: &str, new_string: &str) -> PyResult<usize> {
        let result = self
            .inner
            .edit(path, old_string, new_string)
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        Ok(result.replacements)
    }

    /// Glob for files matching a pattern under the workspace.
    fn glob(&self, pattern: &str) -> PyResult<Vec<String>> {
        let result = self
            .inner
            .glob(pattern)
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        Ok(result.files)
    }

    /// Grep for a literal pattern in files under the workspace.
    #[pyo3(signature = (pattern, path = "."))]
    fn grep(&self, pattern: &str, path: &str) -> PyResult<Vec<(String, usize, String)>> {
        let result = self
            .inner
            .grep(pattern, path)
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        Ok(result
            .matches
            .into_iter()
            .map(|m| (m.file, m.line_number, m.line))
            .collect())
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyLocalFilesystem>()?;
    m.add_function(wrap_pyfunction!(get_glob_discovery_fallback_hint, m)?)?;
    m.add_function(wrap_pyfunction!(get_grep_discovery_fallback_hint, m)?)?;
    m.add_function(wrap_pyfunction!(format_glob_timeout_error_py, m)?)?;
    Ok(())
}

#[pyfunction]
fn get_glob_discovery_fallback_hint() -> &'static str {
    GLOB_DISCOVERY_FALLBACK_HINT
}

#[pyfunction]
fn get_grep_discovery_fallback_hint() -> &'static str {
    GREP_DISCOVERY_FALLBACK_HINT
}

#[pyfunction]
fn format_glob_timeout_error_py(timeout_seconds: f64) -> String {
    format_glob_timeout_error(timeout_seconds)
}
