//! Text preview with truncation.

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

/// Truncate `text` to `max_chars` characters with `...` appended.
pub fn text_preview(text: &str, max_chars: usize) -> String {
    let char_count = text.chars().count();
    if char_count <= max_chars {
        return text.to_string();
    }
    let truncated: String = text.chars().take(max_chars).collect();
    format!("{truncated}...")
}

/// Full preview API.
///
/// Modes: `"chars"` (character-based), `"lines"` (line-based), `"full"` (no truncation).
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
    fn text_preview_short() {
        assert_eq!(text_preview("hello", 10), "hello");
    }

    #[test]
    fn text_preview_truncates() {
        assert_eq!(text_preview("hello world", 5), "hello...");
    }

    #[test]
    fn preview_full_mode_full() {
        assert_eq!(preview_full("hello", "full", None, None, None), "hello");
    }

    #[test]
    fn preview_full_chars_with_last() {
        let text = "abcdefghij";
        let result = preview_full(text, "chars", Some(3), Some(3), None);
        assert!(result.contains("abc"));
        assert!(result.contains("hij"));
    }

    #[test]
    fn preview_full_lines() {
        let text = "line1\nline2\nline3\nline4\nline5\nline6";
        let result = preview_full(text, "lines", Some(2), Some(1), None);
        assert!(result.contains("line1"));
        assert!(result.contains("line6"));
    }
}
