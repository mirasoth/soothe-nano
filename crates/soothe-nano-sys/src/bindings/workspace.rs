//! PyO3 bindings for `soothe-nano-workspace`.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use soothe_nano_workspace::{
    db_path_for_thread, default_db_path, join_workspace_normalized_path,
    resolve_checkpoints_db_path, resolve_context_db_path, resolve_cron_db_path,
    resolve_databases_dir, resolve_display_db_path, resolve_identity_db_path,
    resolve_metadata_db_path, resolve_persist_db_path, resolve_sqlite_db_path,
    resolve_vectors_db_path, resolve_workspace_for_stream, should_use_virtual_path_resolution,
    soothe_data_dir, soothe_home, ResolvedWorkspace, WorkspacePolicy, WorkspaceSource,
    SQLITE_DATABASES_SUBDIR, WORKSPACE_BACKUP_DIR,
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

// ── Free path functions ────────────────────────────────────────

/// Join a workspace root with a relative path, rejecting escapes.
///
/// Returns the canonical absolute path, or raises `RuntimeError` on
/// path-escape or invalid input.
#[pyfunction]
fn join_workspace_normalized_path_py(workspace: &str, relative: &str) -> PyResult<String> {
    let joined = join_workspace_normalized_path(std::path::Path::new(workspace), relative)
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    Ok(joined.to_string_lossy().to_string())
}

/// Resolve the `SOOTHE_HOME` directory (env var > `~/.soothe`).
#[pyfunction]
fn soothe_home_py() -> String {
    soothe_home().to_string_lossy().to_string()
}

/// Path to the default (non-thread-scoped) SQLite DB.
#[pyfunction]
fn default_db_path_py() -> String {
    default_db_path().to_string_lossy().to_string()
}

/// Path to a thread-scoped SQLite DB file.
#[pyfunction]
fn db_path_for_thread_py(thread_id: &str) -> String {
    db_path_for_thread(thread_id).to_string_lossy().to_string()
}

// ── Virtual path resolution ────────────────────────────────────

/// True when a leading-`/` path should use virtual sandbox resolution.
#[pyfunction]
fn should_use_virtual_path_resolution_py(file_path: &str, workspace_root: &str) -> bool {
    should_use_virtual_path_resolution(file_path, std::path::Path::new(workspace_root))
}

// ── SQLite data-dir / db-path helpers ──────────────────────────

/// Resolve `$SOOTHE_DATA_DIR` (env var > `$SOOTHE_HOME/data`).
#[pyfunction]
fn soothe_data_dir_py() -> String {
    soothe_data_dir().to_string_lossy().to_string()
}

/// Return `$SOOTHE_DATA_DIR/databases` (creates nothing).
#[pyfunction]
fn resolve_databases_dir_py() -> String {
    resolve_databases_dir().to_string_lossy().to_string()
}

/// Return `$SOOTHE_DATA_DIR/databases/{purpose}.db`.
#[pyfunction]
fn resolve_sqlite_db_path_py(purpose: &str) -> String {
    resolve_sqlite_db_path(purpose)
        .to_string_lossy()
        .to_string()
}

/// StrangeLoop / loop checkpoints SQLite path.
#[pyfunction]
fn resolve_checkpoints_db_path_py() -> String {
    resolve_checkpoints_db_path().to_string_lossy().to_string()
}

/// Context Engine SQLite path.
#[pyfunction]
fn resolve_context_db_path_py() -> String {
    resolve_context_db_path().to_string_lossy().to_string()
}

/// Display card ledger SQLite path.
#[pyfunction]
fn resolve_display_db_path_py() -> String {
    resolve_display_db_path().to_string_lossy().to_string()
}

/// Cron job store SQLite path.
#[pyfunction]
fn resolve_cron_db_path_py() -> String {
    resolve_cron_db_path().to_string_lossy().to_string()
}

/// Identity service SQLite path.
#[pyfunction]
fn resolve_identity_db_path_py() -> String {
    resolve_identity_db_path().to_string_lossy().to_string()
}

/// ThreadInfo / durability metadata SQLite path.
#[pyfunction]
fn resolve_metadata_db_path_py() -> String {
    resolve_metadata_db_path().to_string_lossy().to_string()
}

/// Persist KV SQLite path.
#[pyfunction]
fn resolve_persist_db_path_py() -> String {
    resolve_persist_db_path().to_string_lossy().to_string()
}

/// Vector store (sqlite-vec) SQLite path.
#[pyfunction]
fn resolve_vectors_db_path_py() -> String {
    resolve_vectors_db_path().to_string_lossy().to_string()
}

/// Product layout under the workspace (`.soothe/backups`).
#[pyfunction]
fn workspace_backup_dir_py() -> &'static str {
    WORKSPACE_BACKUP_DIR
}

/// SQLite purpose databases subdirectory name (`databases`).
#[pyfunction]
fn sqlite_databases_subdir_py() -> &'static str {
    SQLITE_DATABASES_SUBDIR
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

    /// Whether symlink traversal is permitted.
    #[getter]
    fn allow_symlinks(&self) -> bool {
        self.inner.allow_symlinks
    }

    /// Maximum permitted file size in bytes.
    #[getter]
    fn max_file_size(&self) -> u64 {
        self.inner.max_file_size
    }

    /// Check if `path` is within the workspace root.
    fn is_within(&self, path: &str) -> bool {
        self.inner.is_within(std::path::Path::new(path))
    }

    /// Return a read-only policy (writes denied).
    #[pyo3(signature = ())]
    fn read_only(&self) -> PyWorkspacePolicy {
        PyWorkspacePolicy {
            inner: self.inner.clone().read_only(),
        }
    }

    /// Return a policy that permits symlink traversal.
    #[pyo3(signature = ())]
    fn allow_symlinks_set(&self) -> PyWorkspacePolicy {
        PyWorkspacePolicy {
            inner: self.inner.clone().allow_symlinks(),
        }
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
    m.add_function(wrap_pyfunction!(join_workspace_normalized_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(soothe_home_py, m)?)?;
    m.add_function(wrap_pyfunction!(default_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(db_path_for_thread_py, m)?)?;
    m.add_function(wrap_pyfunction!(should_use_virtual_path_resolution_py, m)?)?;
    m.add_function(wrap_pyfunction!(soothe_data_dir_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_databases_dir_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_sqlite_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_checkpoints_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_context_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_display_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_cron_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_identity_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_metadata_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_persist_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_vectors_db_path_py, m)?)?;
    m.add_function(wrap_pyfunction!(workspace_backup_dir_py, m)?)?;
    m.add_function(wrap_pyfunction!(sqlite_databases_subdir_py, m)?)?;
    Ok(())
}
