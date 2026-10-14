//! Pure-logic helpers for subagents (ported from `subagents/*.py`).
//!
//! Covers: topic attachment stripping, search-query compaction, effort
//! parsing/normalization, report display summaries, reference key/merge/format,
//! loop termination heuristics, and preview helpers.

#![allow(clippy::type_complexity)]

use regex::Regex;
use std::collections::HashSet;
use std::sync::OnceLock;

// ── Topic attachment stripping (from `_research_topic_util.py`) ───────────

const CUT_MARKERS: &[&str] = &[
    "--- Context ---",
    "--- Triarch attachments (extracted content) ---",
];
const UI_LANGUAGE_MARKER: &str = "--- Triarch UI language ---";
const MAX_PLANNED_TOPIC_LEN: usize = 800;

/// Return the `--- Triarch UI language ---` block when present.
pub fn ui_language_suffix(topic: &str) -> String {
    let idx = topic.find(UI_LANGUAGE_MARKER);
    match idx {
        Some(i) => topic[i..].trim_start().to_string(),
        None => String::new(),
    }
}

fn join_topic_and_ui(topic: &str, ui_suffix: &str) -> String {
    let cleaned = topic.trim();
    if ui_suffix.is_empty() {
        return cleaned.to_string();
    }
    if cleaned.is_empty() {
        ui_suffix.to_string()
    } else {
        format!("{cleaned}\n\n{ui_suffix}")
    }
}

/// Return the user ask (and optional UI-language footer), without file bodies.
pub fn topic_without_attachments(topic: &str) -> String {
    let text = topic;
    let ui_suffix = ui_language_suffix(text);
    let mut text = text.to_string();
    if !ui_suffix.is_empty() {
        if let Some(idx) = text.find(UI_LANGUAGE_MARKER) {
            text = text[..idx].to_string();
        }
    }
    let mut cut = text.len();
    for marker in CUT_MARKERS {
        if let Some(idx) = text.find(marker) {
            cut = cut.min(idx);
        }
    }
    let cleaned = text[..cut].trim().to_string();
    join_topic_and_ui(&cleaned, &ui_suffix)
}

/// Prefer LLM-extracted topic from `parsed` (JSON dict); else strip attachments.
pub fn planned_research_topic(parsed: Option<&serde_json::Value>, raw_topic: &str) -> String {
    let ui_suffix = ui_language_suffix(raw_topic);
    let mut candidate = String::new();

    if let Some(serde_json::Value::Object(map)) = parsed {
        for key in &["research_topic", "topic"] {
            if let Some(serde_json::Value::String(s)) = map.get(*key) {
                let trimmed = s.trim();
                if !trimmed.is_empty() {
                    candidate = trimmed.to_string();
                    break;
                }
            }
        }
    }

    if candidate.is_empty() {
        let result = topic_without_attachments(raw_topic);
        return if result.chars().count() > MAX_PLANNED_TOPIC_LEN {
            result.chars().take(MAX_PLANNED_TOPIC_LEN).collect()
        } else {
            result
        };
    }

    // Guard: model must not echo attachment/context blocks into research_topic.
    for marker in CUT_MARKERS {
        if let Some(idx) = candidate.find(marker) {
            candidate = candidate[..idx].trim().to_string();
        }
    }
    if let Some(idx) = candidate.find(UI_LANGUAGE_MARKER) {
        candidate = candidate[..idx].trim().to_string();
    }

    if candidate.chars().count() > MAX_PLANNED_TOPIC_LEN {
        let truncated: String = candidate.chars().take(MAX_PLANNED_TOPIC_LEN).collect();
        candidate = format!("{}…", truncated.trim_end());
    }
    join_topic_and_ui(&candidate, &ui_suffix)
}

// ── Search query compaction (from `_research_json_util.py`) ───────────────

/// Reduce a long task prompt to a short search-engine query.
pub fn compact_search_query(raw: &str, max_len: usize) -> String {
    let mut text = raw.trim().to_string();
    for sep in [
        "\n\n", "\n1.", "\n2.", "\n请", "\nPlease", "\nUse ", "\n使用",
    ] {
        if let Some(idx) = text.find(sep) {
            text = text[..idx].trim().to_string();
        }
    }
    // Collapse whitespace
    let collapsed: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.chars().count() > max_len {
        let taken: String = collapsed.chars().take(max_len.saturating_sub(1)).collect();
        format!("{taken}…")
    } else {
        collapsed
    }
}

/// Single sub-question derived from the research topic.
pub fn fallback_sub_questions(topic: &str) -> Vec<serde_json::Value> {
    let q = compact_search_query(topic, 200);
    vec![serde_json::json!({"question": q})]
}

/// Build search queries from sub-questions or the topic.
pub fn fallback_queries(
    topic: &str,
    sub_questions: Option<&[serde_json::Value]>,
) -> Vec<serde_json::Value> {
    let mut queries: Vec<serde_json::Value> = Vec::new();
    if let Some(sq_list) = sub_questions {
        for sq in sq_list {
            let question = match sq {
                serde_json::Value::Object(map) => map
                    .get("question")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim()
                    .to_string(),
                serde_json::Value::String(s) => s.trim().to_string(),
                _ => format!("{sq}").trim().to_string(),
            };
            if question.is_empty() {
                continue;
            }
            let q = compact_search_query(&question, 120);
            queries.push(serde_json::json!({"query": q}));
        }
    }
    if !queries.is_empty() {
        return queries;
    }
    let q = compact_search_query(topic, 120);
    vec![serde_json::json!({"query": q})]
}

// ── Effort parsing (from `academic_research/effort.py` & `deep_research/effort.py`) ─

fn effort_pattern() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?:^|\b)effort\s*[:=]\s*(normal|thorough)\b").unwrap())
}

/// Coerce config/context value to a valid effort level.
pub fn normalize_effort(raw: Option<&str>) -> String {
    let key = raw.unwrap_or("normal").trim().to_lowercase();
    if key == "thorough" {
        "thorough".to_string()
    } else {
        "normal".to_string()
    }
}

/// Parse `effort: thorough` from topic text.
pub fn parse_effort_from_text(text: &str) -> Option<String> {
    if text.is_empty() {
        return None;
    }
    let re = effort_pattern();
    re.captures(text.trim())
        .map(|c| normalize_effort(Some(c.get(1).unwrap().as_str())))
}

// ── Effort profiles (shared structure for both academic and deep research) ─

/// Hard caps for one effort level.
#[derive(Debug, Clone, PartialEq)]
pub struct EffortProfile {
    pub effort: String,
    pub max_sub_questions: i64,
    pub max_initial_queries: i64,
    pub max_follow_up_queries: i64,
    pub max_loops: i64,
    pub crawl_top_n: i64,
}

impl EffortProfile {
    pub fn normal() -> Self {
        Self {
            effort: "normal".to_string(),
            max_sub_questions: 3,
            max_initial_queries: 4,
            max_follow_up_queries: 1,
            max_loops: 2,
            crawl_top_n: 3,
        }
    }

    pub fn thorough() -> Self {
        Self {
            effort: "thorough".to_string(),
            max_sub_questions: 5,
            max_initial_queries: 8,
            max_follow_up_queries: 2,
            max_loops: 4,
            crawl_top_n: 5,
        }
    }

    pub fn plan_hint(&self) -> String {
        format!(
            "Identify at most {} sub-questions and at most {} search queries.",
            self.max_sub_questions, self.max_initial_queries
        )
    }

    pub fn reflect_follow_up_hint(&self) -> String {
        if self.max_follow_up_queries == 0 {
            "If not sufficient, set is_sufficient to true; do not generate follow-up queries."
                .to_string()
        } else {
            format!(
                "If not sufficient, generate at most {} follow-up queries targeting the gaps.",
                self.max_follow_up_queries
            )
        }
    }
}

/// Return the profile for a validated effort level.
pub fn profile_for_effort(effort: &str) -> EffortProfile {
    if effort == "thorough" {
        EffortProfile::thorough()
    } else {
        EffortProfile::normal()
    }
}

// ── Preview helper (from `browser_use/_preview.py` & `computer_use/_preview.py`) ─

/// Return a single-line preview of `text` up to `chars` characters.
pub fn preview_first(text: &str, chars: usize) -> String {
    let t: String = text.replace('\n', " ").trim().to_string();
    if t.chars().count() <= chars {
        return t;
    }
    if chars <= 1 {
        return "…".to_string();
    }
    let taken: String = t.chars().take(chars - 1).collect();
    format!("{taken}…")
}

// ── Result summary (from `browser_use/display_summary.py` & `computer_use/display_summary.py`) ─

/// First non-empty line from result text, flattened and clipped.
pub fn result_summary_for_display(result: &str, max_len: usize) -> String {
    for line in result.lines() {
        let s = line.trim();
        if s.is_empty() {
            continue;
        }
        let out: String = s.split_whitespace().collect::<Vec<_>>().join(" ");
        if out.chars().count() > max_len {
            let taken: String = out.chars().take(max_len - 1).collect();
            return format!("{taken}…");
        }
        return out;
    }
    String::new()
}

// ── Report display summary (from `*/display_summary.py`) ──────────────────

fn scope_heading_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?m-i)^#{1,3}\s+\**Scope\**:?\**").unwrap())
}

fn section_heading_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?m)^#{1,3}\s+(.+)$").unwrap())
}

/// Pick a human title from report headings, falling back to the research topic.
pub fn derive_report_title(report: &str, topic: &str, fallback_prefix: &str) -> String {
    let re = section_heading_re();
    for caps in re.captures_iter(report) {
        let heading = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
        let normalized = heading
            .trim_matches(|c| c == '*' || c == ' ')
            .to_lowercase();
        if normalized.starts_with("scope:") {
            continue;
        }
        let key = normalized
            .split(':')
            .next()
            .unwrap_or("")
            .trim()
            .to_string();
        if key == "scope" || key == "references" {
            continue;
        }
        if !heading.is_empty() {
            return heading.chars().take(120).collect();
        }
    }
    let cleaned = topic.trim();
    if !cleaned.is_empty() {
        cleaned.chars().take(120).collect()
    } else {
        fallback_prefix.to_string()
    }
}

fn clip_summary(text: &str, max_len: usize) -> String {
    let flattened: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flattened.chars().count() <= max_len {
        return flattened;
    }
    let taken: String = flattened.chars().take(max_len - 1).collect();
    format!("{taken}…")
}

fn body_after_scope(report: &str) -> String {
    let text = report.trim();
    let scope_re = scope_heading_re();
    let section_re = section_heading_re();
    match scope_re.find(text) {
        None => text.to_string(),
        Some(m) => {
            let remainder = &text[m.end()..];
            match section_re.find(remainder) {
                Some(m2) => remainder[m2.start()..].trim_start().to_string(),
                None => remainder.trim_start().to_string(),
            }
        }
    }
}

fn first_content_paragraph(report: &str) -> String {
    let text = body_after_scope(report);
    if text.is_empty() {
        return String::new();
    }
    let para_re = Regex::new(r"\n\s*\n").unwrap();
    for chunk in para_re.split(&text) {
        let trimmed = chunk.trim();
        if trimmed.is_empty() {
            continue;
        }
        if trimmed.starts_with('#') {
            continue;
        }
        let flattened: String = trimmed.split_whitespace().collect::<Vec<_>>().join(" ");
        if !flattened.is_empty() {
            return flattened;
        }
    }
    report.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Return a short summary skipping boilerplate Scope headings.
pub fn brief_summary_for_display(
    report: &str,
    preferred_sections: &[&str],
    max_len: usize,
) -> String {
    let text = report.trim();
    if text.is_empty() {
        return String::new();
    }
    let section_re = section_heading_re();
    for caps in section_re.captures_iter(text) {
        let heading = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
        let normalized = heading.trim_matches('*').to_lowercase();
        if !preferred_sections.contains(&normalized.as_str()) {
            continue;
        }
        let start = caps.get(0).unwrap().end();
        let next = section_re.find_at(text, start);
        let section_body = match &next {
            Some(m) => text[start..m.start()].trim().to_string(),
            None => text[start..].trim().to_string(),
        };
        let para = first_content_paragraph(&section_body);
        if !para.is_empty() {
            return clip_summary(&para, max_len);
        }
    }
    let fallback = first_content_paragraph(text);
    if fallback.is_empty() {
        String::new()
    } else {
        clip_summary(&fallback, max_len)
    }
}

// ── Reference key/merge/format (from `*/references.py`) ───────────────────

/// Build a deduplication key for a reference.
pub fn reference_key(url: Option<&str>, source_name: &str, source_ref: &str) -> String {
    if let Some(url) = url {
        let trimmed = url.trim().trim_end_matches('/').to_string();
        // Parse host + path manually (avoid pulling in a full URL crate).
        let no_proto = trimmed
            .strip_prefix("https://")
            .or_else(|| trimmed.strip_prefix("http://"))
            .unwrap_or(&trimmed);
        let (host_path, _) = no_proto.split_once('?').unwrap_or((no_proto, ""));
        let (host_path, _) = host_path.split_once('#').unwrap_or((host_path, ""));
        let (host, path) = host_path
            .split_once('/')
            .map(|(h, p)| (h.to_string(), format!("/{p}")))
            .unwrap_or_else(|| (host_path.to_string(), String::new()));
        let host_lower = host.to_lowercase();
        let path_trimmed = path.trim_end_matches('/').to_string();
        format!("url:{host_lower}{path_trimmed}")
    } else {
        format!("ref:{}:{}", source_name, source_ref).to_lowercase()
    }
}

/// Deduplicate references while preserving first-seen order.
/// Returns indices of the first occurrence of each unique key.
pub fn merge_reference_indices(
    refs: &[(Option<String>, String, String, String, Option<String>)],
) -> Vec<usize> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut result: Vec<usize> = Vec::new();
    for (i, (url, source_name, source_ref, _title, _query)) in refs.iter().enumerate() {
        let key = reference_key(url.as_deref(), source_name, source_ref);
        if seen.insert(key) {
            result.push(i);
        }
    }
    result
}

/// Format a markdown bibliography section.
pub fn format_references_section(
    refs: &[(Option<String>, String, String, String, Option<String>)],
    accessed_date: Option<&str>,
) -> String {
    if refs.is_empty() {
        return String::new();
    }
    let mut lines = vec!["## References".to_string(), String::new()];
    for (idx, (url, source_name, source_ref, title, _query)) in refs.iter().enumerate() {
        let label = if !title.is_empty() {
            title.clone()
        } else if !source_ref.is_empty() {
            source_ref.clone()
        } else {
            source_name.clone()
        };
        let entry = if let Some(u) = url {
            format!("{}. [{}]({})", idx + 1, label, u)
        } else {
            format!("{}. {} ({}: {})", idx + 1, label, source_name, source_ref)
        };
        let entry = if let Some(date) = accessed_date {
            format!("{entry} (accessed {date})")
        } else {
            entry
        };
        lines.push(entry);
    }
    lines.join("\n")
}

// ── Loop termination (from `*/termination.py`) ────────────────────────────

/// Result of early termination check.
#[derive(Debug, Clone, PartialEq)]
pub struct TerminationDecision {
    pub should_terminate: bool,
    pub reason: String,
    pub confidence: f64,
}

/// Configuration for loop termination.
#[derive(Debug, Clone)]
pub struct TerminationConfig {
    pub min_results: usize,
    pub min_source_diversity: usize,
    pub max_duplicate_ratio: f64,
    pub min_content_length: usize,
}

impl Default for TerminationConfig {
    fn default() -> Self {
        Self {
            min_results: 3,
            min_source_diversity: 2,
            max_duplicate_ratio: 0.5,
            min_content_length: 200,
        }
    }
}

/// A source result for termination checking.
#[derive(Debug, Clone)]
pub struct SourceResultInfo {
    pub content: String,
    pub source_name: String,
}

/// Decide whether a research loop has gathered enough to stop early.
pub fn check_termination(
    config: &TerminationConfig,
    accumulated_source_names: &[String],
    current_results: &[SourceResultInfo],
    iteration: usize,
) -> TerminationDecision {
    let total_results = accumulated_source_names.len() + current_results.len();

    if iteration < 1 {
        return TerminationDecision {
            should_terminate: false,
            reason: "insufficient_iterations".to_string(),
            confidence: 0.0,
        };
    }

    if total_results < config.min_results {
        return TerminationDecision {
            should_terminate: false,
            reason: format!("below_min_results ({total_results}/{})", config.min_results),
            confidence: 0.0,
        };
    }

    // Extract unique source names from accumulated and current
    let mut source_names: HashSet<&str> = HashSet::new();
    for name in accumulated_source_names {
        source_names.insert(name.as_str());
    }
    for r in current_results {
        source_names.insert(r.source_name.as_str());
    }
    if source_names.len() < config.min_source_diversity {
        return TerminationDecision {
            should_terminate: false,
            reason: format!(
                "insufficient_diversity ({}/{}) sources",
                source_names.len(),
                config.min_source_diversity
            ),
            confidence: 0.0,
        };
    }

    // Check for diminishing returns
    let prev_set: HashSet<&str> = accumulated_source_names
        .iter()
        .map(|s| s.as_str())
        .collect();
    let current_set: HashSet<&str> = current_results
        .iter()
        .map(|r| r.source_name.as_str())
        .collect();
    let new_sources: Vec<&&str> = current_set.difference(&prev_set).collect();

    if iteration >= 2 && new_sources.is_empty() {
        return TerminationDecision {
            should_terminate: true,
            reason: "no_new_sources".to_string(),
            confidence: 0.7,
        };
    }

    // Check content quality
    let avg_content_length = if current_results.is_empty() {
        0.0
    } else {
        let total: usize = current_results
            .iter()
            .map(|r| r.content.chars().count())
            .sum();
        total as f64 / current_results.len() as f64
    };
    if avg_content_length < config.min_content_length as f64 {
        return TerminationDecision {
            should_terminate: false,
            reason: format!("low_content_quality ({:.0} chars)", avg_content_length),
            confidence: 0.0,
        };
    }

    // Check if we have diverse, high-quality results
    if total_results >= config.min_results * 2 && source_names.len() >= config.min_source_diversity
    {
        return TerminationDecision {
            should_terminate: true,
            reason: "sufficient_diverse_results".to_string(),
            confidence: 0.8,
        };
    }

    TerminationDecision {
        should_terminate: false,
        reason: "continue_research".to_string(),
        confidence: 0.0,
    }
}

// ── Report scenario fallback classification (from `*/report_classifier.py`) ─

/// Academic report scenario sections.
pub fn academic_scenario_sections() -> &'static [(&'static str, &'static [&'static str])] {
    static SECTIONS: &[(&str, &[&str])] = &[
        (
            "literature_review",
            &[
                "Scope",
                "Executive Summary",
                "Key Papers",
                "Themes",
                "Gaps",
                "References",
            ],
        ),
        (
            "paper_comparison",
            &[
                "Scope",
                "Context",
                "Comparison Table",
                "Methods",
                "Findings",
                "Recommendation",
                "References",
            ],
        ),
        (
            "method_survey",
            &[
                "Scope",
                "Overview",
                "Methods Compared",
                "Strengths and Limits",
                "References",
            ],
        ),
        (
            "citation_analysis",
            &["Scope", "Question", "Evidence", "Synthesis", "References"],
        ),
        (
            "general_academic",
            &[
                "Scope",
                "Executive Summary",
                "Key Findings",
                "Open Questions",
                "References",
            ],
        ),
    ];
    SECTIONS
}

/// Deep research scenario sections.
pub fn deep_scenario_sections() -> &'static [(&'static str, &'static [&'static str])] {
    static SECTIONS: &[(&str, &[&str])] = &[
        (
            "landscape_survey",
            &[
                "Scope",
                "Executive Summary",
                "Landscape",
                "Key Players",
                "Trends",
                "References",
            ],
        ),
        (
            "how_to_guide",
            &[
                "Scope",
                "Overview",
                "Prerequisites",
                "Steps",
                "Pitfalls",
                "References",
            ],
        ),
        (
            "comparison",
            &[
                "Scope",
                "Context",
                "Comparison Table",
                "Trade-offs",
                "Recommendation",
                "References",
            ],
        ),
        (
            "fact_check",
            &[
                "Scope",
                "Claim",
                "Evidence For",
                "Evidence Against",
                "Verdict",
                "References",
            ],
        ),
        (
            "general_research",
            &[
                "Scope",
                "Executive Summary",
                "Key Findings",
                "Open Questions",
                "References",
            ],
        ),
    ];
    SECTIONS
}

fn scenario_sections_lookup(table: &[(&str, &[&str])], scenario: &str) -> Vec<String> {
    for (name, sections) in table {
        if *name == scenario {
            return sections.iter().map(|s| s.to_string()).collect();
        }
    }
    table
        .last()
        .map(|(_, s)| s.iter().map(|s| s.to_string()).collect())
        .unwrap_or_default()
}

/// Heuristic fallback for academic report scenario classification.
pub fn academic_fallback_classification(topic: &str) -> (String, Vec<String>, Vec<String>) {
    let lower = topic.to_lowercase();
    let scenario =
        if lower.contains(" vs ") || lower.contains(" versus ") || lower.contains("compare") {
            "paper_comparison"
        } else if lower.contains("literature review") || lower.contains("survey") {
            "literature_review"
        } else if lower.contains("method") || lower.contains("approach") {
            "method_survey"
        } else if lower.contains("cite") || lower.contains("citation") {
            "citation_analysis"
        } else {
            "general_academic"
        };
    let sections = scenario_sections_lookup(academic_scenario_sections(), scenario);
    let focus = vec![topic.chars().take(120).collect()];
    (scenario.to_string(), sections, focus)
}

/// Heuristic fallback for deep research report scenario classification.
pub fn deep_fallback_classification(topic: &str) -> (String, Vec<String>, Vec<String>) {
    let lower = topic.to_lowercase();
    let scenario = if lower.contains(" vs ")
        || lower.contains(" versus ")
        || lower.contains("compare")
    {
        "comparison"
    } else if lower.starts_with("how ") || lower.contains("how to") {
        "how_to_guide"
    } else if lower.contains("true") && topic.contains('?') {
        "fact_check"
    } else if lower.contains("state of") || lower.contains("landscape") || lower.contains("trends")
    {
        "landscape_survey"
    } else {
        "general_research"
    };
    let sections = scenario_sections_lookup(deep_scenario_sections(), scenario);
    let focus = vec![topic.chars().take(120).collect()];
    (scenario.to_string(), sections, focus)
}

// ── JSON extraction (from `*/report_classifier.py`) ────────────────────────

/// Extract JSON from LLM output that may be wrapped in a code fence.
pub fn parse_json_from_llm(content: &str) -> Option<serde_json::Value> {
    let text = content.trim();
    let fence_re = Regex::new(r"(?is)```(?:json)?\s*\n?(.*?)\n?```").unwrap();
    let text = match fence_re.captures(text) {
        Some(c) => c.get(1).map(|m| m.as_str().trim()).unwrap_or(text),
        None => text,
    };
    match serde_json::from_str::<serde_json::Value>(text) {
        Ok(v) if v.is_object() => Some(v),
        _ => None,
    }
}

// ── Timeout computation (from `_research_timeouts.py`) ────────────────────

const DEFAULT_WIZSEARCH_TIMEOUT_SEC: f64 = 30.0;

/// Return gather wait_for timeout that will not cancel wizsearch early.
///
/// `wizsearch_timeout` is the configured wizsearch timeout (or the default 30s).
/// `configured` is the outer source timeout. `slack_sec` is extra margin.
pub fn effective_source_timeout(configured: f64, wizsearch_timeout: f64, slack_sec: f64) -> f64 {
    configured.max(wizsearch_timeout + slack_sec)
}

/// Get the default wizsearch timeout.
pub fn default_wizsearch_timeout() -> f64 {
    DEFAULT_WIZSEARCH_TIMEOUT_SEC
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── Topic attachment stripping ──

    #[test]
    fn topic_without_attachments_strips_body() {
        let topic = "研究世界模型\n\n--- Context ---\nAttached files: x.pdf\n\n--- Triarch attachments (extracted content) ---\nPDF TEXT\n--- Triarch UI language ---\nRespond in Chinese.";
        let cleaned = topic_without_attachments(topic);
        assert!(cleaned.contains("研究世界模型"));
        assert!(cleaned.contains("Respond in Chinese"));
        assert!(!cleaned.contains("PDF TEXT"));
        assert!(!cleaned.contains("Triarch attachments"));
    }

    #[test]
    fn topic_without_attachments_plain_unchanged() {
        let topic = "Compare vector databases for RAG workloads";
        assert_eq!(topic_without_attachments(topic), topic);
    }

    #[test]
    fn ui_language_suffix_extracts_block() {
        let topic = "topic\n--- Triarch UI language ---\nRespond in English.";
        let suffix = ui_language_suffix(topic);
        assert!(suffix.starts_with("--- Triarch UI language ---"));
        assert!(suffix.contains("Respond in English"));
    }

    #[test]
    fn ui_language_suffix_absent_returns_empty() {
        assert_eq!(ui_language_suffix("plain topic"), "");
    }

    #[test]
    fn planned_research_topic_prefers_llm_extraction() {
        let raw = "ask\n\n--- Triarch attachments (extracted content) ---\nLONG PDF\n--- Triarch UI language ---\nRespond in English.";
        let parsed = serde_json::json!({"research_topic": "Good topic", "queries": []});
        let result = planned_research_topic(Some(&parsed), raw);
        assert!(result.starts_with("Good topic"));
        assert!(!result.contains("LONG PDF"));
        assert!(result.contains("Respond in English"));
    }

    #[test]
    fn planned_research_topic_falls_back() {
        let raw = "研究世界模型\n\n--- Triarch attachments (extracted content) ---\nPDF";
        let parsed = serde_json::json!({"queries": []});
        let result = planned_research_topic(Some(&parsed), raw);
        assert_eq!(result, "研究世界模型");
    }

    #[test]
    fn planned_research_topic_strips_echoed_attachments() {
        let raw = "ask\n--- Triarch UI language ---\nRespond in English.";
        let parsed = serde_json::json!({"research_topic": "Good topic\n--- Triarch attachments (extracted content) ---\nBAD"});
        let result = planned_research_topic(Some(&parsed), raw);
        assert!(result.contains("Good topic"));
        assert!(!result.contains("BAD"));
        assert!(result.contains("Respond in English"));
    }

    // ── Search query compaction ──

    #[test]
    fn compact_search_query_short() {
        assert_eq!(compact_search_query("hello world", 120), "hello world");
    }

    #[test]
    fn compact_search_query_truncates() {
        let long = "a".repeat(200);
        let result = compact_search_query(&long, 120);
        assert_eq!(result.chars().count(), 120);
        assert!(result.ends_with('…'));
    }

    #[test]
    fn compact_search_query_strips_after_separator() {
        let raw = "short query\n\nAdditional context that should be stripped";
        assert_eq!(compact_search_query(raw, 120), "short query");
    }

    #[test]
    fn fallback_queries_from_topic() {
        let result = fallback_queries("test topic", None);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0]["query"], "test topic");
    }

    #[test]
    fn fallback_queries_from_sub_questions() {
        let sqs = vec![serde_json::json!({"question": "what is rust"})];
        let result = fallback_queries("fallback", Some(&sqs));
        assert_eq!(result.len(), 1);
        assert_eq!(result[0]["query"], "what is rust");
    }

    // ── Effort parsing ──

    #[test]
    fn normalize_effort_normal() {
        assert_eq!(normalize_effort(Some("bogus")), "normal");
        assert_eq!(normalize_effort(None), "normal");
    }

    #[test]
    fn normalize_effort_thorough() {
        assert_eq!(normalize_effort(Some("THOROUGH")), "thorough");
    }

    #[test]
    fn parse_effort_from_text_finds() {
        assert_eq!(
            parse_effort_from_text("effort: thorough\nCompare vector DBs"),
            Some("thorough".to_string())
        );
        assert_eq!(
            parse_effort_from_text("Research effort=thorough on LLM agents"),
            Some("thorough".to_string())
        );
    }

    #[test]
    fn parse_effort_from_text_missing() {
        assert_eq!(parse_effort_from_text("plain topic"), None);
    }

    #[test]
    fn profile_normal() {
        let p = profile_for_effort("normal");
        assert_eq!(p.max_loops, 2);
        assert_eq!(p.crawl_top_n, 3);
    }

    #[test]
    fn profile_thorough() {
        let p = profile_for_effort("thorough");
        assert_eq!(p.max_loops, 4);
        assert_eq!(p.max_initial_queries, 8);
    }

    #[test]
    fn profile_plan_hint() {
        let p = profile_for_effort("normal");
        assert!(p.plan_hint().contains("3 sub-questions"));
        assert!(p.plan_hint().contains("4 search queries"));
    }

    #[test]
    fn profile_follow_up_hint_nonzero() {
        let p = profile_for_effort("thorough");
        assert!(p.reflect_follow_up_hint().contains("2"));
    }

    #[test]
    fn profile_follow_up_hint_zero() {
        let p = EffortProfile {
            effort: "normal".to_string(),
            max_sub_questions: 1,
            max_initial_queries: 1,
            max_follow_up_queries: 0,
            max_loops: 1,
            crawl_top_n: 1,
        };
        assert!(p.reflect_follow_up_hint().contains("do not generate"));
    }

    // ── Preview ──

    #[test]
    fn preview_first_short() {
        assert_eq!(preview_first("hello", 200), "hello");
    }

    #[test]
    fn preview_first_truncates() {
        let long = "a".repeat(300);
        let result = preview_first(&long, 10);
        assert_eq!(result.chars().count(), 10);
        assert!(result.ends_with('…'));
    }

    #[test]
    fn preview_first_newlines_to_spaces() {
        assert_eq!(preview_first("hello\nworld", 200), "hello world");
    }

    // ── Result summary ──

    #[test]
    fn result_summary_first_line() {
        assert_eq!(result_summary_for_display("hello\nworld", 160), "hello");
    }

    #[test]
    fn result_summary_empty() {
        assert_eq!(result_summary_for_display("", 160), "");
    }

    #[test]
    fn result_summary_truncates() {
        let long = "a".repeat(200);
        let result = result_summary_for_display(&long, 160);
        assert_eq!(result.chars().count(), 160);
        assert!(result.ends_with('…'));
    }

    // ── Report display summary ──

    #[test]
    fn brief_summary_skips_scope() {
        let report = "## Scope\n\nPublic web only.\n\n## Key Findings\n\nFinding one.";
        let preferred = ["executive summary", "key findings", "overview", "summary"];
        assert_eq!(
            brief_summary_for_display(report, &preferred, 320),
            "Finding one."
        );
    }

    #[test]
    fn derive_title_from_heading() {
        let report = "## Scope\n\nblah\n\n## Key Findings\n\ncontent";
        let title = derive_report_title(report, "fallback", "report");
        assert_eq!(title, "Key Findings");
    }

    #[test]
    fn derive_title_falls_back_to_topic() {
        let title = derive_report_title("no headings", "My Topic", "report");
        assert_eq!(title, "My Topic");
    }

    #[test]
    fn derive_title_falls_back_to_prefix() {
        let title = derive_report_title("no headings", "", "academic-report");
        assert_eq!(title, "academic-report");
    }

    // ── Reference key/merge ──

    #[test]
    fn reference_key_with_url() {
        let key = reference_key(Some("https://a.com/x/"), "web", "ref1");
        assert_eq!(key, "url:a.com/x");
    }

    #[test]
    fn reference_key_without_url() {
        let key = reference_key(None, "Web", "Ref1");
        assert_eq!(key, "ref:web:ref1");
    }

    #[test]
    fn merge_references_dedupes() {
        let refs = vec![
            (
                Some("https://a.com/x".to_string()),
                "web".to_string(),
                "a".to_string(),
                "A".to_string(),
                None,
            ),
            (
                Some("https://a.com/x/".to_string()),
                "web".to_string(),
                "a2".to_string(),
                "A dup".to_string(),
                None,
            ),
        ];
        let indices = merge_reference_indices(&refs);
        assert_eq!(indices, vec![0]);
    }

    #[test]
    fn format_references_markdown() {
        let refs = vec![(
            Some("https://example.com".to_string()),
            "web_search".to_string(),
            "example.com".to_string(),
            "Example".to_string(),
            None,
        )];
        let text = format_references_section(&refs, Some("2026-05-25"));
        assert!(text.contains("## References"));
        assert!(text.contains("[Example](https://example.com)"));
        assert!(text.contains("accessed 2026-05-25"));
    }

    #[test]
    fn format_references_empty() {
        assert_eq!(format_references_section(&[], None), "");
    }

    // ── Termination ──

    #[test]
    fn termination_no_terminate_first_iteration() {
        let config = TerminationConfig::default();
        let decision = check_termination(
            &config,
            &[],
            &[SourceResultInfo {
                content: "test".to_string(),
                source_name: "web".to_string(),
            }],
            0,
        );
        assert!(!decision.should_terminate);
        assert_eq!(decision.reason, "insufficient_iterations");
    }

    #[test]
    fn termination_sufficient_diverse() {
        let config = TerminationConfig::default();
        let results: Vec<SourceResultInfo> = (0..6)
            .map(|i| SourceResultInfo {
                content: "a".repeat(300),
                source_name: if i % 2 == 0 { "web" } else { "academic" }.to_string(),
            })
            .collect();
        let decision = check_termination(&config, &[], &results, 1);
        assert!(decision.should_terminate);
        assert_eq!(decision.reason, "sufficient_diverse_results");
        assert!((decision.confidence - 0.8).abs() < 1e-10);
    }

    #[test]
    fn termination_below_min_results() {
        let config = TerminationConfig::default();
        let results = vec![SourceResultInfo {
            content: "a".repeat(300),
            source_name: "web".to_string(),
        }];
        let decision = check_termination(&config, &[], &results, 1);
        assert!(!decision.should_terminate);
        assert!(decision.reason.contains("below_min_results"));
    }

    #[test]
    fn termination_insufficient_diversity() {
        let config = TerminationConfig::default();
        let results: Vec<SourceResultInfo> = (0..3)
            .map(|_| SourceResultInfo {
                content: "a".repeat(300),
                source_name: "web".to_string(),
            })
            .collect();
        let decision = check_termination(&config, &[], &results, 1);
        assert!(!decision.should_terminate);
        assert!(decision.reason.contains("insufficient_diversity"));
    }

    #[test]
    fn termination_no_new_sources() {
        let config = TerminationConfig::default();
        let accumulated = vec!["web".to_string(), "academic".to_string()];
        let results = vec![SourceResultInfo {
            content: "a".repeat(300),
            source_name: "web".to_string(),
        }];
        let decision = check_termination(&config, &accumulated, &results, 2);
        assert!(decision.should_terminate);
        assert_eq!(decision.reason, "no_new_sources");
        assert!((decision.confidence - 0.7).abs() < 1e-10);
    }

    // ── Scenario fallback ──

    #[test]
    fn academic_fallback_comparison() {
        let (scenario, sections, _focus) = academic_fallback_classification("Rust vs Go");
        assert_eq!(scenario, "paper_comparison");
        assert!(sections.contains(&"Comparison Table".to_string()));
    }

    #[test]
    fn academic_fallback_general() {
        let (scenario, _, _) = academic_fallback_classification("some random topic");
        assert_eq!(scenario, "general_academic");
    }

    #[test]
    fn deep_fallback_how_to() {
        let (scenario, _, _) = deep_fallback_classification("how to build a web app");
        assert_eq!(scenario, "how_to_guide");
    }

    #[test]
    fn deep_fallback_general() {
        let (scenario, _, _) = deep_fallback_classification("some random topic");
        assert_eq!(scenario, "general_research");
    }

    // ── JSON parsing ──

    #[test]
    fn parse_json_from_llm_plain() {
        let result = parse_json_from_llm(r#"{"scenario": "general"}"#);
        assert!(result.is_some());
        assert_eq!(result.unwrap()["scenario"], "general");
    }

    #[test]
    fn parse_json_from_llm_fenced() {
        let result = parse_json_from_llm("```json\n{\"scenario\": \"general\"}\n```");
        assert!(result.is_some());
    }

    #[test]
    fn parse_json_from_llm_non_dict() {
        assert!(parse_json_from_llm("[1, 2, 3]").is_none());
    }

    // ── Timeout ──

    #[test]
    fn effective_timeout_covers_wizsearch() {
        assert_eq!(effective_source_timeout(10.0, 30.0, 5.0), 35.0);
    }

    #[test]
    fn effective_timeout_preserves_higher() {
        assert_eq!(effective_source_timeout(45.0, 30.0, 5.0), 45.0);
    }
}
