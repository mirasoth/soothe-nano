//! Skill discovery — filesystem scanning for `.md` skill files
//! (ported from `skills/discovery_tools.py`).

use serde::Serialize;
use std::path::{Path, PathBuf};

/// A discovered skill entry.
#[derive(Debug, Clone, Serialize)]
pub struct SkillEntry {
    pub name: String,
    pub path: String,
    pub description: String,
}

/// Parsed skill markdown.
#[derive(Debug, Clone, Serialize)]
pub struct SkillMarkdown {
    pub name: String,
    pub description: String,
    pub content: String,
}

/// Scans filesystem roots for skill definitions.
pub struct SkillDiscovery {
    roots: Vec<PathBuf>,
}

impl SkillDiscovery {
    pub fn new(roots: Vec<PathBuf>) -> Self {
        Self { roots }
    }

    /// Discover all skills across all roots.
    pub fn discover(&self) -> Vec<SkillEntry> {
        let mut entries = Vec::new();
        for root in &self.roots {
            if !root.is_dir() {
                continue;
            }
            for entry in walk_skills(root) {
                entries.push(entry);
            }
        }
        entries
    }

    /// Read and parse a skill markdown file.
    pub fn read_skill_markdown(path: &Path) -> Result<SkillMarkdown, String> {
        let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        let name = path
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default();
        // Extract description from first paragraph after any heading
        let description = content
            .lines()
            .skip_while(|l| l.starts_with('#'))
            .find(|l| !l.trim().is_empty())
            .unwrap_or("")
            .to_string();
        Ok(SkillMarkdown {
            name,
            description,
            content,
        })
    }
}

fn walk_skills(root: &Path) -> Vec<SkillEntry> {
    let mut entries = Vec::new();
    let walker = ignore::WalkBuilder::new(root).hidden(false).build();
    for entry in walker.flatten() {
        if !entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
            continue;
        }
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("md") {
            continue;
        }
        let name = path
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default();
        let rel = path
            .strip_prefix(root)
            .unwrap_or(path)
            .to_string_lossy()
            .to_string();
        entries.push(SkillEntry {
            name,
            path: rel,
            description: String::new(),
        });
    }
    entries
}
