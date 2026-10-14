//! CLI display formatting.

use std::path::{Path, PathBuf};

/// Format `"{type}: {msg}"`, truncating message to 500 chars + `"..."`.
pub fn format_cli_error(error_type: &str, error_msg: &str) -> String {
    let truncated = if error_msg.chars().count() > 500 {
        let head: String = error_msg.chars().take(500).collect();
        format!("{head}...")
    } else {
        error_msg.to_string()
    };
    format!("{error_type}: {truncated}")
}

/// Return `text` if `<= max_length`, else truncated + `"..."`.
/// When `max_length < 3`, performs a tail slice (negative-index behavior).
pub fn log_preview(text: &str, max_length: usize) -> String {
    let len = text.chars().count();
    if len <= max_length {
        return text.to_string();
    }
    let prefix = if max_length >= 3 {
        text.chars().take(max_length - 3).collect::<String>()
    } else {
        // Negative-index behavior: drop `3 - max_length` trailing chars.
        let drop = 3usize.saturating_sub(max_length);
        let take = len.saturating_sub(drop);
        text.chars().take(take).collect::<String>()
    };
    format!("{prefix}...")
}

/// Abbreviate path for display: home → `~`, base_dir → `.`, else original.
pub fn convert_and_abbreviate_path(path: &str, base_dir: Option<&str>) -> String {
    convert_and_abbreviate_path_inner(path, base_dir, home_dir_str().as_deref())
}

fn convert_and_abbreviate_path_inner(
    path: &str,
    base_dir: Option<&str>,
    home: Option<&str>,
) -> String {
    if path.is_empty() {
        return path.to_string();
    }

    let normalized = normalize_path_str(path);

    if let Some(h) = home {
        let home_norm = normalize_path_str(h);
        if let Some(rel) = strip_prefix_dir(&normalized, &home_norm) {
            if rel.is_empty() {
                return "~".to_string();
            }
            return format!("~/{rel}");
        }
    }

    if let Some(base) = base_dir {
        if !base.is_empty() {
            let base_norm = normalize_path_str(base);
            if let Some(rel) = strip_prefix_dir(&normalized, &base_norm) {
                let rel_str = if rel.is_empty() { ".".to_string() } else { rel };
                return format!(".{rel_str}");
            }
        }
    }

    normalized
}

/// Return relative remainder if `path` starts with `prefix` at a component boundary.
fn strip_prefix_dir(path: &str, prefix: &str) -> Option<String> {
    if !path.starts_with(prefix) {
        return None;
    }
    let rest = &path[prefix.len()..];
    if rest.is_empty() {
        Some(String::new())
    } else if rest.starts_with('/') {
        Some(rest.trim_start_matches('/').to_string())
    } else {
        None
    }
}

/// Normalize a path string.
fn normalize_path_str(path: &str) -> String {
    let p = Path::new(path);
    let buf: PathBuf = p.components().collect();
    let s = buf.to_string_lossy().to_string();
    if let Some(stripped) = s.strip_prefix("./") {
        stripped.to_string()
    } else {
        s
    }
}

/// Return the home directory from `$HOME`, or `None`.
fn home_dir_str() -> Option<String> {
    std::env::var("HOME").ok().filter(|s| !s.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn format_cli_error_basic() {
        assert_eq!(
            format_cli_error("ValueError", "bad input"),
            "ValueError: bad input"
        );
    }

    #[test]
    fn format_cli_error_truncates() {
        let long = "x".repeat(600);
        let result = format_cli_error("Err", &long);
        assert!(result.starts_with("Err: "));
        assert!(result.ends_with("..."));
        assert_eq!(result.len(), "Err: ".len() + 500 + 3);
    }

    #[test]
    fn log_preview_no_truncation() {
        assert_eq!(log_preview("hello", 10), "hello");
    }

    #[test]
    fn log_preview_truncates() {
        assert_eq!(log_preview("hello world", 8), "hello...");
    }

    #[test]
    fn log_preview_negative_index() {
        // max_length=0: text[:-3] → drop last 3 chars
        assert_eq!(log_preview("abcde", 0), "ab...");
    }

    #[test]
    fn log_preview_max_length_3() {
        assert_eq!(log_preview("abcde", 3), "...");
    }

    #[test]
    fn log_preview_max_length_1() {
        // max_length=1: text[:-2] → drop last 2 chars
        assert_eq!(log_preview("abcde", 1), "abc...");
    }

    #[test]
    fn convert_home() {
        assert_eq!(
            convert_and_abbreviate_path_inner("/Users/test/src/main.rs", None, Some("/Users/test")),
            "~/src/main.rs"
        );
    }

    #[test]
    fn convert_home_exact() {
        assert_eq!(
            convert_and_abbreviate_path_inner("/Users/test", None, Some("/Users/test")),
            "~"
        );
    }

    #[test]
    fn convert_false_prefix_rejected() {
        assert_eq!(
            convert_and_abbreviate_path_inner("/Users/xiamingfoo", None, Some("/Users/xiam")),
            "/Users/xiamingfoo"
        );
    }

    #[test]
    fn convert_base_dir() {
        assert_eq!(
            convert_and_abbreviate_path("/ws/src/main.rs", Some("/ws")),
            ".src/main.rs"
        );
    }

    #[test]
    fn convert_base_dir_exact() {
        // path == base → ".." (Python: "." + str(Path(".")) == "..")
        assert_eq!(convert_and_abbreviate_path("/ws", Some("/ws")), "..");
    }

    #[test]
    fn convert_no_match() {
        assert_eq!(
            convert_and_abbreviate_path("/other/path", Some("/ws")),
            "/other/path"
        );
    }

    #[test]
    fn convert_empty() {
        assert_eq!(convert_and_abbreviate_path("", None), "");
    }

    #[test]
    fn convert_relative_with_relative_base() {
        assert_eq!(
            convert_and_abbreviate_path("relative/path", Some("relative")),
            ".path"
        );
    }

    #[test]
    fn convert_strips_leading_dot_slash() {
        assert_eq!(convert_and_abbreviate_path("./foo", None), "foo");
    }

    #[test]
    fn convert_strips_trailing_slash() {
        assert_eq!(convert_and_abbreviate_path("foo/", None), "foo");
    }

    #[test]
    fn convert_collapses_double_slash() {
        assert_eq!(convert_and_abbreviate_path("foo//bar", None), "foo/bar");
    }

    #[test]
    fn convert_home_with_base_fallback() {
        // Path not under home, not under base → original
        assert_eq!(
            convert_and_abbreviate_path_inner("/opt/other", Some("/ws"), Some("/Users/test")),
            "/opt/other"
        );
    }

    #[test]
    fn convert_base_empty_string() {
        assert_eq!(
            convert_and_abbreviate_path("/ws/path", Some("")),
            "/ws/path"
        );
    }
}
