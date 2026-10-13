//! PyO3 bindings for `soothe-nano-tokens`.
//!
//! Only the `count_tokens` function is exposed. The `TokenCounter` class
//! is omitted — `get_token_counter()` is never called from production
//! Python code (the function-level `count_tokens` is used instead).

use pyo3::prelude::*;

#[pyfunction]
#[pyo3(signature = (text, model = None, use_tiktoken = true))]
fn count_tokens(py: Python<'_>, text: &str, model: Option<&str>, use_tiktoken: bool) -> usize {
    if !use_tiktoken {
        return text.len() / 4;
    }
    py.allow_threads(|| {
        let counter = soothe_nano_tokens::TokenCounter::new();
        counter.count(text, model)
    })
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(count_tokens, m)?)?;
    Ok(())
}
