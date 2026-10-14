//! JSON extraction and repair (ported from `utils/json_parsing.py`).

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

    if let Some(v) = try_parse_value(trimmed) {
        return Some(v);
    }

    if let Some(balanced) = extract_balanced_json_object(trimmed) {
        if let Some(v) = try_parse_value(&balanced) {
            return Some(v);
        }
    }

    if let Some(start) = trimmed.find('{').or_else(|| trimmed.find('[')) {
        let fragment = &trimmed[start..];
        if let Some(v) = try_parse_value(fragment) {
            return Some(v);
        }

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

    // If we ran out of text with unclosed braces, return what we have.
    if depth > 0 {
        Some(text[start..].to_string())
    } else {
        None
    }
}

/// Try to parse a string as JSON, removing trailing commas first.
fn try_parse_value(s: &str) -> Option<Value> {
    let cleaned = remove_trailing_commas(s);
    serde_json::from_str(&cleaned).ok()
}

/// Remove trailing commas before `}` or `]`.
fn remove_trailing_commas(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    let chars: Vec<char> = s.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == ',' {
            // Look ahead for the next non-whitespace char.
            let mut j = i + 1;
            while j < chars.len() && chars[j].is_whitespace() {
                j += 1;
            }
            if j < chars.len() && (chars[j] == '}' || chars[j] == ']') {
                // Skip the comma.
                i += 1;
                continue;
            }
        }
        result.push(chars[i]);
        i += 1;
    }
    result
}

/// Repair truncated JSON by closing unclosed strings and brackets.
fn repair_truncated_json(s: &str) -> String {
    let mut result = String::with_capacity(s.len() + 16);
    let mut in_string = false;
    let mut backslash = false;
    let mut brace_stack: Vec<char> = Vec::new();

    for c in s.chars() {
        if backslash {
            result.push(c);
            backslash = false;
            continue;
        }
        if in_string {
            result.push(c);
            if c == '\\' {
                backslash = true;
            } else if c == '"' {
                in_string = false;
            }
            continue;
        }
        match c {
            '"' => {
                in_string = true;
                result.push(c);
            }
            '{' | '[' => {
                brace_stack.push(c);
                result.push(c);
            }
            '}' | ']' => {
                brace_stack.pop();
                result.push(c);
            }
            _ => result.push(c),
        }
    }

    // Close any open string.
    if in_string {
        result.push('"');
    }

    // Close brackets in reverse order.
    while let Some(open) = brace_stack.pop() {
        match open {
            '{' => result.push('}'),
            '[' => result.push(']'),
            _ => {}
        }
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_clean_json() {
        let v = repair_json(r#"{"key": "value"}"#).unwrap();
        assert_eq!(v["key"], "value");
    }

    #[test]
    fn parse_with_prose() {
        let v = repair_json(r#"Here is the result: {"key": "value"} done"#).unwrap();
        assert_eq!(v["key"], "value");
    }

    #[test]
    fn parse_markdown_fenced() {
        let v = repair_json("```json\n{\"key\": \"value\"}\n```").unwrap();
        assert_eq!(v["key"], "value");
    }

    #[test]
    fn parse_trailing_comma() {
        let v = repair_json(r#"{"key": "value",}"#).unwrap();
        assert_eq!(v["key"], "value");
    }

    #[test]
    fn parse_truncated() {
        let v = repair_json(r#"{"key": "val"#).unwrap();
        assert_eq!(v["key"], "val");
    }

    #[test]
    fn parse_empty_returns_none() {
        assert!(repair_json("").is_none());
    }

    #[test]
    fn parse_bom() {
        let v = repair_json("\u{feff}{\"key\": \"value\"}").unwrap();
        assert_eq!(v["key"], "value");
    }

    #[test]
    fn parse_array() {
        let v = repair_json(r#"[1, 2, 3]"#).unwrap();
        assert_eq!(v[0], 1);
    }

    #[test]
    fn parse_nested_with_trailing_comma() {
        let v = repair_json(r#"{"a": {"b": 1,},}"#).unwrap();
        assert_eq!(v["a"]["b"], 1);
    }

    #[test]
    fn parse_truncated_array() {
        let v = repair_json(r#"[1, 2, 3"#).unwrap();
        assert_eq!(v[2], 3);
    }
}
