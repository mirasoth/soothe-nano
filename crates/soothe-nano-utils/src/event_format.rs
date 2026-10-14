//! Compact progress-event formatting.

/// Maximum field length before truncation in compact event formatting.
const MAX_FIELD_LEN: usize = 50;

/// Key fields extracted from events in priority order for compact formatting.
const KEY_FIELDS: &[&str] = &[
    "tool",
    "tool_name",
    "command",
    "url",
    "action_preview",
    "exit_code",
    "duration_ms",
    "error",
    "timeout",
    "pid",
    "session_id",
    "success",
];

/// Format an event dict into a compact, readable string.
///
/// Extracts key fields and formats them concisely:
/// - Shortens event type (removes `soothe.` prefix)
/// - Shows important fields based on event type
/// - Truncates long string values
///
/// `event` is a list of `(key, value_string, value_is_str)` tuples where
/// `value_is_str` indicates whether the original value was a string
/// (so we know whether to apply string truncation logic). Non-string values
/// are formatted as-is via `to_string()`.
pub fn format_event_compact(event: &[(String, String, bool)]) -> String {
    let mut event_type = "unknown".to_string();
    let mut parts: Vec<String> = Vec::new();

    for (key, val, _is_str) in event {
        if key == "type" {
            event_type = val.clone();
            continue;
        }
    }

    // Shorten type: "soothe.tool.execution.commandStarted" -> "tool.execution.commandStarted"
    let short_type = event_type
        .strip_prefix("soothe.")
        .unwrap_or(&event_type)
        .to_string();
    parts.push(short_type);

    for field in KEY_FIELDS {
        for (key, val, is_str) in event {
            if key != field {
                continue;
            }
            // Skip empty/None values.
            if val.is_empty() {
                continue;
            }
            if *field == "duration_ms" {
                parts.push(format!("duration={val}ms"));
            } else if *is_str && val.chars().count() > MAX_FIELD_LEN {
                let prefix: String = val.chars().take(MAX_FIELD_LEN - 3).collect();
                parts.push(format!("{field}={prefix}..."));
            } else {
                parts.push(format!("{field}={val}"));
            }
        }
    }

    parts.join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ev(entries: &[(&str, &str, bool)]) -> Vec<(String, String, bool)> {
        entries
            .iter()
            .map(|(k, v, s)| (k.to_string(), v.to_string(), *s))
            .collect()
    }

    #[test]
    fn basic_type_shortening() {
        let event = ev(&[("type", "soothe.tool.execution.commandStarted", true)]);
        let result = format_event_compact(&event);
        assert!(result.starts_with("tool.execution.commandStarted"));
    }

    #[test]
    fn non_soothe_type_preserved() {
        let event = ev(&[("type", "custom.event", true)]);
        let result = format_event_compact(&event);
        assert!(result.starts_with("custom.event"));
    }

    #[test]
    fn unknown_type_when_missing() {
        let event: Vec<(String, String, bool)> = vec![];
        let result = format_event_compact(&event);
        assert!(result.starts_with("unknown"));
    }

    #[test]
    fn key_field_extraction() {
        let event = ev(&[
            ("type", "soothe.tool.exec", true),
            ("tool", "run_command", true),
            ("exit_code", "0", true),
        ]);
        let result = format_event_compact(&event);
        assert!(result.contains("tool=run_command"));
        assert!(result.contains("exit_code=0"));
    }

    #[test]
    fn duration_ms_formatted() {
        let event = ev(&[
            ("type", "soothe.tool.exec", true),
            ("duration_ms", "150", true),
        ]);
        let result = format_event_compact(&event);
        assert!(result.contains("duration=150ms"));
    }

    #[test]
    fn long_string_truncated() {
        let long = "x".repeat(60);
        let event = ev(&[("type", "soothe.tool.exec", true), ("command", &long, true)]);
        let result = format_event_compact(&event);
        assert!(result.contains("command="));
        assert!(result.contains("..."));
        // The truncated value should be 47 chars + "..."
        let truncated_len = MAX_FIELD_LEN - 3;
        assert!(result.contains(&"x".repeat(truncated_len)));
    }

    #[test]
    fn empty_values_skipped() {
        let event = ev(&[
            ("type", "soothe.tool.exec", true),
            ("tool", "", true),
            ("exit_code", "0", true),
        ]);
        let result = format_event_compact(&event);
        assert!(!result.contains("tool="));
        assert!(result.contains("exit_code=0"));
    }

    #[test]
    fn non_string_value_not_truncated() {
        // Non-string values (is_str=false) are formatted as-is, no truncation.
        let long = "y".repeat(60);
        let event = ev(&[("type", "soothe.tool.exec", true), ("pid", &long, false)]);
        let result = format_event_compact(&event);
        // PID is non-string → full value shown.
        assert!(result.contains(&long));
    }
}
