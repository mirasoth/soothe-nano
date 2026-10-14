//! Grep using `ignore` for traversal and `regex` for matching.

use serde::Serialize;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

#[derive(Debug, Clone, Serialize)]
pub struct GrepMatch {
    pub file: String,
    pub line_number: usize,
    pub line: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct GrepResult {
    pub matches: Vec<GrepMatch>,
    pub files_searched: usize,
}

/// Search for a literal `pattern` in files under `root/path`.
pub fn grep(root: &Path, pattern: &str, path: &str) -> Result<GrepResult, String> {
    let search_root = if path == "." || path.is_empty() {
        root.to_path_buf()
    } else {
        root.join(path)
    };

    let re =
        regex::Regex::new(&regex::escape(pattern)).map_err(|e| format!("invalid pattern: {e}"))?;

    let mut matches = Vec::new();
    let mut files_searched = 0;

    let walker = ignore::WalkBuilder::new(&search_root).hidden(false).build();

    for entry in walker {
        let entry = entry.map_err(|e| e.to_string())?;
        if !entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
            continue;
        }
        files_searched += 1;
        let path = entry.path();
        let file = File::open(path).map_err(|e| e.to_string())?;
        let reader = BufReader::new(file);
        for (i, line) in reader.lines().enumerate() {
            let line = line.map_err(|e| e.to_string())?;
            if re.is_match(&line) {
                matches.push(GrepMatch {
                    file: path
                        .strip_prefix(root)
                        .unwrap_or(path)
                        .to_string_lossy()
                        .to_string(),
                    line_number: i + 1,
                    line,
                });
            }
        }
    }

    Ok(GrepResult {
        matches,
        files_searched,
    })
}
