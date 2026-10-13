//! PyO3 bindings for `soothe-nano-skills`.

use pyo3::prelude::*;
use soothe_nano_skills::{SkillBudget, SkillDiscovery};

#[pyclass(name = "SkillDiscovery")]
pub struct PySkillDiscovery {
    inner: SkillDiscovery,
}

#[pymethods]
impl PySkillDiscovery {
    #[new]
    fn new(roots: Vec<String>) -> Self {
        let roots: Vec<_> = roots.into_iter().map(std::path::PathBuf::from).collect();
        Self {
            inner: SkillDiscovery::new(roots),
        }
    }

    fn discover(&self, py: Python<'_>) -> Vec<(String, String)> {
        py.allow_threads(|| {
            self.inner
                .discover()
                .into_iter()
                .map(|e| (e.name, e.path))
                .collect()
        })
    }
}

#[pyclass(name = "SkillBudget")]
pub struct PySkillBudget {
    inner: SkillBudget,
}

#[pymethods]
impl PySkillBudget {
    #[new]
    fn new(initial: u32) -> Self {
        Self {
            inner: SkillBudget::new(initial),
        }
    }

    fn spend(&self, tokens: u32) -> bool {
        self.inner.spend(tokens)
    }

    #[getter]
    fn remaining(&self) -> u32 {
        self.inner.remaining()
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySkillDiscovery>()?;
    m.add_class::<PySkillBudget>()?;
    Ok(())
}
