//! PyO3 bindings for `soothe-nano-utils`.

use pyo3::prelude::*;

#[pyfunction]
fn generate_thread_id() -> String {
    soothe_nano_utils::generate_thread_id()
}

#[pyfunction]
fn repair_json(py: Python<'_>, raw: &str) -> PyResult<PyObject> {
    let result = py.allow_threads(|| soothe_nano_utils::repair_json(raw));
    match result {
        Some(value) => {
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

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(generate_thread_id, m)?)?;
    m.add_function(wrap_pyfunction!(repair_json, m)?)?;
    m.add_function(wrap_pyfunction!(text_preview, m)?)?;
    Ok(())
}
