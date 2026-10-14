//! PyO3 bindings for `soothe-nano-events`.

use std::collections::HashMap;

use pyo3::prelude::*;
use soothe_nano_events::wire_protocol;

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

/// Return true for structurally valid curated `soothe.subagent.*` wire types.
#[pyfunction]
fn is_curated_subagent_wire_event_type(py: Python<'_>, event_type: &str) -> bool {
    py.allow_threads(|| wire_protocol::is_curated_subagent_wire_event_type(event_type))
}

/// Return the agent segment from `soothe.subagent.<agent>.…`, or `None`.
#[pyfunction]
fn parse_subagent_wire_agent(py: Python<'_>, event_type: &str) -> Option<String> {
    py.allow_threads(|| wire_protocol::parse_subagent_wire_agent(event_type))
}

/// Truncate a single wire string field.
#[pyfunction]
#[pyo3(signature = (value, max_len))]
fn truncate_wire_str(py: Python<'_>, value: &str, max_len: usize) -> String {
    py.allow_threads(|| wire_protocol::truncate_wire_str(value, max_len))
}

/// Copy the dict and truncate known string fields for wire safety.
///
/// Accepts a dict with mixed value types; only string values for known
/// fields are truncated. Non-string values and unknown keys pass through unchanged.
#[pyfunction]
fn clip_wire_event_payload(py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<PyObject> {
    // Extract string-valued entries into a HashMap; collect non-string values separately.
    let dict = data.downcast::<pyo3::types::PyDict>()?;
    let mut string_map: HashMap<String, String> = HashMap::new();
    let mut non_string: Vec<(String, PyObject)> = Vec::new();

    for (k, v) in dict.iter() {
        let key_str: String = k.extract()?;
        if let Ok(s) = v.extract::<String>() {
            string_map.insert(key_str, s);
        } else {
            non_string.push((key_str, v.to_object(py)));
        }
    }

    let clipped = py.allow_threads(|| wire_protocol::clip_wire_event_payload(&string_map));

    // Reassemble into a dict.
    let out = pyo3::types::PyDict::new_bound(py);
    for (k, v) in &clipped {
        out.set_item(k, v)?;
    }
    for (k, v) in non_string {
        out.set_item(k, v)?;
    }
    Ok(out.into())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(custom_event, m)?)?;
    m.add_function(wrap_pyfunction!(is_curated_subagent_wire_event_type, m)?)?;
    m.add_function(wrap_pyfunction!(parse_subagent_wire_agent, m)?)?;
    m.add_function(wrap_pyfunction!(truncate_wire_str, m)?)?;
    m.add_function(wrap_pyfunction!(clip_wire_event_payload, m)?)?;

    // Event type constants
    m.add("MODEL_FALLBACK", "soothe.cognition.llm.model_fallback")?;
    m.add(
        "LLM_PERSISTENT_RETRY",
        "soothe.cognition.llm.persistent_retry",
    )?;
    m.add("STREAM_END", "soothe.stream.end")?;

    Ok(())
}
