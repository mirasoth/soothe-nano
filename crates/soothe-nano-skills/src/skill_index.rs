//! Mtime-based skill index for fast process-level skill discovery.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

/// Lightweight skill metadata cached by the index.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillIndexEntry {
    pub name: String,
    pub description: String,
    pub tags: String,
    pub source: String,
    pub path: String,
    pub mtime: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub paths: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub when_to_use: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub core: Option<bool>,
}

/// Intermediate struct for deserializing YAML frontmatter.
#[derive(Debug, Deserialize)]
struct FrontmatterYaml {
    name: Option<serde_yaml::Value>,
    description: Option<serde_yaml::Value>,
    tags: Option<serde_yaml::Value>,
    paths: Option<serde_yaml::Value>,
    when_to_use: Option<serde_yaml::Value>,
    core: Option<serde_yaml::Value>,
}

/// Mtime-aware skill index; re-parses SKILL.md only when mtime changes.
#[derive(Debug, Clone, Default)]
pub struct SkillIndex {
    entries: HashMap<String, SkillIndexEntry>,
    loaded: bool,
}

impl SkillIndex {
    pub fn new() -> Self {
        Self::default()
    }

    /// Return all indexed entries sorted by name (case-insensitive).
    pub fn entries(&self) -> Vec<&SkillIndexEntry> {
        let mut v: Vec<&SkillIndexEntry> = self.entries.values().collect();
        v.sort_by_key(|e| e.name.to_lowercase());
        v
    }

    /// Resolve a skill by name (case-insensitive).
    pub fn resolve(&self, name: &str) -> Option<&SkillIndexEntry> {
        self.entries.get(&name.to_lowercase())
    }

    /// Stat all skill directories; re-parse only changed entries.
    ///
    /// Returns the full list of current entries after refresh.
    pub fn rebuild_if_stale(
        &mut self,
        roots: &[(String, String)],
        cache_path: &Path,
    ) -> Vec<SkillIndexEntry> {
        if !self.loaded {
            self.load_cache(cache_path);
        }

        let current_skills = discover_skill_dirs(roots);
        let mut changed = false;
        let mut new_entries: HashMap<String, SkillIndexEntry> = HashMap::new();

        for (key, (skill_dir, mtime, source)) in &current_skills {
            if let Some(existing) = self.entries.get(key) {
                if existing.mtime >= *mtime && existing.path == skill_dir.to_string_lossy() {
                    new_entries.insert(key.clone(), existing.clone());
                    continue;
                }
            }
            // Parse the skill dir
            if let Some(entry) = parse_skill_dir(Path::new(skill_dir), *mtime, source) {
                let name_key = entry.name.to_lowercase();
                new_entries.insert(name_key, entry);
                changed = true;
            }
        }

        if self.entries.len() != new_entries.len() || self.entries.keys().ne(new_entries.keys()) {
            changed = true;
        }

        self.entries = new_entries;
        self.loaded = true;

        if changed {
            self.persist(cache_path);
        }

        let mut v: Vec<SkillIndexEntry> = self.entries.values().cloned().collect();
        v.sort_by_key(|e| e.name.to_lowercase());
        v
    }

    /// Return wire-safe dicts (no path field) for RPC serialization.
    pub fn wire_entries(&self) -> Vec<WireEntry> {
        self.entries()
            .iter()
            .map(|e| WireEntry {
                name: e.name.clone(),
                description: e.description.clone(),
                source: e.source.clone(),
                tags: if e.tags.is_empty() {
                    None
                } else {
                    Some(e.tags.clone())
                },
                paths: e.paths.clone(),
                when_to_use: e.when_to_use.clone(),
            })
            .collect()
    }

    /// Load persisted index from disk if available.
    pub fn load_cache(&mut self, path: &Path) {
        let text = match fs::read_to_string(path) {
            Ok(t) => t,
            Err(_) => return,
        };
        let data: Vec<SkillIndexEntry> = match serde_json::from_str(&text) {
            Ok(d) => d,
            Err(_) => return,
        };
        for entry in data {
            self.entries.insert(entry.name.to_lowercase(), entry);
        }
    }

    /// Write current index to disk cache.
    pub fn persist(&self, path: &Path) {
        if let Some(parent) = path.parent() {
            if fs::create_dir_all(parent).is_err() {
                return;
            }
        }
        let entries: Vec<&SkillIndexEntry> = self.entries.values().collect();
        let json = serde_json::to_string_pretty(&entries).unwrap_or_default();
        let _ = fs::write(path, json);
    }
}

/// Wire-safe entry (no path field).
#[derive(Debug, Clone, Serialize)]
pub struct WireEntry {
    pub name: String,
    pub description: String,
    pub source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub paths: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub when_to_use: Option<String>,
}

/// Scan skill roots, stat SKILL.md in each candidate dir.
///
/// Returns name key → (resolved path, mtime, source).
/// Last-wins dedup: later roots override earlier ones.
pub fn discover_skill_dirs(roots: &[(String, String)]) -> HashMap<String, (PathBuf, f64, String)> {
    let mut by_name: HashMap<String, (PathBuf, f64, String)> = HashMap::new();
    for (root, source) in roots {
        let root_path = Path::new(root);
        if !root_path.is_dir() {
            continue;
        }
        let entries = match fs::read_dir(root_path) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for dir_entry in entries.flatten() {
            let file_type = match dir_entry.file_type() {
                Ok(ft) => ft,
                Err(_) => continue,
            };
            if !file_type.is_dir() {
                continue;
            }
            let skill_md = dir_entry.path().join("SKILL.md");
            let st = match fs::metadata(&skill_md) {
                Ok(s) => s,
                Err(_) => continue,
            };
            let mtime = st
                .modified()
                .ok()
                .and_then(|t| {
                    t.duration_since(std::time::UNIX_EPOCH)
                        .ok()
                        .map(|d| d.as_secs_f64())
                })
                .unwrap_or(0.0);

            let dir_name = dir_entry.file_name().to_string_lossy().to_string();
            let name_key = discover_skill_name_key(&skill_md, &dir_name);
            let resolved = dir_entry.path().canonicalize().unwrap_or(dir_entry.path());
            by_name.insert(name_key, (resolved, mtime, source.clone()));
        }
    }
    by_name
}

/// Return lowercase dedupe key from frontmatter `name` when available.
pub fn discover_skill_name_key(skill_md: &Path, fallback_dir_name: &str) -> String {
    let fallback = fallback_dir_name.trim().to_lowercase();
    let text = match fs::read_to_string(skill_md) {
        Ok(t) => t,
        Err(_) => return fallback,
    };
    match parse_skill_frontmatter(&text, fallback_dir_name) {
        Some(entry) if !entry.name.is_empty() => entry.name.trim().to_lowercase(),
        _ => fallback,
    }
}

/// Parse SKILL.md frontmatter and build an index entry.
pub fn parse_skill_dir(skill_dir: &Path, mtime: f64, source: &str) -> Option<SkillIndexEntry> {
    let md_file = skill_dir.join("SKILL.md");
    let text = fs::read_to_string(&md_file).ok()?;
    let entry = parse_skill_frontmatter(&text, &skill_dir.file_name()?.to_string_lossy())?;
    Some(SkillIndexEntry {
        name: entry.name,
        description: entry.description,
        tags: entry.tags,
        source: source.to_string(),
        path: skill_dir.to_string_lossy().to_string(),
        mtime,
        paths: entry.paths,
        when_to_use: entry.when_to_use,
        core: entry.core,
    })
}

/// Parse YAML frontmatter from SKILL.md content.
///
/// Extracts `name`, `description`, `tags`, `paths`, `when_to_use`, `core`
/// from standard YAML frontmatter delimited by `---` markers.
/// Returns `None` if frontmatter is missing or `name`/`description` are absent.
pub fn parse_skill_frontmatter(text: &str, fallback_name: &str) -> Option<SkillIndexEntry> {
    let content = text;

    // Match YAML frontmatter between --- delimiters
    if !content.starts_with("---") {
        return None;
    }
    let rest = &content[3..];

    // Skip optional whitespace after first ---
    let rest = rest
        .strip_prefix('\n')
        .or_else(|| rest.strip_prefix("\r\n"))
        .unwrap_or(rest);

    // Find the closing ---
    let close = rest.find("\n---").or_else(|| rest.find("\r\n---"))?;
    let frontmatter_str = &rest[..close];

    let yaml: FrontmatterYaml = serde_yaml::from_str(frontmatter_str).ok()?;

    let name = yaml
        .name
        .as_ref()
        .and_then(yaml_value_to_string)
        .unwrap_or_default()
        .trim()
        .to_string();
    let description = yaml
        .description
        .as_ref()
        .and_then(yaml_value_to_string)
        .unwrap_or_default()
        .trim()
        .to_string();

    if name.is_empty() || description.is_empty() {
        return None;
    }

    let tags = yaml
        .tags
        .as_ref()
        .and_then(yaml_value_to_string)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_default();

    let paths = yaml.paths.as_ref().and_then(extract_paths);
    let when_to_use = yaml
        .when_to_use
        .as_ref()
        .and_then(yaml_value_to_string)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let core = yaml.core.as_ref().and_then(extract_core);

    let _ = fallback_name; // not used for entry name; frontmatter name wins

    Some(SkillIndexEntry {
        name,
        description,
        tags,
        source: String::new(),
        path: String::new(),
        mtime: 0.0,
        paths,
        when_to_use,
        core,
    })
}

/// Convert a `serde_yaml::Value` to a `String`.
fn yaml_value_to_string(v: &serde_yaml::Value) -> Option<String> {
    match v {
        serde_yaml::Value::String(s) => Some(s.clone()),
        serde_yaml::Value::Number(n) => Some(n.to_string()),
        serde_yaml::Value::Bool(b) => Some(b.to_string()),
        serde_yaml::Value::Null => None,
        _ => Some(serde_yaml::to_string(v).ok()?.trim().to_string()),
    }
}

/// Extract `paths` from frontmatter: list of strings or single non-empty string.
fn extract_paths(v: &serde_yaml::Value) -> Option<Vec<String>> {
    match v {
        serde_yaml::Value::Sequence(seq) => {
            let paths: Vec<String> = seq
                .iter()
                .filter_map(yaml_value_to_string)
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
            if paths.is_empty() {
                None
            } else {
                Some(paths)
            }
        }
        serde_yaml::Value::String(s) => {
            let trimmed = s.trim();
            if trimmed.is_empty() {
                None
            } else {
                Some(vec![trimmed.to_string()])
            }
        }
        _ => None,
    }
}

/// Extract `core` from frontmatter: bool or string "true"/"yes"/"1" / "false"/"no"/"0".
fn extract_core(v: &serde_yaml::Value) -> Option<bool> {
    match v {
        serde_yaml::Value::Bool(b) => Some(*b),
        serde_yaml::Value::String(s) => match s.trim().to_lowercase().as_str() {
            "true" | "yes" | "1" => Some(true),
            "false" | "no" | "0" => Some(false),
            _ => None,
        },
        serde_yaml::Value::Number(n) if n.as_i64().is_some() => match n.as_i64() {
            Some(1) => Some(true),
            Some(0) => Some(false),
            _ => None,
        },
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_frontmatter() {
        let text = "---\nname: my-skill\ndescription: A test skill\ntags: test\n---\n# My Skill\n";
        let entry = parse_skill_frontmatter(text, "my-skill").unwrap();
        assert_eq!(entry.name, "my-skill");
        assert_eq!(entry.description, "A test skill");
        assert_eq!(entry.tags, "test");
    }

    #[test]
    fn test_parse_with_optional_fields() {
        let text = "---\nname: my-skill\ndescription: A test skill\npaths:\n  - \"**/*.py\"\n  - \"**/*.rs\"\nwhen_to_use: When you need testing\ncore: true\n---\n";
        let entry = parse_skill_frontmatter(text, "my-skill").unwrap();
        assert_eq!(
            entry.paths,
            Some(vec!["**/*.py".to_string(), "**/*.rs".to_string()])
        );
        assert_eq!(entry.when_to_use, Some("When you need testing".to_string()));
        assert_eq!(entry.core, Some(true));
    }

    #[test]
    fn test_parse_missing_name_returns_none() {
        let text = "---\ndescription: No name\n---\n";
        assert!(parse_skill_frontmatter(text, "dir").is_none());
    }

    #[test]
    fn test_parse_missing_description_returns_none() {
        let text = "---\nname: skill\n---\n";
        assert!(parse_skill_frontmatter(text, "dir").is_none());
    }

    #[test]
    fn test_parse_no_frontmatter_returns_none() {
        let text = "# Just a heading\nNo frontmatter here";
        assert!(parse_skill_frontmatter(text, "dir").is_none());
    }

    #[test]
    fn test_parse_core_string_variants() {
        for (input, expected) in [
            ("true", true),
            ("yes", true),
            ("1", true),
            ("false", false),
            ("no", false),
            ("0", false),
        ] {
            let text = format!("---\nname: s\ndescription: d\ncore: {input}\n---\n");
            let entry = parse_skill_frontmatter(&text, "s").unwrap();
            assert_eq!(entry.core, Some(expected), "core: {input}");
        }
    }
}
