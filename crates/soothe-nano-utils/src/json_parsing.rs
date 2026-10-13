//! JSON extraction and repair (ported from `utils/json_parsing.py`).
//!
//! Tolerates markdown fences, leading/trailing prose, trailing commas,
//! and truncated (cut-off) JSON by closing unclosed strings and brackets.

use serde_json::Value;

/// Extract a JSON value from raw text that may contain markdown fences,
/// leading/trailing prose, trailing commas, or truncated content.
pub fn repair_json(raw: &str) -> Option<Value> {
    let stripped = strip_leading_bom(raw);
    let fenced = strip_markdown_json_fence(&stripped);
    let trimmed = fenced.trim();

    if trimmed.is_empty() {
        return None;
    }

    // Candidate 1: the full trimmed string.
    if let Some(v) = try_parse_value(trimmed) {
        return Some(v);
    }

    // Candidate 2: balanced-brace extraction (string-aware).
    if let Some(balanced) = extract_balanced_json_object(trimmed) {
        if let Some(v) = try_parse_value(&balanced) {
            return Some(v);
        }
    }

    // Candidate 3: find first `{` or `[` and parse from there.
    if let Some(start) = trimmed.find('{').or_else(|| trimmed.find('[')) {
        let fragment = &trimmed[start..];
        if let Some(v) = try_parse_value(fragment) {
            return Some(v);
        }

        // Candidate 4: repair truncated JSON (close unclosed brackets/strings).
        let repaired = repair_truncated_json(fragment);
        if repaired != fragment {
            if let Some(v) = try_parse_value(&repaired) {
                return Some(v);
            }
        }
    }

    None
}

/// Remove UTF-8 BOM if present.
fn strip_leading_bom(text: &str) -> String {
    text.trim_start_matches('\u{feff}').to_string()
}

/// Extract JSON from ````json ... ```` or generic ``` ... ``` fenced blocks.
fn strip_markdown_json_fence(response: &str) -> String {
    let s = response.trim();

    if let Some(idx) = s.find("```json") {
        let start = idx + 7;
        if let Some(end) = s[start..].find("```") {
            return s[start..start + end].trim().to_string();
        }
    } else if s.contains("```") {
        let start = s.find("```").unwrap() + 3;
        // Skip optional language tag on the fence line.
        let start = match s[start..].find('\n') {
            Some(nl) if nl < 30 => start + nl + 1,
            _ => start,
        };
        if let Some(end) = s[start..].find("```") {
            return s[start..start + end].trim().to_string();
        }
    }

    s.to_string()
}

/// Return the substring from first `{` through its matching `}`, string-aware.
///
/// Avoids greedy `{.*}` mistakes when strings contain `}` or when prose follows JSON.
fn extract_balanced_json_object(text: &str) -> Option<String> {
    let start = text.find('{')?;
    let bytes = text.as_bytes();
    let mut depth = 0i32;
    let mut in_string = false;
    let mut backslash = false;
    let mut i = start;

    while i < text.len() {
        let c = bytes[i] as char;
        if backslash {
            backslash = false;
        } else if in_string {
            if c == '\\' {
                backslash = true;
            } else if c == '"' {
                in_string = false;
            }
        } else if c == '"' {
            in_string = true;
        } else if c == '{' {
            depth += 1;
        } else if c == '}' {
            depth -= 1;
            if depth == 0 {
                return Some(text[start..=i].to_string());
            }
        }
        i += 1;
    }
    None
}

/// Remove JSON trailing commas (`,}` / `,]`) outside of string literals.
fn strip_trailing_commas_json(text: &str) -> String {
    let bytes = text.as_bytes();
    let n = bytes.len();
    let mut out = String::with_capacity(n);
    let mut in_string = false;
    let mut backslash = false;
    let mut i = 0;

    while i < n {
        let c = bytes[i] as char;
        if backslash {
            out.push(c);
            backslash = false;
            i += 1;
            continue;
        }
        if in_string {
            if c == '\\' {
                backslash = true;
                out.push(c);
            } else if c == '"' {
                in_string = false;
                out.push(c);
            } else {
                out.push(c);
            }
            i += 1;
            continue;
        }
        if c == '"' {
            in_string = true;
            out.push(c);
            i += 1;
            continue;
        }
        if c == ',' {
            // Look ahead past whitespace for `}` or `]`.
            let mut j = i + 1;
            while j < n && (bytes[j] as char).is_whitespace() {
                j += 1;
            }
            if j < n && (bytes[j] as char == '}' || bytes[j] as char == ']') {
                i += 1;
                continue;
            }
        }
        out.push(c);
        i += 1;
    }
    out
}

/// Repair truncated JSON by closing unclosed strings and brackets.
fn repair_truncated_json(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut bracket_stack: Vec<char> = Vec::new();
    let mut in_string = false;
    let mut backslash = false;
    let mut last_char = ' ';

    for &b in bytes {
        let c = b as char;
        if backslash {
            backslash = false;
        } else if in_string {
            if c == '\\' {
                backslash = true;
            } else if c == '"' {
                in_string = false;
            }
        } else if c == '"' {
            in_string = true;
        } else if c == '{' || c == '[' {
            bracket_stack.push(c);
        } else if (c == '}' && bracket_stack.last() == Some(&'{'))
            || (c == ']' && bracket_stack.last() == Some(&'['))
        {
            bracket_stack.pop();
        }
        last_char = c;
    }

    let mut repair = String::new();

    if in_string {
        repair.push('"');
    }

    while let Some(open) = bracket_stack.pop() {
        if open == '{' {
            repair.push('}');
        } else if open == '[' {
            repair.push(']');
        }
    }

    let base = if last_char == ',' {
        &text[..text.len() - 1]
    } else {
        text
    };
    format!("{base}{repair}")
}

/// Try to parse a string as JSON, with trailing-comma stripping fallback.
fn try_parse_value(raw: &str) -> Option<Value> {
    if let Ok(v) = serde_json::from_str::<Value>(raw) {
        return Some(v);
    }
    let relaxed = strip_trailing_commas_json(raw);
    if relaxed != raw {
        if let Ok(v) = serde_json::from_str::<Value>(&relaxed) {
            return Some(v);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn direct_parse() {
        let v = repair_json(r#"{"a": 1}"#).unwrap();
        assert_eq!(v["a"], 1);
    }

    #[test]
    fn fenced_json() {
        let v = repair_json("```json\n{\"b\": 2}\n```").unwrap();
        assert_eq!(v["b"], 2);
    }

    #[test]
    fn leading_prose() {
        let v = repair_json("Here is the result: {\"c\": 3}").unwrap();
        assert_eq!(v["c"], 3);
    }

    #[test]
    fn invalid_returns_none() {
        assert!(repair_json("not json at all").is_none());
    }

    #[test]
    fn trailing_comma() {
        let v = repair_json(r#"{"a": 1,}"#).unwrap();
        assert_eq!(v["a"], 1);
    }

    #[test]
    fn truncated_object() {
        let v = repair_json(r#"{"key": "value""#).unwrap();
        assert_eq!(v["key"], "value");
    }

    #[test]
    fn truncated_with_comma() {
        let v = repair_json(r#"{"key": "value","#).unwrap();
        assert_eq!(v["key"], "value");
    }

    #[test]
    fn truncated_nested() {
        let v = repair_json(r#"{"outer": {"inner": 42"#).unwrap();
        assert_eq!(v["outer"]["inner"], 42);
    }

    #[test]
    fn truncated_string() {
        let v = repair_json(r#"{"key": "val"#).unwrap();
        assert_eq!(v["key"], "val");
    }

    #[test]
    fn prose_after_json() {
        let v = repair_json(r#"{"a": 1} and some prose"#).unwrap();
        assert_eq!(v["a"], 1);
    }

    #[test]
    fn generic_fence() {
        let v = repair_json("```\n{\"x\": 99}\n```").unwrap();
        assert_eq!(v["x"], 99);
    }

    #[test]
    fn bom_prefix() {
        let v = repair_json("\u{feff}{\"bom\": true}").unwrap();
        assert_eq!(v["bom"], true);
    }

    #[test]
    fn broken_key_returns_none() {
        // "broken" is not a valid key — serde_json can't repair this.
        assert!(repair_json(r#"{"key": "value", broken}"#).is_none());
    }
}
