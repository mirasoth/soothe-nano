//! PyO3 bindings for `soothe-nano-filesystem`.
//!
//! Exposes `LocalFilesystem` as a Python class providing read/write/edit/glob/grep
//! operations with workspace isolation and path validation. This is a standalone
//! utility — it does not participate in deepagents edit locks and should not be
//! used for operations that require concurrency safety. Use the Python
//! `LocalFilesystem` for production file operations.

use pyo3::prelude::*;
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
    Ok(())
}
