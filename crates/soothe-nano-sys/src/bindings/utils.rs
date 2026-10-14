//! PyO3 bindings for `soothe-nano-utils`.

use std::time::Duration;

use pyo3::prelude::*;
use pyo3::types::PyType;
use soothe_nano_utils::validate_url;

#[pyfunction]
fn generate_thread_id() -> String {
    soothe_nano_utils::generate_thread_id()
}

#[pyfunction]
fn repair_json(py: Python<'_>, raw: &str) -> PyResult<PyObject> {
    let result = py.allow_threads(|| soothe_nano_utils::repair_json(raw));
    match result {
        Some(value) => {
            // Enforce dict-only contract.
            if !value.is_object() {
                return Ok(py.None());
            }
            let json_str = serde_json::to_string(&value)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let json_mod = py.import_bound("json")?;
            let result = json_mod.call_method("loads", (json_str,), None)?;
            Ok(result.into())
        }
        None => Ok(py.None()),
    }
}

#[pyfunction]
#[pyo3(signature = (text, max_chars))]
fn text_preview(py: Python<'_>, text: &str, max_chars: usize) -> String {
    py.allow_threads(|| soothe_nano_utils::text_preview(text, max_chars))
}

#[pyfunction]
#[pyo3(signature = (text, mode="chars", first=None, last=None, marker=None))]
fn preview_full(
    py: Python<'_>,
    text: &str,
    mode: &str,
    first: Option<usize>,
    last: Option<usize>,
    marker: Option<&str>,
) -> String {
    py.allow_threads(|| soothe_nano_utils::preview_full(text, mode, first, last, marker))
}

#[pyfunction]
#[pyo3(signature = (raw))]
fn validate_url_py(py: Python<'_>, raw: &str) -> PyResult<(String, Option<String>)> {
    py.allow_threads(|| {
        let sanitized_input = raw.trim().replace(' ', "%20");

        if sanitized_input.contains('<')
            || sanitized_input.contains('>')
            || sanitized_input.contains('"')
            || sanitized_input.contains('\'')
        {
            return Ok((
                sanitized_input.clone(),
                Some(format!(
                    "URL contains invalid characters: {sanitized_input}"
                )),
            ));
        }

        match validate_url(&sanitized_input) {
            Ok(u) => Ok((u.to_url_string(), None)),
            Err(e) => {
                let msg = match &e {
                    soothe_nano_utils::UrlValidationError::Empty => {
                        "URL cannot be empty".to_string()
                    }
                    soothe_nano_utils::UrlValidationError::InvalidScheme(_) => {
                        format!("URL missing scheme (http:// or https://): {sanitized_input}")
                    }
                    soothe_nano_utils::UrlValidationError::MissingHost => {
                        format!("URL missing domain: {sanitized_input}")
                    }
                    soothe_nano_utils::UrlValidationError::ParseError(_) => {
                        format!("URL missing scheme (http:// or https://): {sanitized_input}")
                    }
                };
                Ok((sanitized_input, Some(msg)))
            }
        }
    })
}

#[pyfunction]
#[pyo3(signature = (output, max_bytes))]
fn truncate_output(py: Python<'_>, output: &str, max_bytes: usize) -> String {
    py.allow_threads(|| soothe_nano_utils::output_capture::truncate_output(output, max_bytes))
}

#[pyfunction]
#[pyo3(signature = (error_type, error_msg))]
fn format_cli_error(py: Python<'_>, error_type: &str, error_msg: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::format_cli_error(error_type, error_msg))
}

#[pyfunction]
#[pyo3(signature = (text, max_length))]
fn log_preview(py: Python<'_>, text: &str, max_length: usize) -> String {
    py.allow_threads(|| soothe_nano_utils::log_preview(text, max_length))
}

#[pyfunction]
#[pyo3(signature = (path, base_dir=None))]
fn convert_and_abbreviate_path(py: Python<'_>, path: &str, base_dir: Option<&str>) -> String {
    py.allow_threads(|| soothe_nano_utils::convert_and_abbreviate_path(path, base_dir))
}

// ── Logging formatter helpers ─────────────────────────────────

#[pyfunction]
fn short_level_letter(py: Python<'_>, levelno: i32) -> String {
    py.allow_threads(|| soothe_nano_utils::logging_fmt::short_level_letter(levelno).to_string())
}

#[pyfunction]
fn abbreviate_logger_name(py: Python<'_>, name: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::logging_fmt::abbreviate_logger_name(name))
}

// ── Prompt clock ──────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (tz=None))]
fn prompt_clock_now_local(py: Python<'_>, tz: Option<String>) -> String {
    py.allow_threads(|| soothe_nano_utils::prompt_clock::now_local(tz.as_deref()))
}

#[pyfunction]
#[pyo3(signature = (ts, tz=None))]
fn prompt_clock_local_date_str(py: Python<'_>, ts: f64, tz: Option<String>) -> String {
    py.allow_threads(|| soothe_nano_utils::prompt_clock::local_date_str(ts, tz.as_deref()))
}

#[pyfunction]
#[pyo3(signature = (ts, tz=None))]
fn prompt_clock_local_time_str(py: Python<'_>, ts: f64, tz: Option<String>) -> String {
    py.allow_threads(|| soothe_nano_utils::prompt_clock::local_time_str(ts, tz.as_deref()))
}

#[pyfunction]
#[pyo3(signature = (ts, tz=None))]
fn prompt_clock_local_timestamp_iso(py: Python<'_>, ts: f64, tz: Option<String>) -> String {
    py.allow_threads(|| soothe_nano_utils::prompt_clock::local_timestamp_iso(ts, tz.as_deref()))
}

#[pyfunction]
#[pyo3(signature = (tz=None))]
fn prompt_clock_local_timezone_label(py: Python<'_>, tz: Option<String>) -> String {
    py.allow_threads(|| soothe_nano_utils::prompt_clock::local_timezone_label(tz.as_deref()))
}

#[pyfunction]
#[pyo3(signature = (tz=None))]
fn prompt_clock_prompt_datetime_context(py: Python<'_>, tz: Option<String>) -> String {
    py.allow_threads(|| soothe_nano_utils::prompt_clock::prompt_datetime_context(tz.as_deref()))
}

#[pyfunction]
#[pyo3(signature = (ts, tz=None))]
fn prompt_clock_format_friendly_local_date(py: Python<'_>, ts: f64, tz: Option<String>) -> String {
    py.allow_threads(|| {
        soothe_nano_utils::prompt_clock::format_friendly_local_date(ts, tz.as_deref())
    })
}

// ── CircuitBreaker ───────────────────────────────────────────

#[pyclass(name = "CircuitBreaker")]
pub struct PyCircuitBreaker {
    inner: soothe_nano_utils::CircuitBreaker,
}

#[pymethods]
impl PyCircuitBreaker {
    #[new]
    #[pyo3(signature = (failure_threshold=5, timeout_seconds=60.0))]
    fn new(failure_threshold: u64, timeout_seconds: f64) -> Self {
        Self {
            inner: soothe_nano_utils::CircuitBreaker::new(
                failure_threshold,
                Duration::from_secs_f64(timeout_seconds),
            ),
        }
    }

    /// Current state: "closed", "open", or "half_open".
    fn state(&self) -> String {
        use soothe_nano_utils::CircuitState;
        match self.inner.state() {
            CircuitState::Closed => "closed",
            CircuitState::Open => "open",
            CircuitState::HalfOpen => "half_open",
        }
        .to_string()
    }

    /// Whether the circuit is open.
    fn is_open(&self) -> bool {
        use soothe_nano_utils::CircuitState;
        self.inner.state() == CircuitState::Open
    }

    /// Record a successful call (resets failure count).
    fn record_success(&self) {
        self.inner.record_success();
    }

    /// Record a failed call (increments failure count, may open the circuit).
    fn record_failure(&self) {
        self.inner.record_failure();
    }

    /// True if a request should be allowed (closed or half-open).
    fn allow_request(&self) -> bool {
        self.inner.allow_request()
    }
}

// ── Task namespace (unified tool_call_id parsing) ───────────

/// Parsed components of a unified tool_call_id.
///
/// Fields are read-only; construct via `parse_unified_tool_call_id` or the
/// `empty()` classmethod.
#[pyclass(name = "ParsedUnifiedToolCallId", module = "soothe_nano._rust")]
#[derive(Clone)]
pub struct PyParsedUnifiedToolCallId {
    inner: soothe_nano_utils::ParsedUnifiedToolCallId,
}

#[pymethods]
impl PyParsedUnifiedToolCallId {
    /// Non-unified or empty id sentinel. `tool_info` defaults to empty.
    #[classmethod]
    #[pyo3(signature = (tool_info=""))]
    fn empty(_cls: &Bound<'_, PyType>, tool_info: &str) -> Self {
        Self {
            inner: soothe_nano_utils::ParsedUnifiedToolCallId::empty_with_tool_info(tool_info),
        }
    }

    /// Execute step id (canonical hyphen form, e.g. ``GHT-01``).
    #[getter]
    fn step_id(&self) -> String {
        self.inner.step_id.clone()
    }

    /// Type code: ``"s"``, ``"t"``, or ``""`` for non-unified ids.
    #[getter]
    fn type_code(&self) -> String {
        self.inner.type_code.clone()
    }

    /// Task index for ``t{N}`` type ids; ``None`` for step-level or non-unified.
    #[getter]
    fn task_idx(&self) -> Option<i32> {
        self.inner.task_idx
    }

    /// Tool info fragment (everything after the type segment, joined by ``":"``).
    #[getter]
    fn tool_info(&self) -> String {
        self.inner.tool_info.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "ParsedUnifiedToolCallId(step_id={:?}, type_code={:?}, task_idx={:?}, tool_info={:?})",
            self.inner.step_id, self.inner.type_code, self.inner.task_idx, self.inner.tool_info
        )
    }

    /// Tuple-style positional access: 0=step_id, 1=type_code, 2=task_idx, 3=tool_info.
    fn __getitem__(&self, index: usize) -> PyResult<PyObject> {
        Python::with_gil(|py| match index {
            0 => Ok(self.inner.step_id.clone().into_py(py)),
            1 => Ok(self.inner.type_code.clone().into_py(py)),
            2 => Ok(self.inner.task_idx.into_py(py)),
            3 => Ok(self.inner.tool_info.clone().into_py(py)),
            _ => Err(pyo3::exceptions::PyIndexError::new_err(format!(
                "tuple index {index} out of range"
            ))),
        })
    }
}

#[pyfunction]
fn step_id_to_unified_fragment(py: Python<'_>, step_id: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::task_namespace::step_id_to_unified_fragment(step_id))
}

#[pyfunction]
fn step_id_from_unified_fragment(py: Python<'_>, fragment: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::task_namespace::step_id_from_unified_fragment(fragment))
}

#[pyfunction]
fn is_wire_step_fragment(py: Python<'_>, fragment: &str) -> bool {
    py.allow_threads(|| soothe_nano_utils::task_namespace::is_wire_step_fragment(fragment))
}

#[pyfunction]
fn provider_tool_fragment(py: Python<'_>, tid: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::task_namespace::provider_tool_fragment(tid))
}

#[pyfunction]
fn tool_info_from_unified_parts(py: Python<'_>, parts: Vec<String>) -> String {
    py.allow_threads(|| {
        let refs: Vec<&str> = parts.iter().map(|s| s.as_str()).collect();
        soothe_nano_utils::task_namespace::tool_info_from_unified_parts(&refs)
    })
}

#[pyfunction]
fn format_unified_tool_call_id(
    py: Python<'_>,
    step_id: &str,
    type_part: &str,
    tool_fragment: &str,
) -> String {
    py.allow_threads(|| {
        soothe_nano_utils::task_namespace::format_unified_tool_call_id(
            step_id,
            type_part,
            tool_fragment,
        )
    })
}

#[pyfunction]
fn parse_unified_tool_call_id(py: Python<'_>, tool_call_id: &str) -> PyParsedUnifiedToolCallId {
    let parsed = py.allow_threads(|| {
        soothe_nano_utils::task_namespace::parse_unified_tool_call_id(tool_call_id)
    });
    PyParsedUnifiedToolCallId { inner: parsed }
}

#[pyfunction]
fn is_unified_tool_call_id(py: Python<'_>, tool_call_id: &str) -> bool {
    py.allow_threads(|| soothe_nano_utils::task_namespace::is_unified_tool_call_id(tool_call_id))
}

#[pyfunction]
fn shorten_tool_call_id(py: Python<'_>, raw_tid: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::task_namespace::shorten_tool_call_id(raw_tid))
}

// ── Content character counting ────────────────────────────────

#[pyfunction]
#[pyo3(signature = (value=None))]
fn coerce_total_tokens_used_rust(py: Python<'_>, value: Option<i64>) -> i64 {
    py.allow_threads(|| soothe_nano_utils::coerce_total_tokens_used(value))
}

#[pyfunction]
fn count_str_chars_rust(py: Python<'_>, s: &str) -> usize {
    py.allow_threads(|| soothe_nano_utils::count_str_chars(s))
}

// ── Error simplification ──────────────────────────────────────

#[pyfunction]
fn is_unexpected_keyword_error_rust(py: Python<'_>, error_msg: &str) -> bool {
    py.allow_threads(|| soothe_nano_utils::is_unexpected_keyword_error(error_msg))
}

#[pyfunction]
fn unexpected_kwarg_name_rust(py: Python<'_>, error_msg: &str) -> Option<String> {
    py.allow_threads(|| soothe_nano_utils::unexpected_kwarg_name(error_msg))
}

#[pyfunction]
fn missing_required_count_rust(py: Python<'_>, error_msg: &str) -> Option<String> {
    py.allow_threads(|| soothe_nano_utils::missing_required_count(error_msg))
}

#[pyfunction]
fn is_llm_argument_error_rust(py: Python<'_>, error_type: &str, error_msg: &str) -> bool {
    py.allow_threads(|| soothe_nano_utils::is_llm_argument_error(error_type, error_msg))
}

#[pyfunction]
#[pyo3(signature = (error_type, error_msg, status=None))]
fn is_warning_level_error_rust(
    py: Python<'_>,
    error_type: &str,
    error_msg: &str,
    status: Option<i32>,
) -> bool {
    py.allow_threads(|| soothe_nano_utils::is_warning_level_error(error_type, error_msg, status))
}

#[pyfunction]
#[pyo3(signature = (error_type, error_msg, status=None))]
fn simplify_error_rust(
    py: Python<'_>,
    error_type: &str,
    error_msg: &str,
    status: Option<i32>,
) -> String {
    py.allow_threads(|| soothe_nano_utils::simplify_error(error_type, error_msg, status))
}

// ── Chrome/Electron process detection ─────────────────────────

#[pyfunction]
fn exe_name_is_chrome_like_rust(py: Python<'_>, exe_name: &str) -> bool {
    py.allow_threads(|| soothe_nano_utils::exe_name_is_chrome_like(exe_name))
}

#[pyfunction]
fn extract_exe_path_from_args_rust(py: Python<'_>, args: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::extract_exe_path_from_args(args))
}

#[pyfunction]
fn is_chrome_like_process_rust(py: Python<'_>, args: &str, exe_name: &str) -> bool {
    py.allow_threads(|| soothe_nano_utils::is_chrome_like_process(args, exe_name))
}

#[pyfunction]
fn extract_user_data_dir_rust(py: Python<'_>, args: &str) -> Option<String> {
    py.allow_threads(|| soothe_nano_utils::extract_user_data_dir(args))
}

#[pyfunction]
fn extract_debug_port_rust(py: Python<'_>, args: &str) -> Option<String> {
    py.allow_threads(|| soothe_nano_utils::extract_debug_port(args))
}

#[pyfunction]
fn parse_singleton_owner_pid_rust(py: Python<'_>, symlink_target: &str) -> Option<i64> {
    py.allow_threads(|| soothe_nano_utils::parse_singleton_owner_pid(symlink_target))
}

// ── Event format compact ──────────────────────────────────────

/// Format an event dict into a compact, readable string.
///
/// Accepts a Python dict; extracts the `type` field and known key fields,
/// truncating long string values. Non-string values pass through as-is.
#[pyfunction]
fn format_event_compact_rust(py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<String> {
    let dict = data.downcast::<pyo3::types::PyDict>()?;
    let mut entries: Vec<(String, String, bool)> = Vec::new();
    for (k, v) in dict.iter() {
        let key_str: String = k.extract()?;
        if let Ok(s) = v.extract::<String>() {
            entries.push((key_str, s, true));
        } else {
            // Non-string value: format via Python str() for fidelity.
            let py_str = v.str()?;
            entries.push((key_str, py_str.to_string(), false));
        }
    }
    Ok(py.allow_threads(|| soothe_nano_utils::format_event_compact(&entries)))
}

// ── Langfuse display-name helpers ─────────────────────────────

#[pyfunction]
#[pyo3(signature = (trace_name=None))]
fn loop_graph_langfuse_run_display_name_rust(py: Python<'_>, trace_name: Option<&str>) -> String {
    py.allow_threads(|| soothe_nano_utils::loop_graph_langfuse_run_display_name(trace_name))
}

#[pyfunction]
#[pyo3(signature = (trace_name=None))]
fn execute_step_langfuse_run_display_name_rust(py: Python<'_>, trace_name: Option<&str>) -> String {
    py.allow_threads(|| soothe_nano_utils::execute_step_langfuse_run_display_name(trace_name))
}

// ── Environment variable resolution ───────────────────────────

#[pyfunction]
#[pyo3(signature = (value=None))]
fn resolve_str_rust(py: Python<'_>, value: Option<&str>) -> Option<String> {
    py.allow_threads(|| soothe_nano_utils::resolve_str_os(value))
}

#[pyfunction]
fn resolve_env_vars_rust(py: Python<'_>, s: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::resolve_env_vars_os(s))
}

#[pyfunction]
fn normalize_tags_rust(py: Python<'_>, tags: Vec<String>) -> Option<Vec<String>> {
    py.allow_threads(|| soothe_nano_utils::normalize_tags(Some(&tags)))
}

// ── Thread ID log suffix ──────────────────────────────────────

#[pyfunction]
fn short_thread_id_for_log_rust(py: Python<'_>, thread_id: &str) -> String {
    py.allow_threads(|| soothe_nano_utils::short_thread_id_for_log(thread_id))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(generate_thread_id, m)?)?;
    m.add_function(wrap_pyfunction!(repair_json, m)?)?;
    m.add_function(wrap_pyfunction!(text_preview, m)?)?;
    m.add_function(wrap_pyfunction!(preview_full, m)?)?;
    m.add_function(wrap_pyfunction!(validate_url_py, m)?)?;
    m.add_function(wrap_pyfunction!(truncate_output, m)?)?;
    m.add_function(wrap_pyfunction!(format_cli_error, m)?)?;
    m.add_function(wrap_pyfunction!(log_preview, m)?)?;
    m.add_function(wrap_pyfunction!(convert_and_abbreviate_path, m)?)?;
    m.add_function(wrap_pyfunction!(short_level_letter, m)?)?;
    m.add_function(wrap_pyfunction!(abbreviate_logger_name, m)?)?;
    m.add_function(wrap_pyfunction!(prompt_clock_now_local, m)?)?;
    m.add_function(wrap_pyfunction!(prompt_clock_local_date_str, m)?)?;
    m.add_function(wrap_pyfunction!(prompt_clock_local_time_str, m)?)?;
    m.add_function(wrap_pyfunction!(prompt_clock_local_timestamp_iso, m)?)?;
    m.add_function(wrap_pyfunction!(prompt_clock_local_timezone_label, m)?)?;
    m.add_function(wrap_pyfunction!(prompt_clock_prompt_datetime_context, m)?)?;
    m.add_function(wrap_pyfunction!(
        prompt_clock_format_friendly_local_date,
        m
    )?)?;
    m.add_class::<PyCircuitBreaker>()?;
    // Task namespace — unified tool_call_id parsing.
    m.add_class::<PyParsedUnifiedToolCallId>()?;
    m.add_function(wrap_pyfunction!(step_id_to_unified_fragment, m)?)?;
    m.add_function(wrap_pyfunction!(step_id_from_unified_fragment, m)?)?;
    m.add_function(wrap_pyfunction!(is_wire_step_fragment, m)?)?;
    m.add_function(wrap_pyfunction!(provider_tool_fragment, m)?)?;
    m.add_function(wrap_pyfunction!(tool_info_from_unified_parts, m)?)?;
    m.add_function(wrap_pyfunction!(format_unified_tool_call_id, m)?)?;
    m.add_function(wrap_pyfunction!(parse_unified_tool_call_id, m)?)?;
    m.add_function(wrap_pyfunction!(is_unified_tool_call_id, m)?)?;
    m.add_function(wrap_pyfunction!(shorten_tool_call_id, m)?)?;
    // Content char counting + token coercion.
    m.add_function(wrap_pyfunction!(coerce_total_tokens_used_rust, m)?)?;
    m.add_function(wrap_pyfunction!(count_str_chars_rust, m)?)?;
    // Error simplification helpers.
    m.add_function(wrap_pyfunction!(is_unexpected_keyword_error_rust, m)?)?;
    m.add_function(wrap_pyfunction!(unexpected_kwarg_name_rust, m)?)?;
    m.add_function(wrap_pyfunction!(missing_required_count_rust, m)?)?;
    m.add_function(wrap_pyfunction!(is_llm_argument_error_rust, m)?)?;
    m.add_function(wrap_pyfunction!(is_warning_level_error_rust, m)?)?;
    m.add_function(wrap_pyfunction!(simplify_error_rust, m)?)?;
    // Chrome/Electron process detection.
    m.add_function(wrap_pyfunction!(exe_name_is_chrome_like_rust, m)?)?;
    m.add_function(wrap_pyfunction!(extract_exe_path_from_args_rust, m)?)?;
    m.add_function(wrap_pyfunction!(is_chrome_like_process_rust, m)?)?;
    m.add_function(wrap_pyfunction!(extract_user_data_dir_rust, m)?)?;
    m.add_function(wrap_pyfunction!(extract_debug_port_rust, m)?)?;
    m.add_function(wrap_pyfunction!(parse_singleton_owner_pid_rust, m)?)?;
    // Event format compact.
    m.add_function(wrap_pyfunction!(format_event_compact_rust, m)?)?;
    // Langfuse display-name helpers.
    m.add_function(wrap_pyfunction!(
        loop_graph_langfuse_run_display_name_rust,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(
        execute_step_langfuse_run_display_name_rust,
        m
    )?)?;
    // Environment variable resolution.
    m.add_function(wrap_pyfunction!(resolve_str_rust, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_env_vars_rust, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_tags_rust, m)?)?;
    // Thread ID log suffix.
    m.add_function(wrap_pyfunction!(short_thread_id_for_log_rust, m)?)?;
    Ok(())
}
