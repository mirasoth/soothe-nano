//! PyO3 bindings for `soothe-nano-config`.

use pyo3::prelude::*;

#[pyfunction]
fn expand_env_vars(s: &str) -> String {
    soothe_nano_config::expand_env_vars(s)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(expand_env_vars, m)?)?;
    Ok(())
}
