//! Glob implementation using the `ignore` crate for gitignore-aware traversal.

use serde::Serialize;
use std::path::Path;

#[derive(Debug, Clone, Serialize)]
pub struct GlobResult {
    pub files: Vec<String>,
}

/// Find files matching a glob `pattern` under `root`.
pub fn glob(root: &Path, pattern: &str) -> Result<GlobResult, String> {
    let glob = globset::Glob::new(pattern).map_err(|e| format!("invalid glob: {e}"))?;
    let matcher = globset::GlobSet::builder()
        .add(glob)
        .build()
        .map_err(|e| format!("globset build: {e}"))?;

    let mut files = Vec::new();
    let walker = ignore::WalkBuilder::new(root).hidden(false).build();

    for entry in walker {
        let entry = entry.map_err(|e| e.to_string())?;
        if !entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
            continue;
        }
        let path = entry.path();
        let rel = path.strip_prefix(root).unwrap_or(path);
        let rel_str = rel.to_string_lossy();
        if matcher.is_match(rel_str.as_ref()) || matcher.is_match(path) {
            files.push(rel_str.to_string());
        }
    }

    files.sort();
    Ok(GlobResult { files })
}
