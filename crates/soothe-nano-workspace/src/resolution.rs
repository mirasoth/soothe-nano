//! Workspace resolution logic.

use crate::WorkspaceError;
use std::path::PathBuf;

/// Where the workspace came from.
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

/// Expand `~` to the home directory.
fn expanduser(path: &str) -> String {
    if path.starts_with('~') {
        if let Ok(home) = std::env::var("HOME") {
            if path == "~" {
                return home;
            }
            if let Some(stripped) = path.strip_prefix("~/") {
                return format!("{home}/{stripped}");
            }
        }
    }
    path.to_string()
}

/// Normalize a workspace candidate: expand `~` and resolve symlinks.
fn normalize_candidate(path: &str) -> PathBuf {
    let expanded = expanduser(path);
    let p = PathBuf::from(&expanded);
    p.canonicalize().unwrap_or(p)
}

/// Resolve workspace for a stream: explicit > thread > daemon default > cwd.
pub fn resolve_workspace_for_stream(
    explicit: Option<&str>,
    thread_workspace: Option<&str>,
    installation_default: Option<&str>,
) -> Result<ResolvedWorkspace, WorkspaceError> {
    if let Some(ws) = explicit {
        return Ok(ResolvedWorkspace {
            path: normalize_candidate(ws),
            source: WorkspaceSource::Explicit,
        });
    }
    if let Some(ws) = thread_workspace {
        return Ok(ResolvedWorkspace {
            path: normalize_candidate(ws),
            source: WorkspaceSource::Thread,
        });
    }
    if let Some(ws) = installation_default {
        return Ok(ResolvedWorkspace {
            path: normalize_candidate(ws),
            source: WorkspaceSource::DaemonDefault,
        });
    }
    Ok(ResolvedWorkspace {
        path: std::env::current_dir().map_err(|_| WorkspaceError::Unresolvable)?,
        source: WorkspaceSource::Cwd,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    /// Serializes tests that mutate `HOME` (shared with paths::tests).
    static ENV_LOCK: Mutex<()> = Mutex::new(());

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
    fn expanduser_tilde() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("HOME", "/test/home");
        assert_eq!(expanduser("~"), "/test/home");
        assert_eq!(expanduser("~/projects"), "/test/home/projects");
        assert_eq!(expanduser("/absolute"), "/absolute");
    }
}
