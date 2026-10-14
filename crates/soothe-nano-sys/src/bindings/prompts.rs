//! PyO3 bindings for `soothe-nano-prompts`.

use pyo3::prelude::*;
use soothe_nano_prompts::context_xml::FileInfo;
use std::path::Path;

/// Build the file-list context XML (pure Rust, no Python round-trip).
#[pyfunction]
fn build_context_xml(_py: Python<'_>, workspace: &str, files: Vec<(String, u64, usize)>) -> String {
    let file_infos: Vec<FileInfo> = files
        .into_iter()
        .map(|(path, size, lines)| FileInfo { path, size, lines })
        .collect();
    soothe_nano_prompts::build_context_xml(workspace, &file_infos)
}

/// Load project instructions from common locations (AGENTS.md, .soothe/AGENTS.md, CLAUDE.md).
#[pyfunction]
fn load_project_instructions(workspace: &str) -> Option<String> {
    soothe_nano_prompts::load_project_instructions(std::path::Path::new(workspace))
}

/// Build the ENVIRONMENT XML block. Round-trips into Python for `is_rg_available()`
/// and `get_knowledge_cutoff(model)`.
#[pyfunction]
fn build_environment_section(py: Python<'_>, model: &str) -> PyResult<String> {
    let platform_name = std::env::consts::OS;
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "unknown".to_string());
    let os_version = format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH);

    let is_rg = py
        .import_bound("soothe_deepagents.backends.grep_search")?
        .getattr("is_rg_available")?
        .call0()?
        .is_truthy()?;

    let cutoff_obj = py
        .import_bound("soothe_nano.config.models")?
        .getattr("get_knowledge_cutoff")?
        .call1((model,))?;
    let cutoff: String = cutoff_obj.extract()?;

    Ok(soothe_nano_prompts::build_environment_section(
        platform_name,
        &shell,
        &os_version,
        model,
        &cutoff,
        is_rg,
    ))
}

/// Build the WORKSPACE XML block (pure Rust filesystem I/O).
#[pyfunction]
#[pyo3(signature = (workspace_path, include_layout_preview=false, max_layout_entries=40, include_readme_excerpt=false, readme_max_chars=500))]
fn build_workspace_section(
    _py: Python<'_>,
    workspace_path: Option<String>,
    include_layout_preview: bool,
    max_layout_entries: usize,
    include_readme_excerpt: bool,
    readme_max_chars: usize,
) -> String {
    let path = match &workspace_path {
        Some(p) => Path::new(p),
        None => Path::new("."),
    };
    soothe_nano_prompts::build_workspace_section(
        path,
        include_layout_preview,
        max_layout_entries,
        include_readme_excerpt,
        readme_max_chars,
    )
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_context_xml, m)?)?;
    m.add_function(wrap_pyfunction!(load_project_instructions, m)?)?;
    m.add_function(wrap_pyfunction!(build_environment_section, m)?)?;
    m.add_function(wrap_pyfunction!(build_workspace_section, m)?)?;
    Ok(())
}
