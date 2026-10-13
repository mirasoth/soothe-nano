//! PyO3 bindings for `soothe-nano-filesystem`.

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

    #[pyo3(signature = (path, offset = 0, limit = None))]
    fn read(
        &self,
        py: Python<'_>,
        path: &str,
        offset: usize,
        limit: Option<usize>,
    ) -> PyResult<String> {
        py.allow_threads(|| {
            self.inner
                .read(path, offset, limit)
                .map(|r| r.content)
                .map_err(pyo3::exceptions::PyRuntimeError::new_err)
        })
    }

    fn write(&self, py: Python<'_>, path: &str, content: &str) -> PyResult<u64> {
        py.allow_threads(|| {
            self.inner
                .write(path, content)
                .map(|r| r.bytes_written)
                .map_err(pyo3::exceptions::PyRuntimeError::new_err)
        })
    }

    fn edit(&self, py: Python<'_>, path: &str, old: &str, new: &str) -> PyResult<usize> {
        py.allow_threads(|| {
            self.inner
                .edit(path, old, new)
                .map(|r| r.replacements)
                .map_err(pyo3::exceptions::PyRuntimeError::new_err)
        })
    }

    fn glob(&self, py: Python<'_>, pattern: &str) -> PyResult<Vec<String>> {
        py.allow_threads(|| {
            self.inner
                .glob(pattern)
                .map(|r| r.files)
                .map_err(pyo3::exceptions::PyRuntimeError::new_err)
        })
    }

    fn grep(
        &self,
        py: Python<'_>,
        pattern: &str,
        path: &str,
    ) -> PyResult<Vec<(String, usize, String)>> {
        py.allow_threads(|| {
            self.inner
                .grep(pattern, path)
                .map(|r| {
                    r.matches
                        .into_iter()
                        .map(|m| (m.file, m.line_number, m.line))
                        .collect()
                })
                .map_err(pyo3::exceptions::PyRuntimeError::new_err)
        })
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyLocalFilesystem>()?;
    Ok(())
}
