//! Text preview with truncation (ported from `utils/text_preview.py`).

const DEFAULT_MARKER_TEMPLATE: &str = "[...{count} {unit} abbr...]";

/// Build a truncation marker string.
fn build_marker(count: usize, unit: &str, marker: Option<&str>) -> String {
    match marker {
        Some(m) => m.to_string(),
        None => DEFAULT_MARKER_TEMPLATE
            .replace("{count}", &count.to_string())
            .replace("{unit}", unit),
    }
}

/// Produce a preview of `text`, truncated to `max_chars` characters with `...` appended.
///
/// Matches Python's `log_preview(text, chars)` behavior:
/// - If text length <= max_chars, return as-is.
/// - Otherwise, return first `max_chars` characters + `...`.
/// - No whitespace collapsing.
pub fn text_preview(text: &str, max_chars: usize) -> String {
    let char_count = text.chars().count();
    if char_count <= max_chars {
        return text.to_string();
    }
    let truncated: String = text.chars().take(max_chars).collect();
    format!("{truncated}...")
}

/// Full preview API mirroring Python's `preview(text, mode, first, last, marker)`.
///
/// - mode "chars": character-based truncation
/// - mode "lines": line-based truncation
/// - mode "full": no truncation (return as-is)
/// - first: number of chars/lines to include from the start
/// - last: when set, include last N chars/lines with a marker in between
/// - marker: custom marker string; None uses the default template
pub fn preview_full(
    text: &str,
    mode: &str,
    first: Option<usize>,
    last: Option<usize>,
    marker: Option<&str>,
) -> String {
    if mode == "full" || text.is_empty() {
        return text.to_string();
    }

    match mode {
        "chars" => {
            let first_n = first.unwrap_or(200);
            let char_count = text.chars().count();
            if char_count <= first_n {
                return text.to_string();
            }
            let first_part: String = text.chars().take(first_n).collect();
            if let Some(last_n) = last {
                if last_n > 0 && first_n + last_n >= char_count {
                    return text.to_string();
                }
                if last_n > 0 && char_count > first_n + last_n {
                    let last_part: String = text.chars().skip(char_count - last_n).collect();
                    let omitted = char_count - first_n - last_n;
                    let m = build_marker(omitted, "chars", marker);
                    return format!("{first_part}{m}{last_part}");
                }
            }
            let omitted = char_count - first_n;
            let m = build_marker(omitted, "chars", marker);
            format!("{first_part}{m}")
        }
        "lines" => {
            let first_n = first.unwrap_or(5);
            let lines: Vec<&str> = text.lines().collect();
            let line_count = lines.len();
            if line_count <= first_n {
                return text.to_string();
            }
            let first_part: String = lines[..first_n].join("\n");
            if let Some(last_n) = last {
                if last_n > 0 && first_n + last_n >= line_count {
                    return text.to_string();
                }
                if last_n > 0 && line_count > first_n + last_n {
                    let last_part: String = lines[line_count - last_n..].join("\n");
                    let omitted = line_count - first_n - last_n;
                    let m = build_marker(omitted, "lines", marker);
                    return format!("{first_part}\n{m}\n{last_part}");
                }
            }
            let omitted = line_count - first_n;
            let m = build_marker(omitted, "lines", marker);
            format!("{first_part}\n{m}")
        }
        _ => text.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_text_unchanged() {
        assert_eq!(text_preview("hello world", 100), "hello world");
    }

    #[test]
    fn long_text_truncated() {
        let out = text_preview("hello world foo bar baz", 10);
        assert_eq!(out, "hello worl...");
    }

    #[test]
    fn exact_boundary() {
        assert_eq!(text_preview("exact", 5), "exact");
    }

    #[test]
    fn one_over_boundary() {
        assert_eq!(text_preview("abcdef", 5), "abcde...");
    }

    #[test]
    fn preview_full_chars_first_only() {
        let out = preview_full("Hello world", "chars", Some(5), None, None);
        assert!(out.starts_with("Hello"));
        assert!(out.contains("chars abbr"));
    }

    #[test]
    fn preview_full_chars_head_tail() {
        let out = preview_full("abcdefghij", "chars", Some(2), Some(2), None);
        assert!(out.starts_with("ab"));
        assert!(out.ends_with("ij"));
        assert!(out.contains("chars abbr"));
    }

    #[test]
    fn preview_full_lines_head_tail() {
        let text = "L1\nL2\nL3\nL4\nL5\nL6";
        let out = preview_full(text, "lines", Some(1), Some(1), None);
        assert!(out.starts_with("L1"));
        assert!(out.ends_with("L6"));
        assert!(out.contains("lines abbr"));
    }

    #[test]
    fn preview_full_mode_returns_as_is() {
        assert_eq!(
            preview_full("anything", "full", None, None, None),
            "anything"
        );
    }

    #[test]
    fn preview_full_custom_marker() {
        let out = preview_full("abcdefghij", "chars", Some(2), None, Some("[CUT]"));
        assert_eq!(out, "ab[CUT]");
    }
}
