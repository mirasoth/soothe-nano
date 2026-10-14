//! PyO3 bindings for `soothe-nano-diagnose`.

use pyo3::prelude::*;
use pyo3::types::PyDict;
use soothe_nano_diagnose::models::{aggregate_status, CheckResult, CheckStatus};
use soothe_nano_diagnose::{
    mcp, models_check, observability, protocols, providers, tool_deps, vector_stores,
};

// ── CheckStatus helpers ───────────────────────────────────────

/// Return the string value of a CheckStatus.
#[pyfunction]
fn check_status_str(status: &str) -> Option<String> {
    CheckStatus::parse_str(status).map(|s| s.as_str().to_string())
}

/// Return the numeric severity of a CheckStatus string.
#[pyfunction]
fn check_status_severity(status: &str) -> Option<i32> {
    CheckStatus::parse_str(status).map(|s| s.severity())
}

/// Aggregate multiple status strings into one (worst wins). Returns "ok" for empty.
#[pyfunction]
fn aggregate_status_rust(statuses: Vec<String>) -> String {
    let parsed: Vec<CheckStatus> = statuses
        .iter()
        .filter_map(|s| CheckStatus::parse_str(s))
        .collect();
    aggregate_status(&parsed).as_str().to_string()
}

/// Compare two status strings by severity. Returns -1, 0, 1, or None for unknown.
#[pyfunction]
fn compare_status(a: &str, b: &str) -> Option<i32> {
    let a = CheckStatus::parse_str(a)?;
    let b = CheckStatus::parse_str(b)?;
    Some(a.cmp(&b) as i32)
}

// ── CheckResult construction (returns dict matching to_dict contract) ──

/// Build a CheckResult dict from name, status, message, and optional details dict.
#[pyfunction]
#[pyo3(signature = (name, status, message, details=None))]
fn check_result_to_dict(
    py: Python<'_>,
    name: &str,
    status: &str,
    message: &str,
    details: Option<Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    let status = CheckStatus::parse_str(status).ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err(format!("Unknown status: {status}"))
    })?;
    let details_json = match details {
        Some(d) => {
            let json_str = py
                .import_bound("json")?
                .call_method("dumps", (d.clone(),), None)?
                .extract::<String>()?;
            serde_json::from_str(&json_str)
                .unwrap_or(serde_json::Value::Object(serde_json::Map::new()))
        }
        None => serde_json::Value::Object(serde_json::Map::new()),
    };
    let cr = CheckResult {
        name: name.to_string(),
        status,
        message: message.to_string(),
        details: details_json,
    };
    dict_from_json(py, &cr.to_dict())
}

/// Build a CategoryResult dict from category, status, and a list of check dicts.
#[pyfunction]
#[pyo3(signature = (category, status, check_dicts, message=None))]
fn category_result_to_dict(
    py: Python<'_>,
    category: &str,
    status: &str,
    check_dicts: Vec<Bound<'_, PyDict>>,
    message: Option<String>,
) -> PyResult<PyObject> {
    let status = CheckStatus::parse_str(status).ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err(format!("Unknown status: {status}"))
    })?;
    let json_mod = py.import_bound("json")?;
    let mut checks_json: Vec<serde_json::Value> = Vec::new();
    for d in &check_dicts {
        let json_str: String = json_mod
            .call_method("dumps", (d.clone(),), None)?
            .extract()?;
        let val: serde_json::Value =
            serde_json::from_str(&json_str).unwrap_or(serde_json::Value::Null);
        checks_json.push(val);
    }

    let mut map = serde_json::Map::new();
    map.insert(
        "category".into(),
        serde_json::Value::String(category.to_string()),
    );
    map.insert(
        "status".into(),
        serde_json::Value::String(status.as_str().to_string()),
    );
    map.insert("checks".into(), serde_json::Value::Array(checks_json));
    map.insert(
        "message".into(),
        message
            .map(serde_json::Value::String)
            .unwrap_or(serde_json::Value::Null),
    );
    dict_from_json(py, &serde_json::Value::Object(map))
}

// ── tool_deps ─────────────────────────────────────────────────

/// Build the tool_deps category result dict from resolved binary paths.
#[pyfunction]
#[pyo3(signature = (rg_path=None, fd_path=None, git_path=None))]
fn check_tool_deps_rust(
    py: Python<'_>,
    rg_path: Option<String>,
    fd_path: Option<String>,
    git_path: Option<String>,
) -> PyResult<PyObject> {
    let cat =
        tool_deps::check_tool_deps(rg_path.as_deref(), fd_path.as_deref(), git_path.as_deref());
    dict_from_json(py, &cat.to_dict())
}

// ── protocols ─────────────────────────────────────────────────

/// Build the protocols category result from import-check results.
/// `results` = list of (name, module_path, ok: bool, error_msg) tuples.
#[pyfunction]
fn check_protocols_from_results_rust(
    py: Python<'_>,
    results: Vec<(String, String, bool, String)>,
) -> PyResult<PyObject> {
    let cat = protocols::check_protocols_from_results(&results);
    dict_from_json(py, &cat.to_dict())
}

// ── vector_stores ─────────────────────────────────────────────

/// Build the vector_stores category result from pre-built check dicts.
#[pyfunction]
fn check_vector_stores_from_results_rust(
    py: Python<'_>,
    check_dicts: Vec<Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    let checks = parse_check_dicts(py, &check_dicts)?;
    let cat = vector_stores::check_vector_stores_from_results(checks);
    dict_from_json(py, &cat.to_dict())
}

// ── models_check ──────────────────────────────────────────────

/// Build the models category result when no config is loaded.
#[pyfunction]
fn check_models_no_config_rust(py: Python<'_>) -> PyResult<PyObject> {
    let cat = models_check::check_models_no_config();
    dict_from_json(py, &cat.to_dict())
}

/// Build the models category result when embedding_profile is not set (warning).
#[pyfunction]
#[pyo3(signature = (resolved=None, skillify_model_role="embedding", skillify_resolved=None, embedding_dims=None))]
fn check_models_no_profile_rust(
    py: Python<'_>,
    resolved: Option<String>,
    skillify_model_role: &str,
    skillify_resolved: Option<String>,
    embedding_dims: Option<i64>,
) -> PyResult<PyObject> {
    let cat = models_check::check_models_no_profile(
        resolved.as_deref(),
        skillify_model_role,
        skillify_resolved.as_deref(),
        embedding_dims,
    );
    dict_from_json(py, &cat.to_dict())
}

/// Build the models category result when embedding_profile is configured (ok).
#[pyfunction]
#[pyo3(signature = (resolved, skillify_model_role="embedding", skillify_resolved=None, embedding_dims=None))]
fn check_models_ok_rust(
    py: Python<'_>,
    resolved: &str,
    skillify_model_role: &str,
    skillify_resolved: Option<String>,
    embedding_dims: Option<i64>,
) -> PyResult<PyObject> {
    let cat = models_check::check_models_ok(
        resolved,
        skillify_model_role,
        skillify_resolved.as_deref(),
        embedding_dims,
    );
    dict_from_json(py, &cat.to_dict())
}

// ── observability ─────────────────────────────────────────────

/// Build the observability category result from pre-built check dicts.
#[pyfunction]
fn check_observability_from_results_rust(
    py: Python<'_>,
    check_dicts: Vec<Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    let checks = parse_check_dicts(py, &check_dicts)?;
    let cat = observability::check_observability_from_results(checks);
    dict_from_json(py, &cat.to_dict())
}

// ── providers ─────────────────────────────────────────────────

/// Validate provider credentials. Returns a check result dict.
#[pyfunction]
#[pyo3(signature = (provider_name, api_key=None, provider_type="openai"))]
fn check_provider_credentials_rust(
    py: Python<'_>,
    provider_name: &str,
    api_key: Option<String>,
    provider_type: &str,
) -> PyResult<PyObject> {
    let cr =
        providers::check_provider_credentials(provider_name, api_key.as_deref(), provider_type);
    dict_from_json(py, &cr.to_dict())
}

/// Downgrade credential failures for providers not used by the active profile.
#[pyfunction]
#[pyo3(signature = (check_dict, active, profile_name=None))]
fn demote_inactive_provider_check_rust(
    py: Python<'_>,
    check_dict: Bound<'_, PyDict>,
    active: Vec<String>,
    profile_name: Option<String>,
) -> PyResult<PyObject> {
    let check = parse_single_check_dict(py, &check_dict)?;
    let active_set: std::collections::HashSet<String> = active.into_iter().collect();
    let demoted =
        providers::demote_inactive_provider_check(&check, &active_set, profile_name.as_deref());
    dict_from_json(py, &demoted.to_dict())
}

/// Build a missing-active-provider check result dict.
#[pyfunction]
#[pyo3(signature = (name, profile_name=None))]
fn missing_active_provider_rust(
    py: Python<'_>,
    name: &str,
    profile_name: Option<String>,
) -> PyResult<PyObject> {
    let cr = providers::missing_active_provider(name, profile_name.as_deref());
    dict_from_json(py, &cr.to_dict())
}

/// Build the providers category result from pre-built check dicts.
#[pyfunction]
fn check_providers_from_results_rust(
    py: Python<'_>,
    check_dicts: Vec<Bound<'_, PyDict>>,
    status_check_dicts: Vec<Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    let checks = parse_check_dicts(py, &check_dicts)?;
    let status_checks = parse_check_dicts(py, &status_check_dicts)?;
    let cat = providers::check_providers_from_results(checks, &status_checks);
    dict_from_json(py, &cat.to_dict())
}

/// Extract provider name from a `provider:model` spec.
#[pyfunction]
#[pyo3(signature = (spec=None))]
fn provider_from_spec_rust(spec: Option<String>) -> Option<String> {
    providers::provider_from_spec(spec.as_deref())
}

/// True if value contains an unresolved `${ENV}` reference.
#[pyfunction]
#[pyo3(signature = (value=None))]
fn unresolved_env_ref_rust(value: Option<String>) -> bool {
    providers::unresolved_env_ref(value.as_deref())
}

/// Collect active provider names from router specs and embedding config.
#[pyfunction]
#[pyo3(signature = (router_specs, embedding_model=None, embedding_profile_model_role=None))]
fn active_provider_names_rust(
    router_specs: [Option<String>; 5],
    embedding_model: Option<String>,
    embedding_profile_model_role: Option<String>,
) -> Vec<String> {
    let names = providers::active_provider_names(
        &router_specs,
        embedding_model.as_deref(),
        embedding_profile_model_role.as_deref(),
    );
    names.into_iter().collect()
}

// ── mcp ───────────────────────────────────────────────────────

/// Check MCP server configs from spec data.
/// `server_specs` = list of (name, transport, command, url) tuples.
#[pyfunction]
fn check_mcp_configs_rust(
    py: Python<'_>,
    server_specs: Vec<(String, String, Option<String>, Option<String>)>,
) -> PyResult<PyObject> {
    let servers: Vec<mcp::McpServerSpec> = server_specs
        .into_iter()
        .map(|(name, transport, command, url)| mcp::McpServerSpec {
            name,
            transport,
            command,
            url,
        })
        .collect();
    let (result, _names) = mcp::check_mcp_configs(&servers);
    dict_from_json(py, &result.to_dict())
}

/// Check MCP server availability from availability data.
/// `availability_data` = list of (name, transport, command_or_url, is_available, is_remote) tuples.
#[pyfunction]
fn check_mcp_availability_rust(
    py: Python<'_>,
    availability_data: Vec<(String, String, Option<String>, bool, bool)>,
) -> PyResult<PyObject> {
    let result = mcp::check_mcp_availability(&availability_data);
    dict_from_json(py, &result.to_dict())
}

/// Build the mcp_servers category result from pre-built check dicts.
#[pyfunction]
fn check_mcp_servers_from_results_rust(
    py: Python<'_>,
    check_dicts: Vec<Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    let checks = parse_check_dicts(py, &check_dicts)?;
    let cat = mcp::check_mcp_servers_from_results(checks);
    dict_from_json(py, &cat.to_dict())
}

// ── helpers ───────────────────────────────────────────────────

/// Convert a serde_json::Value into a Python object via json round-trip.
fn dict_from_json(py: Python<'_>, value: &serde_json::Value) -> PyResult<PyObject> {
    let json_str = serde_json::to_string(value)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
    let json_mod = py.import_bound("json")?;
    let result = json_mod.call_method("loads", (json_str,), None)?;
    Ok(result.into())
}

/// Parse a list of Python dicts into Rust CheckResult objects.
fn parse_check_dicts(py: Python<'_>, dicts: &[Bound<'_, PyDict>]) -> PyResult<Vec<CheckResult>> {
    let json_mod = py.import_bound("json")?;
    let mut checks = Vec::new();
    for d in dicts {
        let json_str: String = json_mod
            .call_method("dumps", (d.clone(),), None)?
            .extract()?;
        let val: serde_json::Value =
            serde_json::from_str(&json_str).unwrap_or(serde_json::Value::Null);
        checks.push(parse_check_result(&val));
    }
    Ok(checks)
}

/// Parse a single Python dict into a Rust CheckResult.
fn parse_single_check_dict(py: Python<'_>, d: &Bound<'_, PyDict>) -> PyResult<CheckResult> {
    let json_mod = py.import_bound("json")?;
    let json_str: String = json_mod
        .call_method("dumps", (d.clone(),), None)?
        .extract()?;
    let val: serde_json::Value = serde_json::from_str(&json_str).unwrap_or(serde_json::Value::Null);
    Ok(parse_check_result(&val))
}

/// Parse a serde_json::Value (from a check dict) into a CheckResult.
fn parse_check_result(val: &serde_json::Value) -> CheckResult {
    let empty = serde_json::Map::new();
    let obj = val.as_object().unwrap_or(&empty);
    let name = obj
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let status_str = obj.get("status").and_then(|v| v.as_str()).unwrap_or("ok");
    let status = CheckStatus::parse_str(status_str).unwrap_or(CheckStatus::Ok);
    let message = obj
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let details = obj
        .get("details")
        .cloned()
        .unwrap_or(serde_json::Value::Object(serde_json::Map::new()));
    CheckResult {
        name,
        status,
        message,
        details,
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(check_status_str, m)?)?;
    m.add_function(wrap_pyfunction!(check_status_severity, m)?)?;
    m.add_function(wrap_pyfunction!(aggregate_status_rust, m)?)?;
    m.add_function(wrap_pyfunction!(compare_status, m)?)?;
    m.add_function(wrap_pyfunction!(check_result_to_dict, m)?)?;
    m.add_function(wrap_pyfunction!(category_result_to_dict, m)?)?;
    m.add_function(wrap_pyfunction!(check_tool_deps_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_protocols_from_results_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_vector_stores_from_results_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_models_no_config_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_models_no_profile_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_models_ok_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_observability_from_results_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_provider_credentials_rust, m)?)?;
    m.add_function(wrap_pyfunction!(demote_inactive_provider_check_rust, m)?)?;
    m.add_function(wrap_pyfunction!(missing_active_provider_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_providers_from_results_rust, m)?)?;
    m.add_function(wrap_pyfunction!(provider_from_spec_rust, m)?)?;
    m.add_function(wrap_pyfunction!(unresolved_env_ref_rust, m)?)?;
    m.add_function(wrap_pyfunction!(active_provider_names_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_mcp_configs_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_mcp_availability_rust, m)?)?;
    m.add_function(wrap_pyfunction!(check_mcp_servers_from_results_rust, m)?)?;
    Ok(())
}
