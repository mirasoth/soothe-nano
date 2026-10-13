//! PyO3 bindings for `soothe-nano-workspace`.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use soothe_nano_workspace::{resolve_workspace_for_stream, ResolvedWorkspace, WorkspaceSource};

#[pyclass(name = "ResolvedWorkspace")]
pub struct PyResolvedWorkspace {
    #[pyo3(get)]
    pub path: String,
    #[pyo3(get)]
    pub source: String,
}

impl From<ResolvedWorkspace> for PyResolvedWorkspace {
    fn from(r: ResolvedWorkspace) -> Self {
        let source = match r.source {
            WorkspaceSource::Explicit => "explicit",
            WorkspaceSource::Thread => "thread",
            WorkspaceSource::DaemonDefault => "daemon_default",
            WorkspaceSource::Cwd => "cwd",
            WorkspaceSource::ToolExecution => "tool_execution",
        };
        Self {
            path: r.path.to_string_lossy().to_string(),
            source: source.to_string(),
        }
    }
}

#[pyfunction]
#[pyo3(signature = (explicit=None, thread_workspace=None, installation_default=None))]
fn resolve_workspace(
    explicit: Option<String>,
    thread_workspace: Option<String>,
    installation_default: Option<String>,
) -> PyResult<PyResolvedWorkspace> {
    let result = resolve_workspace_for_stream(
        explicit.as_deref(),
        thread_workspace.as_deref(),
        installation_default.as_deref(),
    )
    .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    Ok(result.into())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyResolvedWorkspace>()?;
    m.add_function(wrap_pyfunction!(resolve_workspace, m)?)?;
    Ok(())
}
