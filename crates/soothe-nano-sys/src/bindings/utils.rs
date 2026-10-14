//! PyO3 bindings for `soothe-nano-utils`.

use std::time::Duration;

use pyo3::prelude::*;
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
    Ok(())
}
