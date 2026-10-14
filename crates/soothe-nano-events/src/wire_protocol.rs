//! Wire protocol helpers for `soothe.subagent.*` event types.

use std::collections::HashMap;
use std::sync::OnceLock;

use regex::Regex;

/// Compiled regex for `soothe.subagent.<agent>.<signal>` curated wire types.
static CURATED_RE: OnceLock<Regex> = OnceLock::new();

fn curated_re() -> &'static Regex {
    CURATED_RE.get_or_init(|| {
        Regex::new(r"^soothe\.subagent\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]+$").unwrap()
    })
}

/// Return true for structurally valid curated `soothe.subagent.*` wire types.
pub fn is_curated_subagent_wire_event_type(event_type: &str) -> bool {
    curated_re().is_match(event_type)
}

/// Return the agent segment from `soothe.subagent.<agent>.…`, or `None`.
pub fn parse_subagent_wire_agent(event_type: &str) -> Option<String> {
    let parts: Vec<&str> = event_type.split('.').collect();
    if parts.len() >= 4 && parts[0] == "soothe" && parts[1] == "subagent" {
        Some(parts[2].to_string())
    } else {
        None
    }
}

/// Truncate a single wire string field.
///
/// If `value` fits within `max_len`, return it unchanged. If `max_len <= 1`,
/// return `"…"`. Otherwise return `value[..max_len-1] + "…"`.
pub fn truncate_wire_str(value: &str, max_len: usize) -> String {
    if value.chars().count() <= max_len {
        return value.to_string();
    }
    if max_len <= 1 {
        return "…".to_string();
    }
    let prefix: String = value.chars().take(max_len - 1).collect();
    format!("{prefix}…")
}

/// Per-field string length caps for wire payload clipping.
fn string_caps() -> &'static [(&'static str, usize)] {
    static CAPS: OnceLock<Vec<(&'static str, usize)>> = OnceLock::new();
    CAPS.get_or_init(|| {
        vec![
            ("task_preview", 200),
            ("topic", 200),
            ("topic_preview", 120),
            ("search_target", 8000),
            ("task", 200),
            ("judgement", 200),
            ("message", 200),
            ("error", 200),
            ("action_preview", 120),
            ("tool_name", 120),
            ("input_preview", 120),
            ("summary", 200),
            ("url", 200),
            ("title", 120),
            ("query_preview", 120),
            ("args_preview", 120),
            ("result_preview", 120),
        ]
    })
}

/// Copy the map and truncate known string fields for wire safety.
pub fn clip_wire_event_payload(data: &HashMap<String, String>) -> HashMap<String, String> {
    let mut out = data.clone();
    for (key, cap) in string_caps() {
        if let Some(val) = out.get(*key) {
            if val.chars().count() > *cap {
                out.insert((*key).to_string(), truncate_wire_str(val, *cap));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── is_curated_subagent_wire_event_type ──────────────────────

    #[test]
    fn curated_valid_types() {
        assert!(is_curated_subagent_wire_event_type(
            "soothe.subagent.browser.started"
        ));
        assert!(is_curated_subagent_wire_event_type(
            "soothe.subagent.claude.tool.start"
        ));
        assert!(is_curated_subagent_wire_event_type(
            "soothe.subagent.research_2.gather.summary"
        ));
    }

    #[test]
    fn curated_rejects_invalid_types() {
        assert!(!is_curated_subagent_wire_event_type(
            "soothe.subagent.browser"
        ));
        assert!(!is_curated_subagent_wire_event_type(
            "soothe.subagent.Browser.started"
        ));
        assert!(!is_curated_subagent_wire_event_type(
            "soothe.cognition.llm.started"
        ));
        assert!(!is_curated_subagent_wire_event_type(""));
        assert!(!is_curated_subagent_wire_event_type(
            "soothe.subagent..started"
        ));
        assert!(!is_curated_subagent_wire_event_type(
            "soothe.subagent.1agent.started"
        ));
    }

    // ── parse_subagent_wire_agent ────────────────────────────────

    #[test]
    fn parse_valid_agent() {
        assert_eq!(
            parse_subagent_wire_agent("soothe.subagent.browser.started"),
            Some("browser".to_string())
        );
        assert_eq!(
            parse_subagent_wire_agent("soothe.subagent.deep_research.completed.summary"),
            Some("deep_research".to_string())
        );
    }

    #[test]
    fn parse_returns_none_for_invalid() {
        assert_eq!(parse_subagent_wire_agent("soothe.subagent.browser"), None);
        assert_eq!(
            parse_subagent_wire_agent("soothe.cognition.llm.started"),
            None
        );
        assert_eq!(parse_subagent_wire_agent("subagent.browser.started"), None);
        assert_eq!(parse_subagent_wire_agent(""), None);
    }

    // ── truncate_wire_str ────────────────────────────────────────

    #[test]
    fn truncate_short_value_unchanged() {
        assert_eq!(truncate_wire_str("hello", 10), "hello");
        assert_eq!(truncate_wire_str("hello", 5), "hello");
    }

    #[test]
    fn truncate_long_value() {
        let result = truncate_wire_str("hello world", 8);
        assert_eq!(result, "hello w…");
        assert_eq!(result.chars().count(), 8);
    }

    #[test]
    fn truncate_max_len_zero_or_one() {
        assert_eq!(truncate_wire_str("hello", 1), "…");
        assert_eq!(truncate_wire_str("hello", 0), "…");
    }

    #[test]
    fn truncate_multibyte_safe() {
        // 5 CJK chars = 15 bytes; truncate at 3 chars.
        let value = "你好世界吗";
        let result = truncate_wire_str(value, 3);
        assert_eq!(result, "你好…");
        assert_eq!(result.chars().count(), 3);
    }

    // ── clip_wire_event_payload ──────────────────────────────────

    #[test]
    fn clip_truncates_known_fields() {
        let mut data = HashMap::new();
        data.insert("task".to_string(), "x".repeat(300));
        data.insert("topic_preview".to_string(), "y".repeat(200));
        data.insert("url".to_string(), "http://short".to_string());

        let clipped = clip_wire_event_payload(&data);

        assert_eq!(clipped.get("task").unwrap().chars().count(), 200);
        assert!(clipped.get("task").unwrap().ends_with('…'));
        assert_eq!(clipped.get("topic_preview").unwrap().chars().count(), 120);
        assert!(clipped.get("topic_preview").unwrap().ends_with('…'));
        // Short value unchanged.
        assert_eq!(clipped.get("url").unwrap(), "http://short");
    }

    #[test]
    fn clip_preserves_unknown_fields() {
        let mut data = HashMap::new();
        data.insert("custom_field".to_string(), "x".repeat(500));
        data.insert("task".to_string(), "x".repeat(300));

        let clipped = clip_wire_event_payload(&data);

        assert_eq!(clipped.get("custom_field").unwrap().chars().count(), 500);
        assert_eq!(clipped.get("task").unwrap().chars().count(), 200);
    }

    #[test]
    fn clip_does_not_mutate_input() {
        let mut data = HashMap::new();
        data.insert("task".to_string(), "x".repeat(300));

        let _ = clip_wire_event_payload(&data);

        assert_eq!(data.get("task").unwrap().chars().count(), 300);
    }

    #[test]
    fn clip_search_target_has_large_cap() {
        let mut data = HashMap::new();
        data.insert("search_target".to_string(), "x".repeat(9000));

        let clipped = clip_wire_event_payload(&data);

        assert_eq!(clipped.get("search_target").unwrap().chars().count(), 8000);
        assert!(clipped.get("search_target").unwrap().ends_with('…'));
    }

    #[test]
    fn clip_empty_map() {
        let data = HashMap::new();
        let clipped = clip_wire_event_payload(&data);
        assert!(clipped.is_empty());
    }
}
