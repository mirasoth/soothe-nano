//! Environment and workspace XML section builders.
//!
//! Ports: `prompts/context_xml.py::build_soothe_environment_section` and
//! `build_soothe_workspace_section`. The environment section calls back into
//! Python via PyO3 for `is_rg_available()` and `get_knowledge_cutoff()`.

use std::path::Path;

/// XML-escape text content (& < >).
fn escape_xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// Build the ENVIRONMENT XML block.
///
/// `is_rg` and `knowledge_cutoff` are passed in (obtained via PyO3 round-trip
/// from Python) so this function stays pure Rust and testable without Python.
pub fn build_environment_section(
    platform_name: &str,
    shell: &str,
    os_version: &str,
    model: &str,
    knowledge_cutoff: &str,
    is_rg: bool,
) -> String {
    let search_backend = if is_rg { "ripgrep" } else { "python_fallback" };
    let inner = [
        format!("<platform>{}</platform>", escape_xml(platform_name)),
        format!("<shell>{}</shell>", escape_xml(shell)),
        format!("<os_version>{}</os_version>", escape_xml(os_version)),
        format!("<model>{}</model>", escape_xml(model)),
        format!(
            "<knowledge_cutoff>{}</knowledge_cutoff>",
            escape_xml(knowledge_cutoff)
        ),
        format!(
            "<search_backend>{}</search_backend>",
            escape_xml(search_backend)
        ),
    ];
    format!("<ENVIRONMENT>\n{}\n</ENVIRONMENT>", inner.join("\n"))
}

/// Build the WORKSPACE XML block.
///
/// `workspace_path` is the resolved root. When `include_layout` is true,
/// lists top-level directory entries (max `max_layout_entries`). When
/// `include_readme` is true, reads a short README excerpt.
pub fn build_workspace_section(
    workspace_path: &Path,
    include_layout: bool,
    max_layout_entries: usize,
    include_readme: bool,
    readme_max_chars: usize,
) -> String {
    let cwd = workspace_path.to_str().unwrap_or("").to_string();
    let is_git = workspace_path.join(".git").exists();
    let present = if is_git { "true" } else { "false" };

    let mut lines: Vec<String> = vec![
        format!("<root>{}</root>", escape_xml(&cwd)),
        format!(r#"<vcs present="{}"/>"#, present),
    ];

    if include_layout && workspace_path.is_dir() {
        if let Some(preview) = safe_list_dir_names(workspace_path, max_layout_entries) {
            lines.push(format!(
                r#"<layout_preview max_entries="{}">{}</layout_preview>"#,
                max_layout_entries,
                escape_xml(&preview)
            ));
        }
    }

    if include_readme && workspace_path.is_dir() {
        if let Some(excerpt) = readme_excerpt(workspace_path, readme_max_chars) {
            lines.push(format!(
                "<readme_excerpt>{}</readme_excerpt>",
                escape_xml(&excerpt)
            ));
        }
    }

    let inner = lines.join("\n");
    format!("<WORKSPACE>\n{}\n</WORKSPACE>", inner)
}

/// List non-hidden top-level directory names, capped at `max_entries`.
fn safe_list_dir_names(root: &Path, max_entries: usize) -> Option<String> {
    let entries = std::fs::read_dir(root).ok()?;
    let mut names: Vec<String> = Vec::new();
    for entry in entries {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with('.') {
            continue;
        }
        names.push(name);
    }
    if names.is_empty() {
        return None;
    }
    names.sort();
    let total = names.len();
    let preview: Vec<&str> = names.iter().take(max_entries).map(|s| s.as_str()).collect();
    let mut joined = preview.join(", ");
    if total > max_entries {
        joined.push_str(", …");
    }
    Some(joined)
}

/// Read a short excerpt from a README file if one exists.
fn readme_excerpt(root: &Path, max_chars: usize) -> Option<String> {
    for name in &["README.md", "README.rst", "README.txt", "README"] {
        let path = root.join(name);
        if path.is_file() {
            if let Ok(raw) = std::fs::read_to_string(&path) {
                let excerpt: String = raw.chars().take(max_chars).collect();
                let trimmed = excerpt.trim().to_string();
                if !trimmed.is_empty() {
                    return Some(trimmed);
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn builds_environment_with_ripgrep() {
        let xml = build_environment_section(
            "Darwin",
            "/bin/zsh",
            "Darwin-15.4.1",
            "claude-opus-4-6",
            "2025-05",
            true,
        );
        assert!(xml.contains("<ENVIRONMENT>"));
        assert!(xml.contains("<platform>Darwin</platform>"));
        assert!(xml.contains("<shell>/bin/zsh</shell>"));
        assert!(xml.contains("<search_backend>ripgrep</search_backend>"));
        assert!(xml.contains("<knowledge_cutoff>2025-05</knowledge_cutoff>"));
    }

    #[test]
    fn builds_environment_with_python_fallback() {
        let xml =
            build_environment_section("Linux", "bash", "Linux-6.1", "test-model", "2025-01", false);
        assert!(xml.contains("<search_backend>python_fallback</search_backend>"));
    }

    #[test]
    fn escapes_xml_in_environment() {
        let xml =
            build_environment_section("Darwin", "/bin/zsh & more", "x", "<model>", "2025-01", true);
        assert!(xml.contains("&amp;"));
        assert!(xml.contains("&lt;model&gt;"));
    }

    #[test]
    fn builds_workspace_with_git() {
        let tmp = tempfile::tempdir().unwrap();
        fs::create_dir(tmp.path().join(".git")).unwrap();
        let xml = build_workspace_section(tmp.path(), false, 40, false, 500);
        assert!(xml.contains("<WORKSPACE>"));
        assert!(xml.contains(r#"<vcs present="true"/>"#));
    }

    #[test]
    fn builds_workspace_without_git() {
        let tmp = tempfile::tempdir().unwrap();
        let xml = build_workspace_section(tmp.path(), false, 40, false, 500);
        assert!(xml.contains(r#"<vcs present="false"/>"#));
    }

    #[test]
    fn workspace_layout_preview_lists_entries() {
        let tmp = tempfile::tempdir().unwrap();
        fs::create_dir(tmp.path().join("src")).unwrap();
        fs::create_dir(tmp.path().join("tests")).unwrap();
        fs::create_dir(tmp.path().join(".hidden")).unwrap();
        let xml = build_workspace_section(tmp.path(), true, 40, false, 500);
        assert!(xml.contains("src"));
        assert!(xml.contains("tests"));
        assert!(!xml.contains(".hidden"));
    }

    #[test]
    fn workspace_layout_preview_caps_entries() {
        let tmp = tempfile::tempdir().unwrap();
        for i in 0..10 {
            fs::create_dir(tmp.path().join(format!("dir{i}"))).unwrap();
        }
        let xml = build_workspace_section(tmp.path(), true, 5, false, 500);
        assert!(xml.contains("…"));
    }

    #[test]
    fn workspace_readme_excerpt() {
        let tmp = tempfile::tempdir().unwrap();
        fs::write(
            tmp.path().join("README.md"),
            "# My Project\n\nSome content here.",
        )
        .unwrap();
        let xml = build_workspace_section(tmp.path(), false, 40, true, 500);
        assert!(xml.contains("<readme_excerpt>"));
        assert!(xml.contains("My Project"));
    }

    #[test]
    fn workspace_readme_excerpt_truncated() {
        let tmp = tempfile::tempdir().unwrap();
        let long = "A".repeat(1000);
        fs::write(tmp.path().join("README.md"), &long).unwrap();
        let xml = build_workspace_section(tmp.path(), false, 40, true, 50);
        let excerpt_start = xml.find("<readme_excerpt>").unwrap() + "<readme_excerpt>".len();
        let excerpt_end = xml.find("</readme_excerpt>").unwrap();
        let excerpt = &xml[excerpt_start..excerpt_end];
        assert!(excerpt.len() <= 50);
    }
}
