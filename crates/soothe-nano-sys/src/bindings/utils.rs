//! PyO3 bindings for `soothe-nano-utils`.
//!
//! Only stateless functions that fully replace their Python counterparts
//! are exposed. The `CircuitBreaker` class is omitted — the Python
//! implementation owns the full state machine (decorators, async support,
//! logging) and the Rust class would only be a parallel, never-read copy.

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
            // Enforce dict-only contract: if the root is not a JSON object,
            // return None so the Python fallback can raise TypeError/ValueError.
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
        // Encode spaces to %20 (matching Python's behavior).
        let sanitized_input = raw.trim().replace(' ', "%20");

        // Check for invalid characters (matching Python's behavior).
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
                // Map Rust error messages to match Python's error phrasing.
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

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(generate_thread_id, m)?)?;
    m.add_function(wrap_pyfunction!(repair_json, m)?)?;
    m.add_function(wrap_pyfunction!(text_preview, m)?)?;
    m.add_function(wrap_pyfunction!(preview_full, m)?)?;
    m.add_function(wrap_pyfunction!(validate_url_py, m)?)?;
    m.add_function(wrap_pyfunction!(truncate_output, m)?)?;
    Ok(())
}
