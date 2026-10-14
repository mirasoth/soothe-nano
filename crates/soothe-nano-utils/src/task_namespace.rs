//! Task-tool namespace parsing (ported from `ux/task_namespace.py`).
//!
//! Pure string ops for the unified tool_call_id format
//! ``{step_wire}:{type}:{tool}:{idx}``.

/// Parsed components of a unified tool_call_id.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedUnifiedToolCallId {
    pub step_id: String,
    pub type_code: String,
    pub task_idx: Option<i32>,
    pub tool_info: String,
}

impl ParsedUnifiedToolCallId {
    /// Non-unified or empty id sentinel. ``tool_info`` defaults to empty.
    pub fn empty() -> Self {
        Self::empty_with_tool_info("")
    }

    /// Non-unified id sentinel preserving the raw id in ``tool_info``.
    pub fn empty_with_tool_info(tool_info: &str) -> Self {
        ParsedUnifiedToolCallId {
            step_id: String::new(),
            type_code: String::new(),
            task_idx: None,
            tool_info: tool_info.to_string(),
        }
    }
}

/// Map execute step ids (``GHT-01``) to the unified wire fragment (``GHT_01``).
pub fn step_id_to_unified_fragment(step_id: &str) -> String {
    step_id.trim().replace('-', "_")
}

/// Map unified wire step fragment back to canonical execute step id.
pub fn step_id_from_unified_fragment(fragment: &str) -> String {
    fragment.trim().replace('_', "-")
}

/// True when the first segment uses underscore wire form (``GHT_01``).
pub fn is_wire_step_fragment(fragment: &str) -> bool {
    let text = fragment.trim();
    !text.is_empty() && text.contains('_') && !text.contains('-')
}

/// Parse provider ``tool:idx`` into unified ``tool:idx`` fragment.
///
/// If ``:`` is present, split at the last ``:``; when the suffix is all digits
/// and the name is non-empty, return ``{name}:{idx}``. Otherwise return the
/// trimmed text unchanged.
pub fn provider_tool_fragment(tid: &str) -> String {
    let text = tid.trim();
    if text.is_empty() {
        return text.to_string();
    }
    if let Some((name, idx)) = text.rsplit_once(':') {
        if !name.is_empty() && !idx.is_empty() && idx.chars().all(|c| c.is_ascii_digit()) {
            return format!("{name}:{idx}");
        }
    }
    text.to_string()
}

/// Extract tool_info from colon segments after the type segment.
///
/// Returns everything after ``parts[1]`` joined by ``":"``. The canonical wire
/// form is ``{name}:{idx}`` (e.g. ``grep:0``), but providers that stamp opaque
/// call ids without an ``:idx`` suffix are preserved verbatim.
pub fn tool_info_from_unified_parts(parts: &[&str]) -> String {
    if parts.len() >= 3 {
        parts[2..].join(":").trim().to_string()
    } else {
        String::new()
    }
}

/// Build canonical unified id: ``{step_wire}:{type}:{tool}:{idx}``.
pub fn format_unified_tool_call_id(step_id: &str, type_part: &str, tool_fragment: &str) -> String {
    let sid_wire = step_id_to_unified_fragment(step_id);
    let frag = provider_tool_fragment(tool_fragment);
    format!("{sid_wire}:{type_part}:{frag}")
}

/// Parse unified tool_call_id format into components.
///
/// Recognition rules (in order):
/// 1. The id must contain at least three colon-separated segments.
/// 2. ``parts[0]`` must be a wire step fragment (underscore form, no hyphen).
/// 3. ``parts[1]`` must be ``s`` (step-level) or ``t{N}`` (task-level).
/// 4. Everything after ``parts[1]`` is the tool_info, joined by ``":"``.
///
/// Non-unified ids use empty step_id/type_code and preserve the raw id in
/// tool_info.
pub fn parse_unified_tool_call_id(tool_call_id: &str) -> ParsedUnifiedToolCallId {
    let tid = tool_call_id.trim();
    if tid.is_empty() {
        return ParsedUnifiedToolCallId::empty();
    }

    let parts: Vec<&str> = tid.split(':').collect();
    if parts.len() < 3 || !is_wire_step_fragment(parts[0]) {
        return ParsedUnifiedToolCallId::empty_with_tool_info(tid);
    }

    let type_part = parts[1];
    let type_code;
    let task_idx: Option<i32>;
    if type_part == "s" {
        type_code = "s".to_string();
        task_idx = None;
    } else if type_part.starts_with('t') && type_part.len() > 1 {
        match type_part[1..].parse::<i32>() {
            Ok(idx) => {
                task_idx = Some(idx);
                type_code = "t".to_string();
            }
            Err(_) => return ParsedUnifiedToolCallId::empty_with_tool_info(tid),
        }
    } else {
        return ParsedUnifiedToolCallId::empty_with_tool_info(tid);
    }

    let tool_info = tool_info_from_unified_parts(&parts);
    if tool_info.is_empty() {
        return ParsedUnifiedToolCallId::empty_with_tool_info(tid);
    }

    let step_id = step_id_from_unified_fragment(parts[0]);
    ParsedUnifiedToolCallId {
        step_id,
        type_code,
        task_idx,
        tool_info,
    }
}

/// Return True when ``tool_call_id`` matches the canonical unified wire format.
pub fn is_unified_tool_call_id(tool_call_id: &str) -> bool {
    let parsed = parse_unified_tool_call_id(tool_call_id);
    !parsed.step_id.is_empty()
        && (parsed.type_code == "s" || parsed.type_code == "t")
        && !parsed.tool_info.is_empty()
}

/// Shorten provider tool_call_id to ``tool:idx`` for unified id assembly.
///
/// Accepts provider ids (``functions.grep:0``). Already-unified ids yield their
/// tool fragment via [`parse_unified_tool_call_id`].
pub fn shorten_tool_call_id(raw_tid: &str) -> String {
    let tid = raw_tid.trim();
    let parsed = parse_unified_tool_call_id(tid);
    if !parsed.step_id.is_empty()
        && (parsed.type_code == "s" || parsed.type_code == "t")
        && !parsed.tool_info.is_empty()
    {
        return parsed.tool_info;
    }
    let stripped = tid.strip_prefix("functions.").unwrap_or(tid);
    provider_tool_fragment(stripped)
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── step_id_to_unified_fragment ──────────────────────────────

    #[test]
    fn fragment_replaces_hyphen_with_underscore() {
        assert_eq!(step_id_to_unified_fragment("GHT-01"), "GHT_01");
    }

    #[test]
    fn fragment_strips_whitespace() {
        assert_eq!(step_id_to_unified_fragment("  GHT-01  "), "GHT_01");
    }

    #[test]
    fn fragment_no_hyphen_unchanged() {
        assert_eq!(step_id_to_unified_fragment("GHT_01"), "GHT_01");
    }

    #[test]
    fn fragment_empty_string() {
        assert_eq!(step_id_to_unified_fragment(""), "");
    }

    // ── step_id_from_unified_fragment ────────────────────────────

    #[test]
    fn from_fragment_replaces_underscore_with_hyphen() {
        assert_eq!(step_id_from_unified_fragment("GHT_01"), "GHT-01");
    }

    #[test]
    fn from_fragment_strips_whitespace() {
        assert_eq!(step_id_from_unified_fragment("  GHT_01  "), "GHT-01");
    }

    #[test]
    fn from_fragment_no_underscore_unchanged() {
        assert_eq!(step_id_from_unified_fragment("GHT-01"), "GHT-01");
    }

    // ── is_wire_step_fragment ────────────────────────────────────

    #[test]
    fn wire_fragment_valid() {
        assert!(is_wire_step_fragment("GHT_01"));
    }

    #[test]
    fn wire_fragment_rejects_hyphen() {
        assert!(!is_wire_step_fragment("GHT-01"));
    }

    #[test]
    fn wire_fragment_rejects_empty() {
        assert!(!is_wire_step_fragment(""));
    }

    #[test]
    fn wire_fragment_rejects_no_underscore() {
        assert!(!is_wire_step_fragment("GHT01"));
    }

    #[test]
    fn wire_fragment_strips_whitespace() {
        assert!(is_wire_step_fragment("  GHT_01  "));
    }

    // ── provider_tool_fragment ───────────────────────────────────

    #[test]
    fn provider_fragment_with_idx() {
        assert_eq!(provider_tool_fragment("grep:0"), "grep:0");
    }

    #[test]
    fn provider_fragment_functions_prefix_preserved() {
        // Note: _provider_tool_fragment does NOT strip functions. — that's
        // _shorten_tool_call_id's job.
        assert_eq!(
            provider_tool_fragment("functions.grep:0"),
            "functions.grep:0"
        );
    }

    #[test]
    fn provider_fragment_non_digit_idx_unchanged() {
        assert_eq!(provider_tool_fragment("tool-abc"), "tool-abc");
    }

    #[test]
    fn provider_fragment_opaque_uuid_preserved() {
        assert_eq!(
            provider_tool_fragment("tool-550e8400-e29b-41d4-a716-446655440000"),
            "tool-550e8400-e29b-41d4-a716-446655440000"
        );
    }

    #[test]
    fn provider_fragment_empty() {
        assert_eq!(provider_tool_fragment(""), "");
    }

    #[test]
    fn provider_fragment_last_colon_split() {
        assert_eq!(provider_tool_fragment("a:b:0"), "a:b:0");
    }

    #[test]
    fn provider_fragment_non_digit_suffix_unchanged() {
        assert_eq!(provider_tool_fragment("call_abc:xyz"), "call_abc:xyz");
    }

    #[test]
    fn provider_fragment_empty_name_rejected() {
        // rpartition(":") with name="" → Python returns text unchanged.
        assert_eq!(provider_tool_fragment(":0"), ":0");
    }

    // ── tool_info_from_unified_parts ─────────────────────────────

    #[test]
    fn tool_info_joins_after_type() {
        let parts = vec!["GHT_01", "s", "grep", "0"];
        assert_eq!(tool_info_from_unified_parts(&parts), "grep:0");
    }

    #[test]
    fn tool_info_too_few_parts_empty() {
        let parts = vec!["GHT_01", "s"];
        assert_eq!(tool_info_from_unified_parts(&parts), "");
    }

    #[test]
    fn tool_info_opaque_id_preserved() {
        let parts = vec!["GHT_01", "s", "tool-uuid"];
        assert_eq!(tool_info_from_unified_parts(&parts), "tool-uuid");
    }

    #[test]
    fn tool_info_strips_outer_whitespace() {
        // .strip() only affects the outer edges of the joined string, matching
        // Python's ":".join(parts[2:]).strip() behavior.
        let parts = vec!["GHT_01", "s", "  grep ", " 0 "];
        assert_eq!(tool_info_from_unified_parts(&parts), "grep : 0");
    }

    // ── format_unified_tool_call_id ──────────────────────────────

    #[test]
    fn format_canonical_step_level() {
        assert_eq!(
            format_unified_tool_call_id("GHT-01", "s", "grep:0"),
            "GHT_01:s:grep:0"
        );
    }

    #[test]
    fn format_canonical_task_level() {
        assert_eq!(
            format_unified_tool_call_id("GHT-01", "t0", "grep:0"),
            "GHT_01:t0:grep:0"
        );
    }

    #[test]
    fn format_strips_functions_prefix_from_fragment() {
        // provider_tool_fragment does NOT strip "functions."; only shorten does.
        assert_eq!(
            format_unified_tool_call_id("GHT-01", "s", "functions.grep:0"),
            "GHT_01:s:functions.grep:0"
        );
    }

    #[test]
    fn format_opaque_id_preserved() {
        assert_eq!(
            format_unified_tool_call_id("GHT-01", "s", "call_abc"),
            "GHT_01:s:call_abc"
        );
    }

    // ── parse_unified_tool_call_id ───────────────────────────────

    #[test]
    fn parse_step_level_canonical() {
        let parsed = parse_unified_tool_call_id("GHT_01:s:grep:0");
        assert_eq!(parsed.step_id, "GHT-01");
        assert_eq!(parsed.type_code, "s");
        assert_eq!(parsed.task_idx, None);
        assert_eq!(parsed.tool_info, "grep:0");
    }

    #[test]
    fn parse_task_level_canonical() {
        let parsed = parse_unified_tool_call_id("GHT_01:t2:grep:0");
        assert_eq!(parsed.step_id, "GHT-01");
        assert_eq!(parsed.type_code, "t");
        assert_eq!(parsed.task_idx, Some(2));
        assert_eq!(parsed.tool_info, "grep:0");
    }

    #[test]
    fn parse_opaque_tool_info_preserved() {
        let parsed = parse_unified_tool_call_id("GHT_01:s:tool-uuid");
        assert_eq!(parsed.step_id, "GHT-01");
        assert_eq!(parsed.tool_info, "tool-uuid");
    }

    #[test]
    fn parse_non_unified_returns_empty_sentinel_with_raw() {
        let parsed = parse_unified_tool_call_id("functions.grep:0");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.type_code, "");
        assert_eq!(parsed.task_idx, None);
        assert_eq!(parsed.tool_info, "functions.grep:0");
    }

    #[test]
    fn parse_empty_returns_empty_sentinel() {
        let parsed = parse_unified_tool_call_id("");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.tool_info, "");
    }

    #[test]
    fn parse_too_few_segments_returns_raw() {
        let parsed = parse_unified_tool_call_id("GHT_01:s");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.tool_info, "GHT_01:s");
    }

    #[test]
    fn parse_hyphen_step_fragment_rejected() {
        let parsed = parse_unified_tool_call_id("GHT-01:s:grep:0");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.tool_info, "GHT-01:s:grep:0");
    }

    #[test]
    fn parse_invalid_type_part_rejected() {
        let parsed = parse_unified_tool_call_id("GHT_01:x:grep:0");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.tool_info, "GHT_01:x:grep:0");
    }

    #[test]
    fn parse_t_without_idx_rejected() {
        let parsed = parse_unified_tool_call_id("GHT_01:t:grep:0");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.tool_info, "GHT_01:t:grep:0");
    }

    #[test]
    fn parse_t_non_numeric_idx_rejected() {
        let parsed = parse_unified_tool_call_id("GHT_01:tabc:grep:0");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.tool_info, "GHT_01:tabc:grep:0");
    }

    #[test]
    fn parse_strips_whitespace() {
        let parsed = parse_unified_tool_call_id("  GHT_01:s:grep:0  ");
        assert_eq!(parsed.step_id, "GHT-01");
        assert_eq!(parsed.tool_info, "grep:0");
    }

    #[test]
    fn parse_empty_tool_info_rejected() {
        // Input is trimmed first → "GHT_01:s:" → parts[2]="" → tool_info empty → sentinel.
        let parsed = parse_unified_tool_call_id("GHT_01:s:   ");
        assert_eq!(parsed.step_id, "");
        assert_eq!(parsed.tool_info, "GHT_01:s:");
    }

    #[test]
    fn parse_task_zero_idx() {
        let parsed = parse_unified_tool_call_id("GHT_01:t0:task:0");
        assert_eq!(parsed.type_code, "t");
        assert_eq!(parsed.task_idx, Some(0));
        assert_eq!(parsed.tool_info, "task:0");
    }

    // ── is_unified_tool_call_id ──────────────────────────────────

    #[test]
    fn is_unified_step_level_true() {
        assert!(is_unified_tool_call_id("GHT_01:s:grep:0"));
    }

    #[test]
    fn is_unified_task_level_true() {
        assert!(is_unified_tool_call_id("GHT_01:t0:grep:0"));
    }

    #[test]
    fn is_unified_non_unified_false() {
        assert!(!is_unified_tool_call_id("functions.grep:0"));
    }

    #[test]
    fn is_unified_empty_false() {
        assert!(!is_unified_tool_call_id(""));
    }

    #[test]
    fn is_unified_invalid_type_false() {
        assert!(!is_unified_tool_call_id("GHT_01:x:grep:0"));
    }

    #[test]
    fn is_unified_opaque_tool_info_true() {
        assert!(is_unified_tool_call_id("GHT_01:s:tool-uuid"));
    }

    // ── shorten_tool_call_id ─────────────────────────────────────

    #[test]
    fn shorten_unified_returns_tool_info() {
        assert_eq!(shorten_tool_call_id("GHT_01:s:grep:0"), "grep:0");
    }

    #[test]
    fn shorten_functions_prefix_stripped() {
        assert_eq!(shorten_tool_call_id("functions.grep:0"), "grep:0");
    }

    #[test]
    fn shorten_provider_with_idx() {
        assert_eq!(shorten_tool_call_id("grep:0"), "grep:0");
    }

    #[test]
    fn shorten_opaque_id_preserved() {
        assert_eq!(shorten_tool_call_id("call_abc"), "call_abc");
    }

    #[test]
    fn shorten_empty() {
        assert_eq!(shorten_tool_call_id(""), "");
    }

    #[test]
    fn shorten_functions_opaque_no_colon() {
        assert_eq!(shorten_tool_call_id("functions.tool-uuid"), "tool-uuid");
    }

    #[test]
    fn shorten_strips_whitespace() {
        assert_eq!(shorten_tool_call_id("  functions.grep:0  "), "grep:0");
    }
}
