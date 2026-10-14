//! PyO3 bindings for `soothe-nano-protocols`.
//!
//! Exposes pure-logic functions that the Python protocol modules delegate to.
//! The Pydantic models themselves stay in Python (for `model_dump` /
//! `model_validate` compatibility), but their pure logic is Rust-backed.

use pyo3::prelude::*;
use serde_json::Value;
use soothe_nano_protocols::{
    self, identity, operation_security, planner, policy, vector_store::VectorRecord,
};

// ── Planner pure logic ────────────────────────────────────────

/// Resolve bounded planner-facing text from an outcome dict (JSON string).
/// Returns the first non-empty stripped string from keys:
/// `wave_join_preview`, `task_return_preview`, `output_summary`, or None.
#[pyfunction]
fn planner_outcome_text_preview(py: Python<'_>, outcome_json: &str) -> Option<String> {
    py.allow_threads(|| {
        let outcome: Value = serde_json::from_str(outcome_json).ok()?;
        planner::planner_outcome_text_preview(&outcome)
    })
}

/// Build an evidence string for a StepResult from its JSON representation.
/// Mirrors `StepResult.to_evidence_string(truncate=...)`.
#[pyfunction]
#[pyo3(signature = (step_result_json, truncate = true))]
fn step_result_to_evidence_string(
    py: Python<'_>,
    step_result_json: &str,
    truncate: bool,
) -> String {
    py.allow_threads(|| {
        let result: planner::StepResult = match serde_json::from_str(step_result_json) {
            Ok(r) => r,
            Err(_) => return "Step ?: ✗ Error: invalid step result".to_string(),
        };
        result.to_evidence_string(truncate)
    })
}

/// True when `hint` is a valid execution hint.
#[pyfunction]
fn is_valid_execution_hint(hint: &str) -> bool {
    planner::is_valid_execution_hint(hint)
}

/// True when `status` is a valid step status.
#[pyfunction]
fn is_valid_step_status(status: &str) -> bool {
    planner::is_valid_step_status(status)
}

/// True when `status` is a valid plan status.
#[pyfunction]
fn is_valid_plan_status(status: &str) -> bool {
    planner::is_valid_plan_status(status)
}

/// True when `action` is a valid goal directive action.
#[pyfunction]
fn is_valid_goal_directive_action(action: &str) -> bool {
    planner::is_valid_goal_directive_action(action)
}

// ── Policy pure logic ─────────────────────────────────────────

/// Check if a granted permission covers a requested permission.
/// Mirrors `Permission.matches(requested)`.
#[pyfunction]
fn permission_matches(
    category: &str,
    action: &str,
    scope: &str,
    req_category: &str,
    req_action: &str,
    req_scope: &str,
) -> bool {
    let granted = policy::Permission::with_scope(category.into(), action.into(), scope.into());
    let requested =
        policy::Permission::with_scope(req_category.into(), req_action.into(), req_scope.into());
    granted.matches(&requested)
}

/// fnmatch-style glob match (shell wildcard matching).
/// Returns true if `pattern` matches `text`.
#[pyfunction]
fn glob_match(pattern: &str, text: &str) -> bool {
    policy::glob_match(pattern, text)
}

/// True when `category` is a valid permission category.
#[pyfunction]
fn is_valid_permission_category(category: &str) -> bool {
    policy::is_valid_category(category)
}

/// True when `action` is a valid permission action.
#[pyfunction]
fn is_valid_permission_action(action: &str) -> bool {
    policy::is_valid_action(action)
}

/// True when `verdict` is a valid policy decision verdict.
#[pyfunction]
fn is_valid_policy_verdict(verdict: &str) -> bool {
    policy::is_valid_policy_verdict(verdict)
}

// ── Identity pure logic ───────────────────────────────────────

/// True when `token_type` is a valid token type (access or refresh).
#[pyfunction]
fn is_valid_token_type(token_type: &str) -> bool {
    identity::is_valid_token_type(token_type)
}

/// Check if an AKSK pair is active given its JSON representation and current ISO timestamp.
/// Returns `(is_revoked, is_expired, is_active)`.
#[pyfunction]
fn aksk_pair_status(py: Python<'_>, aksk_json: &str, now_iso: &str) -> (bool, bool, bool) {
    py.allow_threads(|| {
        let pair: identity::AKSKPair = match serde_json::from_str(aksk_json) {
            Ok(p) => p,
            Err(_) => return (true, true, false),
        };
        (
            pair.is_revoked(),
            pair.is_expired(now_iso),
            pair.is_active(now_iso),
        )
    })
}

/// Check if a token claims object is expired given its JSON representation and current ISO timestamp.
#[pyfunction]
fn token_claims_is_expired(py: Python<'_>, claims_json: &str, now_iso: &str) -> Option<bool> {
    py.allow_threads(|| {
        let claims: identity::TokenClaims = serde_json::from_str(claims_json).ok()?;
        Some(claims.is_expired(now_iso))
    })
}

/// Check if a token info object is active given its JSON representation and current ISO timestamp.
/// Returns `(is_revoked, is_expired, is_active)`.
#[pyfunction]
fn token_info_status(py: Python<'_>, token_json: &str, now_iso: &str) -> (bool, bool, bool) {
    py.allow_threads(|| {
        let ti: identity::TokenInfo = match serde_json::from_str(token_json) {
            Ok(t) => t,
            Err(_) => return (true, true, false),
        };
        (
            ti.is_revoked(),
            ti.is_expired(now_iso),
            ti.is_active(now_iso),
        )
    })
}

// ── Concurrency pure logic ────────────────────────────────────

/// True when `parallelism` is a valid step_parallelism value.
#[pyfunction]
fn is_valid_step_parallelism(parallelism: &str) -> bool {
    soothe_nano_protocols::concurrency::is_valid_step_parallelism(parallelism)
}

/// True when `max_parallel` value means unlimited (0).
#[pyfunction]
fn is_unlimited(max_parallel: i64) -> bool {
    max_parallel == 0
}

// ── Memory pure logic ─────────────────────────────────────────

/// True when `importance` is within the valid range [0.0, 1.0].
#[pyfunction]
fn is_valid_importance(importance: f64) -> bool {
    (0.0..=1.0).contains(&importance)
}

// ── Operation security pure logic ─────────────────────────────

/// True when `kind` is a valid operation kind.
#[pyfunction]
fn is_valid_operation_kind(kind: &str) -> bool {
    operation_security::is_valid_operation_kind(kind)
}

/// True when `verdict` is a valid operation security decision verdict.
#[pyfunction]
fn is_valid_operation_security_verdict(verdict: &str) -> bool {
    operation_security::is_valid_verdict(verdict)
}

// ── Durability pure logic ─────────────────────────────────────

/// True when `status` is a valid thread status.
#[pyfunction]
fn is_valid_thread_status(status: &str) -> bool {
    soothe_nano_protocols::durability::is_valid_status(status)
}

/// True when `priority` is a valid thread priority.
#[pyfunction]
fn is_valid_thread_priority(priority: &str) -> bool {
    soothe_nano_protocols::durability::is_valid_priority(priority)
}

/// Strip the legacy `claude_sessions` key from a metadata dict (JSON string).
/// Returns the cleaned JSON string.
#[pyfunction]
fn strip_legacy_claude_sessions(py: Python<'_>, metadata_json: &str) -> String {
    py.allow_threads(|| {
        let mut val: Value =
            serde_json::from_str(metadata_json).unwrap_or(Value::Object(Default::default()));
        if let Some(obj) = val.as_object_mut() {
            obj.remove("claude_sessions");
        }
        serde_json::to_string(&val).unwrap_or_else(|_| "{}".to_string())
    })
}

// ── Vector store pure logic ───────────────────────────────────

/// Create a new VectorRecord as JSON string.
#[pyfunction]
fn vector_record_new(py: Python<'_>, id: &str) -> String {
    py.allow_threads(|| {
        let r = VectorRecord::new(id.to_string());
        serde_json::to_string(&r).unwrap_or_else(|_| "{}".to_string())
    })
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Planner
    m.add_function(wrap_pyfunction!(planner_outcome_text_preview, m)?)?;
    m.add_function(wrap_pyfunction!(step_result_to_evidence_string, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_execution_hint, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_step_status, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_plan_status, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_goal_directive_action, m)?)?;

    // Policy
    m.add_function(wrap_pyfunction!(permission_matches, m)?)?;
    m.add_function(wrap_pyfunction!(glob_match, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_permission_category, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_permission_action, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_policy_verdict, m)?)?;

    // Identity
    m.add_function(wrap_pyfunction!(is_valid_token_type, m)?)?;
    m.add_function(wrap_pyfunction!(aksk_pair_status, m)?)?;
    m.add_function(wrap_pyfunction!(token_claims_is_expired, m)?)?;
    m.add_function(wrap_pyfunction!(token_info_status, m)?)?;

    // Concurrency
    m.add_function(wrap_pyfunction!(is_valid_step_parallelism, m)?)?;
    m.add_function(wrap_pyfunction!(is_unlimited, m)?)?;

    // Memory
    m.add_function(wrap_pyfunction!(is_valid_importance, m)?)?;

    // Operation security
    m.add_function(wrap_pyfunction!(is_valid_operation_kind, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_operation_security_verdict, m)?)?;

    // Durability
    m.add_function(wrap_pyfunction!(is_valid_thread_status, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_thread_priority, m)?)?;
    m.add_function(wrap_pyfunction!(strip_legacy_claude_sessions, m)?)?;

    // Vector store
    m.add_function(wrap_pyfunction!(vector_record_new, m)?)?;

    Ok(())
}
