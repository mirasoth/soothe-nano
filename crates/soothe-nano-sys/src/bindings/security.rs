//! PyO3 bindings for `soothe-nano-security`.
//!
//! Exposes `PathValidator`, `RateLimiter`, `SecurityPolicy`, and `OperationGuard`
//! as Python classes. These are standalone security utilities — they do not
//! replace the full Python `PathValidator` (which has suspicious patterns,
//! symlink detection, severity levels) but provide compiled-regex fast paths
//! and rate-limiting that Python can delegate to.

use pyo3::prelude::*;
use soothe_nano_security::{
    OperationGuard, OperationRecord, PathValidator, PolicyAction, RateLimiter, SecurityPolicy,
    ValidationResult, ViolationType,
};

// ── ValidationResult ──────────────────────────────────────────

#[pyclass(name = "ValidationResult")]
pub struct PyValidationResult {
    #[pyo3(get)]
    pub is_valid: bool,
    #[pyo3(get)]
    pub normalized_path: Option<String>,
    #[pyo3(get)]
    pub violation: String,
    #[pyo3(get)]
    pub message: String,
}

impl From<ValidationResult> for PyValidationResult {
    fn from(r: ValidationResult) -> Self {
        let violation = match r.violation {
            ViolationType::None => "none",
            ViolationType::PathEscape => "path_traversal",
            ViolationType::AbsolutePath => "absolute_path",
            ViolationType::NullByte => "null_byte",
            ViolationType::SymlinkEscape => "symlink_escape",
            ViolationType::TooLarge => "too_large",
        };
        Self {
            is_valid: r.is_valid,
            normalized_path: r.normalized_path.map(|p| p.to_string_lossy().to_string()),
            violation: violation.to_string(),
            message: r.message,
        }
    }
}

// ── PathValidator ─────────────────────────────────────────────

#[pyclass(name = "PathValidator")]
pub struct PyPathValidator {
    inner: PathValidator,
}

#[pymethods]
impl PyPathValidator {
    #[new]
    fn new(workspace: &str) -> Self {
        Self {
            inner: PathValidator::new(workspace),
        }
    }

    /// Validate a path string against security rules.
    fn validate(&self, path: &str) -> PyValidationResult {
        self.inner.validate(path).into()
    }
}

// ── RateLimiter ──────────────────────────────────────────────

#[pyclass(name = "RateLimiter")]
pub struct PyRateLimiter {
    inner: RateLimiter,
}

#[pymethods]
impl PyRateLimiter {
    #[new]
    #[pyo3(signature = (capacity = 60, refill_per_minute = 60))]
    fn new(capacity: u32, refill_per_minute: u32) -> Self {
        Self {
            inner: RateLimiter::new(capacity, refill_per_minute),
        }
    }

    /// Try to consume one token for `key`. Returns True if allowed.
    fn try_consume(&self, key: &str) -> bool {
        self.inner.try_consume(key)
    }
}

// ── SecurityPolicy ────────────────────────────────────────────

#[pyclass(name = "SecurityPolicy")]
pub struct PySecurityPolicy {
    inner: SecurityPolicy,
}

#[pymethods]
impl PySecurityPolicy {
    #[new]
    fn new() -> Self {
        Self {
            inner: SecurityPolicy::default(),
        }
    }

    /// Evaluate a path against all rules, returning the action name.
    fn evaluate_path(&self, path: &str) -> String {
        match self.inner.evaluate_path(path) {
            PolicyAction::Allow => "allow",
            PolicyAction::Deny => "deny",
            PolicyAction::Log => "log",
            PolicyAction::Notify => "notify",
            PolicyAction::Sanitize => "sanitize",
        }
        .to_string()
    }
}

// ── OperationGuard ───────────────────────────────────────────

#[pyclass(name = "OperationGuard")]
pub struct PyOperationGuard {
    inner: OperationGuard,
}

#[pymethods]
impl PyOperationGuard {
    #[new]
    fn new(workspace: &str) -> Self {
        Self {
            inner: OperationGuard::new(
                workspace,
                SecurityPolicy::default(),
                RateLimiter::default(),
            ),
        }
    }

    /// Check an operation. Returns ValidationResult on success, raises on deny.
    fn check(&self, operation: &str, path: &str) -> PyResult<PyValidationResult> {
        let record = OperationRecord {
            operation: operation.to_string(),
            path: path.to_string(),
            size: None,
        };
        match self.inner.check(&record) {
            Ok(result) => Ok(result.into()),
            Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
        }
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyValidationResult>()?;
    m.add_class::<PyPathValidator>()?;
    m.add_class::<PyRateLimiter>()?;
    m.add_class::<PySecurityPolicy>()?;
    m.add_class::<PyOperationGuard>()?;
    Ok(())
}
