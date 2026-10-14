//! PyO3 bindings for `soothe-nano-workspace`.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use soothe_nano_workspace::{
    resolve_workspace_for_stream, ResolvedWorkspace, WorkspacePolicy, WorkspaceSource,
};

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

// ── WorkspacePolicy ───────────────────────────────────────────

#[pyclass(name = "WorkspacePolicy")]
pub struct PyWorkspacePolicy {
    inner: WorkspacePolicy,
}

#[pymethods]
impl PyWorkspacePolicy {
    /// Create a policy rooted at `root` with defaults.
    #[new]
    fn new(root: &str) -> Self {
        Self {
            inner: WorkspacePolicy::new(root),
        }
    }

    /// Whether writes are permitted.
    #[getter]
    fn can_write(&self) -> bool {
        self.inner.can_write()
    }

    /// Workspace root as a string.
    #[getter]
    fn root(&self) -> String {
        self.inner.root.to_string_lossy().to_string()
    }

    /// Check if `path` is within the workspace root.
    fn is_within(&self, path: &str) -> bool {
        self.inner.is_within(std::path::Path::new(path))
    }
}

/// Construct a `WorkspacePolicy` rooted at `root`.
#[pyfunction]
fn workspace_policy_new(root: &str) -> PyWorkspacePolicy {
    PyWorkspacePolicy {
        inner: WorkspacePolicy::new(root),
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyResolvedWorkspace>()?;
    m.add_class::<PyWorkspacePolicy>()?;
    m.add_function(wrap_pyfunction!(resolve_workspace, m)?)?;
    m.add_function(wrap_pyfunction!(workspace_policy_new, m)?)?;
    Ok(())
}
