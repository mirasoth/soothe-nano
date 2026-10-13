//! PyO3 extension module — the bridge between Rust crates and Python.
//!
//! This is the **only** crate that depends on `pyo3`.
//! All other crates are pure Rust libraries.
//!
//! Python imports this as: `from soothe_nano._rust import ...`

// PyO3's `map_err(...)?` pattern triggers clippy::useless_conversion because
// `map_err` already yields `PyErr` and `?` does an identity `From<PyErr> for PyErr`.
#![allow(clippy::useless_conversion)]

use pyo3::prelude::*;

mod bindings;

/// Entry point for the `soothe_nano._rust` extension module.
///
/// The function name `_rust` must match the final path component of the
/// module name `soothe_nano._rust` so that PyO3 generates `PyInit__rust`.
#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    bindings::security::register(m)?;
    bindings::workspace::register(m)?;
    bindings::tokens::register(m)?;
    bindings::utils::register(m)?;
    bindings::filesystem::register(m)?;
    bindings::config::register(m)?;
    bindings::prompts::register(m)?;
    bindings::events::register(m)?;
    bindings::persist::register(m)?;
    bindings::skills::register(m)?;

    Ok(())
}
