//! Workspace policy (ported from `workspace/workspace_policy.py`).

use std::path::{Path, PathBuf};

/// Controls what paths are allowed within a workspace.
#[derive(Debug, Clone)]
pub struct WorkspacePolicy {
    pub root: PathBuf,
    pub allow_symlinks: bool,
    pub max_file_size: u64,
    pub read_only: bool,
}

impl WorkspacePolicy {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self {
            root: root.into(),
            allow_symlinks: false,
            max_file_size: 10 * 1024 * 1024, // 10 MiB
            read_only: false,
        }
    }

    pub fn read_only(mut self) -> Self {
        self.read_only = true;
        self
    }

    pub fn allow_symlinks(mut self) -> Self {
        self.allow_symlinks = true;
        self
    }

    /// Check if a path is within the workspace root.
    pub fn is_within(&self, path: &Path) -> bool {
        let canonical_root = self
            .root
            .canonicalize()
            .unwrap_or_else(|_| self.root.clone());
        let canonical_path = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
        canonical_path.starts_with(&canonical_root)
    }

    /// Whether writes are permitted.
    pub fn can_write(&self) -> bool {
        !self.read_only
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn read_only_blocks_writes() {
        let policy = WorkspacePolicy::new("/tmp/ws").read_only();
        assert!(!policy.can_write());
    }

    #[test]
    fn default_allows_writes() {
        let policy = WorkspacePolicy::new("/tmp/ws");
        assert!(policy.can_write());
    }
}
