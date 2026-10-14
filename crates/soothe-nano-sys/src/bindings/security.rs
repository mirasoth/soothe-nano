//! PyO3 bindings for `soothe-nano-security`.

use std::str::FromStr;

use pyo3::prelude::*;
use soothe_nano_security::{
    path_is_under, OperationGuard, OperationRecord, PathPolicyDecision, PathValidator,
    PolicyAction, RateLimiter, SecurityPolicy, ValidationResult,
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
        let violation = match r.violation_type.as_str() {
            "none" | "" => "none",
            v => v,
        };
        Self {
            is_valid: r.is_valid,
            normalized_path: r.normalized_path,
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

    /// Validate a path string against security rules (full pipeline).
    fn validate(&self, path: &str) -> PyValidationResult {
        self.inner.validate(path).into()
    }

    /// Fast-path pre-check: traversal/absolute/null-byte only.
    /// Returns None when the path passes the fast check (caller continues).
    fn fast_check(&self, path: &str) -> Option<PyValidationResult> {
        self.inner.fast_check(path).map(|r| r.into())
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

    /// Try to consume one token for `key`.
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

    /// Evaluate a path against all rules.
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

    /// Check an operation against security rules.
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

// ── Banned-command matching (fast path) ───────────────────────

/// Return the first banned pattern's rule_id matching `command`, or None.
#[pyfunction]
fn dangerous_command_rule_id(py: Python<'_>, command: &str) -> Option<String> {
    py.allow_threads(|| soothe_nano_security::dangerous_command_rule_id(command))
}

/// Return all rule ids in the same family as `rule_id` (inclusive).
#[pyfunction]
fn rule_family(py: Python<'_>, rule_id: &str) -> Vec<String> {
    py.allow_threads(|| soothe_nano_security::rule_family(rule_id))
}

// ── Policy-models pure logic (delegated from policy_models.py) ─

/// True if `path` equals `prefix` (after rstrip '/') or sits beneath it.
#[pyfunction]
fn path_is_under_rust(path: &str, prefix: &str) -> bool {
    path_is_under(path, prefix)
}

/// True if a decision with `allowed` and `action` denies the operation.
#[pyfunction]
fn path_policy_is_denied(allowed: bool, action: &str) -> bool {
    let act = PolicyAction::from_str(action).ok().unwrap_or_default();
    !allowed || act == PolicyAction::Deny
}

/// True if a decision with `action` should be logged.
#[pyfunction]
fn path_policy_should_log(action: &str) -> bool {
    let act = PolicyAction::from_str(action).ok().unwrap_or_default();
    matches!(
        act,
        PolicyAction::Log | PolicyAction::Deny | PolicyAction::Notify
    )
}

/// Merge two decisions (most restrictive wins). Returns the merged field
/// tuple `(allowed, action, reason, sanitized_path)`; the caller combines
/// violations and metadata on the Python side (they are plain concatenation
/// / overlay and don't need Rust evaluation).
#[pyfunction]
#[allow(clippy::too_many_arguments)]
#[pyo3(signature = (
    self_allowed, self_action, self_reason, self_sanitized_path,
    other_allowed, other_action, other_reason, other_sanitized_path
))]
fn path_policy_merge(
    py: Python<'_>,
    self_allowed: bool,
    self_action: &str,
    self_reason: Option<String>,
    self_sanitized_path: Option<String>,
    other_allowed: bool,
    other_action: &str,
    other_reason: Option<String>,
    other_sanitized_path: Option<String>,
) -> (bool, String, Option<String>, Option<String>) {
    py.allow_threads(|| {
        let self_action = PolicyAction::from_str(self_action).ok().unwrap_or_default();
        let other_action = PolicyAction::from_str(other_action)
            .ok()
            .unwrap_or_default();
        let self_d = PathPolicyDecision {
            allowed: self_allowed,
            action: self_action,
            reason: self_reason,
            violations: Vec::new(),
            sanitized_path: self_sanitized_path,
            metadata: Default::default(),
        };
        let other_d = PathPolicyDecision {
            allowed: other_allowed,
            action: other_action,
            reason: other_reason,
            violations: Vec::new(),
            sanitized_path: other_sanitized_path,
            metadata: Default::default(),
        };
        let merged = self_d.merge(&other_d);
        (
            merged.allowed,
            merged.action.as_str().to_string(),
            merged.reason,
            merged.sanitized_path,
        )
    })
}

// ── Sliding-window rate limiter ────────────────────────────────

/// Python-facing sliding-window rate limiter (mirrors the Python
/// `security_enforcer.RateLimiter` class).
#[pyclass(name = "SlidingWindowRateLimiter")]
pub struct PySlidingWindowRateLimiter {
    inner: std::sync::Mutex<soothe_nano_security::SlidingWindowRateLimiter>,
}

#[pymethods]
impl PySlidingWindowRateLimiter {
    #[new]
    #[pyo3(signature = (window_seconds = 60))]
    fn new(window_seconds: u64) -> Self {
        Self {
            inner: std::sync::Mutex::new(soothe_nano_security::SlidingWindowRateLimiter::new(
                window_seconds,
            )),
        }
    }

    /// Record an operation for `operation` and `path`.
    fn record(&self, operation: &str, path: &str) -> PyResult<()> {
        let inner = self
            .inner
            .lock()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("lock error: {e}")))?;
        inner.record(operation, path);
        Ok(())
    }

    /// Check rate for `operation` with `max_count`; optionally per-`path`.
    /// Returns `(allowed, count)`.
    #[pyo3(signature = (operation, max_count, path=None))]
    fn check_rate(
        &self,
        operation: &str,
        max_count: usize,
        path: Option<&str>,
    ) -> PyResult<(bool, usize)> {
        let inner = self
            .inner
            .lock()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("lock error: {e}")))?;
        Ok(inner.check_rate(operation, max_count, path))
    }

    /// Return stats dict with `operations` and `paths` sub-dicts.
    fn get_stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
        let inner = self
            .inner
            .lock()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("lock error: {e}")))?;
        let stats = inner.get_stats();
        let dict = pyo3::types::PyDict::new_bound(py);
        for (category, sub) in &stats {
            let sub_dict = pyo3::types::PyDict::new_bound(py);
            for (k, v) in sub {
                sub_dict.set_item(k, *v)?;
            }
            dict.set_item(category, sub_dict)?;
        }
        Ok(dict)
    }
}

// ── Operation-guard pure-logic functions ───────────────────────

/// Return the first dangerous path component found in `path`, or None.
#[pyfunction]
fn find_dangerous_path_component(py: Python<'_>, path: &str) -> Option<String> {
    py.allow_threads(|| {
        soothe_nano_security::find_dangerous_path_component(path).map(|s| s.to_string())
    })
}

/// Return the first sensitive system path pattern that `path` matches, or None.
#[pyfunction]
fn matches_sensitive_system_path(py: Python<'_>, path: &str) -> Option<String> {
    py.allow_threads(|| {
        soothe_nano_security::matches_sensitive_system_path(path).map(|s| s.to_string())
    })
}

/// Return all PIDs targeted by `kill` invocations in `command`.
#[pyfunction]
fn kill_invocation_pids(py: Python<'_>, command: &str) -> Vec<i64> {
    py.allow_threads(|| soothe_nano_security::kill_invocation_pids(command))
}

/// Parse numeric PIDs from `kill` argument text (skip signal tokens).
#[pyfunction]
fn pids_from_kill_args(py: Python<'_>, args: &str) -> Vec<i64> {
    py.allow_threads(|| soothe_nano_security::pids_from_kill_args(args))
}

/// Allowlist record: (tool, signature, rule).
type AllowlistRecord = (String, Option<String>, Option<String>);

/// True when `command` is approved by an allowlist entry.
#[pyfunction]
#[pyo3(signature = (command, rule_id=None, allowlist=None))]
#[allow(clippy::type_complexity)]
fn command_approved_by_allowlist(
    py: Python<'_>,
    command: &str,
    rule_id: Option<&str>,
    allowlist: Option<Vec<AllowlistRecord>>,
) -> bool {
    py.allow_threads(|| {
        let allowlist: Vec<AllowlistRecord> = allowlist.unwrap_or_default();
        soothe_nano_security::command_approved_by_allowlist(command, rule_id, &allowlist)
    })
}

/// Glob (fnmatch) pattern match — case-sensitive, like Python's default.
#[pyfunction]
fn glob_match(py: Python<'_>, pattern: &str, text: &str) -> bool {
    py.allow_threads(|| soothe_nano_security::glob_match(pattern, text))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyValidationResult>()?;
    m.add_class::<PyPathValidator>()?;
    m.add_class::<PyRateLimiter>()?;
    m.add_class::<PySlidingWindowRateLimiter>()?;
    m.add_class::<PySecurityPolicy>()?;
    m.add_class::<PyOperationGuard>()?;
    m.add_function(wrap_pyfunction!(dangerous_command_rule_id, m)?)?;
    m.add_function(wrap_pyfunction!(rule_family, m)?)?;
    m.add_function(wrap_pyfunction!(path_is_under_rust, m)?)?;
    m.add_function(wrap_pyfunction!(path_policy_is_denied, m)?)?;
    m.add_function(wrap_pyfunction!(path_policy_should_log, m)?)?;
    m.add_function(wrap_pyfunction!(path_policy_merge, m)?)?;
    m.add_function(wrap_pyfunction!(find_dangerous_path_component, m)?)?;
    m.add_function(wrap_pyfunction!(matches_sensitive_system_path, m)?)?;
    m.add_function(wrap_pyfunction!(kill_invocation_pids, m)?)?;
    m.add_function(wrap_pyfunction!(pids_from_kill_args, m)?)?;
    m.add_function(wrap_pyfunction!(command_approved_by_allowlist, m)?)?;
    m.add_function(wrap_pyfunction!(glob_match, m)?)?;
    Ok(())
}
