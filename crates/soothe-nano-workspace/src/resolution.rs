//! Workspace resolution logic (ported from `workspace/workspace_api.py`).

use crate::WorkspaceError;
use std::path::{Path, PathBuf};

/// Where the workspace came from — mirrors the Python precedence chain.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceSource {
    Explicit,
    Thread,
    DaemonDefault,
    Cwd,
    ToolExecution,
}

/// Result of workspace resolution.
#[derive(Debug, Clone)]
pub struct ResolvedWorkspace {
    pub path: PathBuf,
    pub source: WorkspaceSource,
}

/// Resolve the workspace for a stream, following the precedence chain:
/// explicit > thread > daemon default > cwd.
pub fn resolve_workspace_for_stream(
    explicit: Option<&str>,
    thread_workspace: Option<&str>,
    installation_default: Option<&str>,
) -> Result<ResolvedWorkspace, WorkspaceError> {
    if let Some(ws) = explicit {
        return Ok(ResolvedWorkspace {
            path: PathBuf::from(ws),
            source: WorkspaceSource::Explicit,
        });
    }
    if let Some(ws) = thread_workspace {
        return Ok(ResolvedWorkspace {
            path: PathBuf::from(ws),
            source: WorkspaceSource::Thread,
        });
    }
    if let Some(ws) = installation_default {
        return Ok(ResolvedWorkspace {
            path: PathBuf::from(ws),
            source: WorkspaceSource::DaemonDefault,
        });
    }
    Ok(ResolvedWorkspace {
        path: std::env::current_dir().map_err(|_| WorkspaceError::Unresolvable)?,
        source: WorkspaceSource::Cwd,
    })
}

/// Join a workspace root with a relative path, ensuring the result
/// does not escape the workspace boundary.
pub fn join_workspace_normalized_path(
    workspace: &Path,
    relative: &str,
) -> Result<PathBuf, WorkspaceError> {
    let normalized =
        soothe_nano_utils::normalize_relative(relative).map_err(WorkspaceError::InvalidPath)?;

    let joined = workspace.join(&normalized);
    let canonical = joined
        .parent()
        .and_then(|p| p.canonicalize().ok())
        .unwrap_or_else(|| workspace.to_path_buf());

    if !canonical.starts_with(workspace) {
        return Err(WorkspaceError::PathEscape(relative.to_string()));
    }

    Ok(canonical.join(normalized.file_name().unwrap_or_default()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_takes_precedence() {
        let r = resolve_workspace_for_stream(Some("/explicit"), Some("/thread"), Some("/default"))
            .unwrap();
        assert_eq!(r.source, WorkspaceSource::Explicit);
        assert_eq!(r.path, PathBuf::from("/explicit"));
    }

    #[test]
    fn thread_falls_back_to_default() {
        let r = resolve_workspace_for_stream(None, None, Some("/default")).unwrap();
        assert_eq!(r.source, WorkspaceSource::DaemonDefault);
    }

    #[test]
    fn join_rejects_escape() {
        let ws = Path::new("/tmp/workspace");
        assert!(join_workspace_normalized_path(ws, "../../etc").is_err());
    }

    #[test]
    fn join_normal_relative() {
        let ws = Path::new("/tmp/workspace");
        let joined = join_workspace_normalized_path(ws, "src/main.rs").unwrap();
        assert!(joined.starts_with(ws));
    }
}
