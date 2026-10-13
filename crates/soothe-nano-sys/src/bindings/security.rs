//! PyO3 bindings for `soothe-nano-security`.

use pyo3::prelude::*;

/// Python-visible path validator.
#[pyclass(name = "PathValidator")]
pub struct PyPathValidator {
    inner: soothe_nano_security::PathValidator,
}

#[pymethods]
impl PyPathValidator {
    #[new]
    #[pyo3(signature = (workspace = "."))]
    fn new(workspace: &str) -> Self {
        Self {
            inner: soothe_nano_security::PathValidator::new(workspace),
        }
    }

    fn validate(&self, py: Python<'_>, path: &str) -> PyValidationResult {
        py.allow_threads(|| {
            let r = self.inner.validate(path);
            r.into()
        })
    }
}

/// Python-visible validation result.
#[pyclass(name = "ValidationResult")]
#[derive(Clone)]
pub struct PyValidationResult {
    pub is_valid: bool,
    pub normalized_path: Option<String>,
    pub message: String,
}

#[pymethods]
impl PyValidationResult {
    #[getter]
    fn is_valid(&self) -> bool {
        self.is_valid
    }
    #[getter]
    fn normalized_path(&self) -> Option<&str> {
        self.normalized_path.as_deref()
    }
    #[getter]
    fn message(&self) -> &str {
        &self.message
    }
}

impl From<soothe_nano_security::ValidationResult> for PyValidationResult {
    fn from(r: soothe_nano_security::ValidationResult) -> Self {
        Self {
            is_valid: r.is_valid,
            normalized_path: r.normalized_path.map(|p| p.to_string_lossy().to_string()),
            message: r.message,
        }
    }
}

/// Register the security submodule.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyPathValidator>()?;
    m.add_class::<PyValidationResult>()?;
    Ok(())
}
