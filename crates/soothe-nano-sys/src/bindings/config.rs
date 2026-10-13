//! PyO3 bindings for `soothe-nano-config`.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use soothe_nano_config::SootheConfig;

#[pyclass(name = "RustConfig")]
pub struct PySootheConfig {
    inner: SootheConfig,
}

#[pymethods]
impl PySootheConfig {
    #[staticmethod]
    fn from_yaml(path: &str) -> PyResult<Self> {
        let config = SootheConfig::from_yaml_file(std::path::Path::new(path))
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        Ok(Self { inner: config })
    }

    fn resolve_model(&self, role: &str) -> Option<String> {
        self.inner.resolve_model(role).map(|s| s.to_string())
    }

    #[getter]
    fn agent_model(&self) -> &str {
        &self.inner.agent.model
    }
}

#[pyfunction]
fn expand_env_vars(s: &str) -> String {
    soothe_nano_config::expand_env_vars(s)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySootheConfig>()?;
    m.add_function(wrap_pyfunction!(expand_env_vars, m)?)?;
    Ok(())
}
