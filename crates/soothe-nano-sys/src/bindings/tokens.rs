//! PyO3 bindings for `soothe-nano-tokens`.

use pyo3::prelude::*;
use soothe_nano_tokens::TokenCounter;

#[pyclass(name = "TokenCounter")]
pub struct PyTokenCounter {
    inner: TokenCounter,
}

#[pymethods]
impl PyTokenCounter {
    #[new]
    fn new() -> Self {
        Self {
            inner: TokenCounter::new(),
        }
    }

    #[pyo3(signature = (text, model = None))]
    fn count(&self, py: Python<'_>, text: &str, model: Option<&str>) -> usize {
        py.allow_threads(|| self.inner.count(text, model))
    }
}

#[pyfunction]
#[pyo3(signature = (text, model = None))]
fn count_tokens(py: Python<'_>, text: &str, model: Option<&str>) -> usize {
    py.allow_threads(|| soothe_nano_tokens::TokenCounter::count_default(text, model))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyTokenCounter>()?;
    m.add_function(wrap_pyfunction!(count_tokens, m)?)?;
    Ok(())
}
