//! PyO3 bindings for `soothe-nano-prompts`.

use pyo3::prelude::*;
use soothe_nano_prompts::context_xml::FileInfo;

#[pyfunction]
fn build_context_xml(_py: Python<'_>, workspace: &str, files: Vec<(String, u64, usize)>) -> String {
    let file_infos: Vec<FileInfo> = files
        .into_iter()
        .map(|(path, size, lines)| FileInfo { path, size, lines })
        .collect();
    soothe_nano_prompts::build_context_xml(workspace, &file_infos)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_context_xml, m)?)?;
    Ok(())
}
