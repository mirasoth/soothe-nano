//! Project instructions loader (ported from `prompts/project_instructions.py`).

use std::path::Path;

/// Load project instructions from common locations:
/// `AGENTS.md`, `.soothe/AGENTS.md`, `CLAUDE.md`.
pub fn load_project_instructions(workspace: &Path) -> Option<String> {
    for filename in &["AGENTS.md", ".soothe/AGENTS.md", "CLAUDE.md"] {
        let path = workspace.join(filename);
        if path.is_file() {
            if let Ok(content) = std::fs::read_to_string(&path) {
                return Some(content);
            }
        }
    }
    None
}
