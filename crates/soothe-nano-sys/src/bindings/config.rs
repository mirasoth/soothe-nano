//! PyO3 bindings for `soothe-nano-config`.
//!
//! Only `expand_env_vars` is exposed — it fully replaces the Python
//! `os.path.expandvars` equivalent. The `RustConfig` class is omitted
//! — `get_rust_config()` is never called from production Python code
//! (config loading uses the full Pydantic-based Python pipeline).

use pyo3::prelude::*;

#[pyfunction]
fn expand_env_vars(s: &str) -> String {
    soothe_nano_config::expand_env_vars(s)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(expand_env_vars, m)?)?;
    Ok(())
}
