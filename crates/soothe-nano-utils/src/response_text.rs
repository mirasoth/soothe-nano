//! LLM response text extraction and JSON parsing.
//!
//! Pure-string helpers for normalizing model output: markdown-fence stripping,
//! brace-depth JSON extraction, and prose-prefix slicing.

use std::sync::OnceLock;

use regex::Regex;
use serde_json::Value;

/// Lazily-compiled markdown fence regex: `` ```json ... ``` `` or bare `` ``` ``.
///
/// Mirrors Python's ``r"```(?:json)?\s*\n?(.*?)\n?```"`` with DOTALL | IGNORECASE.
/// Group 1 captures the inner content.
fn json_fence_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        // (?is) = case-insensitive + dotall (dot matches newline)
        Regex::new(r"(?is)```(?:json)?\s*\n?(.*?)\n?```").unwrap()
    })
}

/// Normalize model output to a JSON-parseable string.
///
/// Strips markdown fences and, if prose precedes the first ``{``, slices to
/// that position. Returns the normalized string (caller parses it).
pub fn strip_json_text(raw: &str) -> String {
    let text = raw.trim();
    if text.is_empty() {
        return text.to_string();
    }

    // Check for a markdown fence.
    let text = if let Some(caps) = json_fence_re().captures(text) {
        if let Some(m) = caps.get(1) {
            m.as_str().trim()
        } else {
            text
        }
    } else {
        text
    };

    // If prose precedes the first `{`, slice it off.
    let start = text.find('{');
    match start {
        Some(idx) if idx > 0 => text[idx..].to_string(),
        _ => text.to_string(),
    }
}

/// Parse a JSON object from model output (raw or markdown-fenced).
///
/// Tries (in order):
/// 1. Markdown fence extraction → direct parse.
/// 2. Brace-depth matching to find the first balanced ``{...}``.
///
/// Returns ``Some(Value::Object(...))`` only when the result is a JSON object;
/// ``None`` otherwise.
pub fn parse_json_object(content: &str) -> Option<Value> {
    let text = content.trim();
    if text.is_empty() {
        return None;
    }

    // Step 1: try fence extraction + direct parse.
    let fenced = if let Some(caps) = json_fence_re().captures(text) {
        caps.get(1).map(|m| m.as_str().trim()).unwrap_or(text)
    } else {
        text
    };

    if let Ok(parsed) = serde_json::from_str::<Value>(fenced) {
        if parsed.is_object() {
            return Some(parsed);
        }
    }

    // Step 2: brace-depth matching — find the first balanced {...} object.
    let start = fenced.find('{')?;

    let bytes = fenced.as_bytes();
    let mut depth: i32 = 0;
    let mut in_string = false;
    let mut escape = false;
    let mut i = start;

    while i < bytes.len() {
        let ch = bytes[i];

        if in_string {
            if escape {
                escape = false;
            } else if ch == b'\\' {
                escape = true;
            } else if ch == b'"' {
                in_string = false;
            }
        } else {
            match ch {
                b'"' => in_string = true,
                b'{' => depth += 1,
                b'}' => {
                    depth -= 1;
                    if depth == 0 {
                        // Found a balanced object — try to parse it.
                        let candidate = &fenced[start..=i];
                        if let Ok(parsed) = serde_json::from_str::<Value>(candidate) {
                            if parsed.is_object() {
                                return Some(parsed);
                            }
                        }
                        // Unparseable balanced span — give up (matches Python's break).
                        return None;
                    }
                }
                _ => {}
            }
        }
        i += 1;
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // ── strip_json_text ──────────────────────────────────────────

    #[test]
    fn strip_plain_json() {
        assert_eq!(
            strip_json_text(r#"{"key": "value"}"#),
            r#"{"key": "value"}"#
        );
    }

    #[test]
    fn strip_fenced_json() {
        let raw = "```json\n{\"key\": \"value\"}\n```";
        assert_eq!(strip_json_text(raw), r#"{"key": "value"}"#);
    }

    #[test]
    fn strip_bare_fence() {
        let raw = "```\n{\"key\": \"value\"}\n```";
        assert_eq!(strip_json_text(raw), r#"{"key": "value"}"#);
    }

    #[test]
    fn strip_prose_prefix() {
        let raw = "Here is the JSON:\n{\"key\": \"value\"}";
        assert_eq!(strip_json_text(raw), r#"{"key": "value"}"#);
    }

    #[test]
    fn strip_empty() {
        assert_eq!(strip_json_text(""), "");
        assert_eq!(strip_json_text("   "), "");
    }

    #[test]
    fn strip_no_brace() {
        // No `{` at all — returned as-is (trimmed).
        assert_eq!(strip_json_text("just text"), "just text");
    }

    // ── parse_json_object ────────────────────────────────────────

    #[test]
    fn parse_raw_json() {
        let result = parse_json_object(r#"{"key": "value"}"#);
        assert_eq!(result, Some(json!({"key": "value"})));
    }

    #[test]
    fn parse_fenced_json() {
        let raw = "prefix\n```json\n{\"queries\": [{\"query\": \"test\"}]}\n```";
        let result = parse_json_object(raw);
        assert_eq!(result, Some(json!({"queries": [{"query": "test"}]})));
    }

    #[test]
    fn parse_bare_fence() {
        let raw = "```\n{\"x\": 1}\n```";
        let result = parse_json_object(raw);
        assert_eq!(result, Some(json!({"x": 1})));
    }

    #[test]
    fn parse_prose_prefix_brace_depth() {
        let raw = "Here is the JSON:\n{\"key\": \"value\"}";
        let result = parse_json_object(raw);
        assert_eq!(result, Some(json!({"key": "value"})));
    }

    #[test]
    fn parse_nested_braces() {
        let raw = "blah {\"outer\": {\"inner\": 1}} trailing";
        let result = parse_json_object(raw);
        assert_eq!(result, Some(json!({"outer": {"inner": 1}})));
    }

    #[test]
    fn parse_empty() {
        assert_eq!(parse_json_object(""), None);
        assert_eq!(parse_json_object("   "), None);
    }

    #[test]
    fn parse_no_json() {
        assert_eq!(parse_json_object("just plain text"), None);
    }

    #[test]
    fn parse_array_not_object() {
        // An array is not a dict — should return None.
        assert_eq!(parse_json_object("[1, 2, 3]"), None);
    }

    #[test]
    fn parse_brace_in_string_ignored() {
        // A `{` inside a JSON string should not affect brace-depth counting.
        let raw = r#"{"msg": "hello {world}"}"#;
        let result = parse_json_object(raw);
        assert_eq!(result, Some(json!({"msg": "hello {world}"})));
    }

    #[test]
    fn parse_fenced_with_prose_prefix() {
        let raw = "Here:\n```json\n{\"a\": 1}\n```\nignored";
        let result = parse_json_object(raw);
        assert_eq!(result, Some(json!({"a": 1})));
    }

    #[test]
    fn parse_case_insensitive_fence() {
        let raw = "```JSON\n{\"a\": 1}\n```";
        let result = parse_json_object(raw);
        assert_eq!(result, Some(json!({"a": 1})));
    }
}
