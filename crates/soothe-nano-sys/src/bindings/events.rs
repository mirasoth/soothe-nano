//! PyO3 bindings for `soothe-nano-events`.

use pyo3::prelude::*;

/// Build a soothe protocol custom event chunk `((), "custom", data)`.
#[pyfunction]
fn custom_event(py: Python<'_>, data: &str) -> PyResult<PyObject> {
    let builtins = py.import_bound("json")?;
    let parsed: PyObject = builtins.call_method("loads", (data,), None)?.into();

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
