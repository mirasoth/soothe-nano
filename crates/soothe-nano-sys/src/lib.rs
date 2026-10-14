//! PyO3 extension module — the bridge between Rust crates and Python.

// PyO3's `map_err(...)?` pattern triggers clippy::useless_conversion because
// `map_err` already yields `PyErr` and `?` does an identity `From<PyErr> for PyErr`.
#![allow(clippy::useless_conversion)]

use pyo3::prelude::*;

mod bindings;

/// Entry point for the `soothe_nano._rust` extension module.
#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    bindings::core::register(m)?;
    bindings::workspace::register(m)?;
    bindings::tokens::register(m)?;
    bindings::utils::register(m)?;
    bindings::config::register(m)?;
    bindings::prompts::register(m)?;
    bindings::events::register(m)?;
    bindings::security::register(m)?;
    bindings::persist::register(m)?;
    bindings::filesystem::register(m)?;
    bindings::skills::register(m)?;
    bindings::protocols::register(m)?;
    bindings::diagnose::register(m)?;
    bindings::subagents::register(m)?;

    Ok(())
}
