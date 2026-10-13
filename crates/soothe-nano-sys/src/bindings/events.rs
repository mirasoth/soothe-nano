//! PyO3 bindings for `soothe-nano-events`.
//!
//! Only `custom_event` is exposed — it's the only event function called from
//! production Python. Event constructor bindings (stream_end_event, etc.) were
//! removed because they were never called from production code.

use pyo3::prelude::*;

/// Build a soothe protocol custom event chunk.
///
/// Mirrors the Python `custom_event(data)` which returns the tuple
/// `((), "custom", data)`.
#[pyfunction]
fn custom_event(py: Python<'_>, data: &str) -> PyResult<PyObject> {
    // Parse JSON string into a Python object.
    let builtins = py.import_bound("json")?;
    let parsed: PyObject = builtins.call_method("loads", (data,), None)?.into();

    // Build the tuple ((), "custom", parsed_data) to match the Python API.
    let empty_tuple = pyo3::types::PyTuple::empty_bound(py);
    let elements: Vec<PyObject> = vec![empty_tuple.to_object(py), "custom".to_object(py), parsed];
    let py_tuple = pyo3::types::PyTuple::new_bound(py, &elements);
    Ok(py_tuple.into())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(custom_event, m)?)?;

    // Event type constants (matching Python's events/catalog.py)
    m.add("MODEL_FALLBACK", "soothe.cognition.llm.model_fallback")?;
    m.add(
        "LLM_PERSISTENT_RETRY",
        "soothe.cognition.llm.persistent_retry",
    )?;
    m.add("STREAM_END", "soothe.stream.end")?;

    Ok(())
}
