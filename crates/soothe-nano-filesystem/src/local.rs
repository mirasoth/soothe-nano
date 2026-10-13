//! Local filesystem implementation (ported from `filesystem/local.py`).

use std::path::PathBuf;

use soothe_nano_security::PathValidator;
use soothe_nano_workspace::WorkspacePolicy;

use crate::file_ops::{BatchedEditResult, EditOp, EditResult, ReadResult, WriteResult};
use crate::glob::GlobResult;
use crate::grep::GrepResult;

/// Local filesystem with workspace isolation + path validation.
#[allow(dead_code)]
pub struct LocalFilesystem {
    workspace: PathBuf,
    policy: WorkspacePolicy,
    validator: PathValidator,
    max_file_size: u64,
}

impl LocalFilesystem {
    pub fn new(workspace: impl Into<PathBuf>) -> Self {
        let workspace = workspace.into();
        let policy = WorkspacePolicy::new(&workspace);
        let max_file_size = policy.max_file_size;
        let validator = PathValidator::new(&workspace);
        Self {
            workspace,
            policy,
            validator,
            max_file_size,
        }
    }

    /// Resolve a user-supplied path relative to the workspace root.
    fn resolve(&self, path: &str) -> Result<PathBuf, String> {
        let normalized = soothe_nano_utils::normalize_relative(path).map_err(|e| e.to_string())?;
        let full = self.workspace.join(&normalized);
        if !self.policy.is_within(&full) {
            return Err(format!("path escapes workspace: {path}"));
        }
        Ok(full)
    }

    /// Read file contents with optional offset/limit (line-based).
    pub fn read(
        &self,
        path: &str,
        offset: usize,
        limit: Option<usize>,
    ) -> Result<ReadResult, String> {
        let full = self.resolve(path)?;
        let content = std::fs::read_to_string(&full).map_err(|e| e.to_string())?;
        let lines: Vec<&str> = content.lines().collect();
        let start = offset.min(lines.len());
        let end = limit
            .map(|l| (start + l).min(lines.len()))
            .unwrap_or(lines.len());
        let slice = &lines[start..end];
        Ok(ReadResult {
            content: slice.join("\n"),
            total_lines: lines.len(),
            returned_lines: slice.len(),
            offset: start,
        })
    }

    /// Write content to a file (creates or overwrites).
    pub fn write(&self, path: &str, content: &str) -> Result<WriteResult, String> {
        let full = self.resolve(path)?;
        if let Some(parent) = full.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        std::fs::write(&full, content).map_err(|e| e.to_string())?;
        Ok(WriteResult {
            bytes_written: content.len() as u64,
        })
    }

    /// Edit a file by replacing `old_string` with `new_string`.
    pub fn edit(&self, path: &str, old: &str, new: &str) -> Result<EditResult, String> {
        let full = self.resolve(path)?;
        let content = std::fs::read_to_string(&full).map_err(|e| e.to_string())?;
        let count = content.matches(old).count();
        if count == 0 {
            return Err(format!("old_string not found in {path}"));
        }
        if count > 1 {
            return Err(format!(
                "old_string appears {count} times in {path}; must be unique"
            ));
        }
        let new_content = content.replacen(old, new, 1);
        std::fs::write(&full, &new_content).map_err(|e| e.to_string())?;
        Ok(EditResult { replacements: 1 })
    }

    /// Apply multiple edits in sequence.
    pub fn batch_edit(&self, ops: Vec<EditOp>) -> Result<BatchedEditResult, String> {
        let mut results = Vec::with_capacity(ops.len());
        let mut errors = Vec::new();
        for op in ops {
            match self.edit(&op.path, &op.old_string, &op.new_string) {
                Ok(r) => results.push(r),
                Err(e) => errors.push(format!("{}: {e}", op.path)),
            }
        }
        Ok(BatchedEditResult { results, errors })
    }

    /// Delete a file.
    pub fn delete(&self, path: &str) -> Result<(), String> {
        let full = self.resolve(path)?;
        std::fs::remove_file(&full).map_err(|e| e.to_string())
    }

    /// Glob files matching a pattern (gitignore-aware).
    pub fn glob(&self, pattern: &str) -> Result<GlobResult, String> {
        crate::glob::glob(&self.workspace, pattern)
    }

    /// Grep for a literal pattern in files.
    pub fn grep(&self, pattern: &str, path: &str) -> Result<GrepResult, String> {
        crate::grep::grep(&self.workspace, pattern, path)
    }
}
