//! String-matching helpers for skill name/tag prefetch.

/// Maximum length for a token to require word-boundary enforcement.
const SHORT_BOUNDARY_MAX_LEN: usize = 3;

/// Built-in skill aliases (name → extra match tokens).
fn builtin_skill_aliases(skill_name: &str) -> Vec<&'static str> {
    match skill_name {
        "clawhub" => vec![
            "claw hub",
            "claw hub registry",
            "clawhub registry",
            "community skill registry",
        ],
        "github" => vec!["git hub", "github cli", "gh cli"],
        "skill-creator" => vec![
            "skill creator",
            "create skill",
            "create a skill",
            "new skill",
            "write skill",
            "agentskill",
            "skill authoring",
        ],
        "mcp-builder" => vec![
            "mcp builder",
            "mcp server",
            "model context protocol",
            "build mcp",
            "create mcp",
        ],
        "weather" => vec!["wttr", "wttr.in"],
        _ => vec![],
    }
}

/// Collapse spaces, hyphens, and underscores; lowercase.
pub fn compact(text: &str) -> String {
    text.to_lowercase()
        .chars()
        .filter(|&ch| !is_compact_separator(ch))
        .collect()
}

/// Whether a char is a compact separator (whitespace, hyphen, underscore).
fn is_compact_separator(ch: char) -> bool {
    ch.is_whitespace() || ch == '-' || ch == '_'
}

/// Whether a char is an alphanumeric boundary char `[a-z0-9]`.
fn is_boundary_char(ch: char) -> bool {
    ch.is_ascii_alphanumeric()
}

/// Find `variant` in `corpus` with word-boundary enforcement for short tokens.
pub fn direct_substring_index(corpus: &str, variant: &str) -> Option<usize> {
    let vlen = variant.chars().count();
    if vlen < 2 {
        return None;
    }
    if vlen <= SHORT_BOUNDARY_MAX_LEN {
        // Word-boundary search: the char before and after the match must
        // NOT be `[a-z0-9]` (i.e. must be a boundary or string edge).
        for pos in find_all_byte_offsets(corpus, variant) {
            if has_word_boundary(corpus, variant, pos) {
                return Some(pos);
            }
        }
        None
    } else {
        corpus.find(variant)
    }
}

/// Check that `variant` at byte `pos` in `corpus` has word boundaries on
/// both sides (the preceding and following chars are not `[a-z0-9]`).
fn has_word_boundary(corpus: &str, variant: &str, pos: usize) -> bool {
    // Preceding char must not be [a-z0-9].
    let before_ok = if pos == 0 {
        true
    } else {
        // Find the char whose end byte is at `pos`.
        match corpus[..pos].chars().next_back() {
            Some(ch) => !is_boundary_char(ch),
            None => true,
        }
    };
    if !before_ok {
        return false;
    }
    // Following char must not be [a-z0-9].
    let after_end = pos + variant.len();
    let after_ok = if after_end >= corpus.len() {
        true
    } else {
        match corpus[after_end..].chars().next() {
            Some(ch) => !is_boundary_char(ch),
            None => true,
        }
    };
    after_ok
}

/// All byte offsets where `needle` occurs in `haystack` (non-overlapping).
fn find_all_byte_offsets(haystack: &str, needle: &str) -> Vec<usize> {
    let mut offsets = Vec::new();
    let mut start = 0;
    while let Some(pos) = haystack[start..].find(needle) {
        offsets.push(start + pos);
        start += pos + needle.len();
    }
    offsets
}

/// Match `token` against `corpus` after compacting both sides.
pub fn compact_substring_index(corpus: &str, token: &str) -> Option<usize> {
    let compact_token = compact(token);
    if compact_token.chars().count() < 4 {
        return None;
    }
    let compact_corpus = compact(corpus);
    compact_corpus
        .find(&compact_token)
        .and_then(|pos| compact_index_to_corpus_index(corpus, pos))
}

/// Map an index in `compact(corpus)` back to an index in `corpus`.
pub fn compact_index_to_corpus_index(corpus: &str, compact_index: usize) -> Option<usize> {
    let mut ci = 0usize;
    for (i, ch) in corpus.char_indices() {
        if is_compact_separator(ch) {
            continue;
        }
        if ci == compact_index {
            return Some(i);
        }
        ci += 1;
    }
    // Fallback: return corpus length.
    Some(corpus.len())
}

/// Return lowercase variants for matching a skill name or tag in user text.
pub fn match_variants_for_token(token: &str, skill_name: Option<&str>) -> Vec<String> {
    let base = token.trim().to_lowercase();
    if base.is_empty() {
        return Vec::new();
    }
    let mut variants: Vec<String> = vec![base.clone()];
    if base.contains('-') {
        variants.push(base.replace('-', " "));
        variants.push(base.replace('-', ""));
    }
    if let Some(sn) = skill_name {
        if base == sn.to_lowercase() {
            for alias in builtin_skill_aliases(&sn.to_lowercase()) {
                variants.push(alias.to_string());
            }
        }
    }
    // Deduplicate while preserving order, keeping only variants with len >= 2.
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for variant in variants {
        if variant.chars().count() >= 2 && seen.insert(variant.clone()) {
            out.push(variant);
        }
    }
    out
}

/// Return the earliest start index where `token` matches `corpus`, or `None`.
pub fn earliest_corpus_match(corpus: &str, token: &str, skill_name: Option<&str>) -> Option<usize> {
    let corpus_l = corpus.trim().to_lowercase();
    if corpus_l.is_empty() {
        return None;
    }

    let mut best: Option<usize> = None;
    for variant in match_variants_for_token(token, skill_name) {
        if let Some(pos) = direct_substring_index(&corpus_l, &variant) {
            best = Some(best.map_or(pos, |b| b.min(pos)));
        }
    }

    if let Some(compact_pos) = compact_substring_index(&corpus_l, token) {
        best = Some(best.map_or(compact_pos, |b| b.min(compact_pos)));
    }

    best
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── compact normalization ──────────────────────────────────────

    #[test]
    fn test_compact_removes_whitespace_hyphens_underscores() {
        assert_eq!(compact("claw hub"), "clawhub");
        assert_eq!(compact("claw-hub"), "clawhub");
        assert_eq!(compact("claw_hub"), "clawhub");
        assert_eq!(compact("  Claw  Hub  "), "clawhub");
        assert_eq!(compact("skill-creator"), "skillcreator");
        assert_eq!(compact("MCP Builder"), "mcpbuilder");
    }

    #[test]
    fn test_compact_empty_string() {
        assert_eq!(compact(""), "");
    }

    #[test]
    fn test_compact_preserves_other_punctuation() {
        assert_eq!(compact("wttr.in"), "wttr.in");
    }

    // ── direct substring search ────────────────────────────────────

    #[test]
    fn test_direct_substring_long_token_no_boundary() {
        assert_eq!(
            direct_substring_index("claw hub registry", "claw hub"),
            Some(0)
        );
    }

    #[test]
    fn test_direct_substring_short_token_requires_boundary() {
        // "pr" inside "prior" should NOT match (no word boundary).
        assert_eq!(direct_substring_index("the prior goal", "pr"), None);
        // "pr" with word boundaries should match.
        assert_eq!(
            direct_substring_index("list open pr on git hub", "pr"),
            Some(10)
        );
    }

    #[test]
    fn test_direct_substring_too_short_returns_none() {
        assert_eq!(direct_substring_index("hello", "h"), None);
        assert_eq!(direct_substring_index("hello", ""), None);
    }

    #[test]
    fn test_direct_substring_ci_boundary() {
        // "ci" inside "decision" should NOT match.
        assert_eq!(direct_substring_index("make a decision soon", "ci"), None);
        // "ci" with word boundaries should match.
        assert_eq!(direct_substring_index("check ci on git hub", "ci"), Some(6));
    }

    // ── compact index mapping ───────────────────────────────────────

    #[test]
    fn test_compact_index_to_corpus_index_basic() {
        // corpus: "claw hub" → compact: "clawhub"
        // compact index 0 → corpus index 0 ('c')
        assert_eq!(compact_index_to_corpus_index("claw hub", 0), Some(0));
        // compact index 4 ('h') → corpus index 5 ('h', after the space)
        assert_eq!(compact_index_to_corpus_index("claw hub", 4), Some(5));
        // compact index 7 ('b') → corpus index 8 ('b')
        assert_eq!(compact_index_to_corpus_index("claw hub", 7), Some(8));
    }

    #[test]
    fn test_compact_index_to_corpus_index_with_hyphens() {
        // corpus: "skill-creator" → compact: "skillcreator"
        // compact index 5 ('c') → corpus index 6 ('c', after the hyphen)
        assert_eq!(compact_index_to_corpus_index("skill-creator", 5), Some(6));
    }

    // ── compact substring index ─────────────────────────────────────

    #[test]
    fn test_compact_substring_index_finds_spaced() {
        // "clawhub" compacted = "clawhub", found in compact("claw hub") = "clawhub"
        let pos = compact_substring_index("claw hub", "clawhub");
        assert_eq!(pos, Some(0));
    }

    #[test]
    fn test_compact_substring_index_short_token_returns_none() {
        // compact token < 4 chars → None
        assert_eq!(compact_substring_index("hello world", "ab"), None);
    }

    #[test]
    fn test_compact_substring_index_not_found() {
        assert_eq!(compact_substring_index("hello world", "nonexistent"), None);
    }

    // ── variant matching ───────────────────────────────────────────

    #[test]
    fn test_match_variants_basic() {
        let variants = match_variants_for_token("skill-creator", None);
        assert!(variants.contains(&"skill-creator".to_string()));
        assert!(variants.contains(&"skill creator".to_string()));
        assert!(variants.contains(&"skillcreator".to_string()));
    }

    #[test]
    fn test_match_variants_with_builtin_aliases() {
        let variants = match_variants_for_token("clawhub", Some("clawhub"));
        assert!(variants.contains(&"claw hub".to_string()));
        assert!(variants.contains(&"claw hub registry".to_string()));
    }

    #[test]
    fn test_match_variants_empty_token() {
        assert!(match_variants_for_token("", None).is_empty());
        assert!(match_variants_for_token("   ", None).is_empty());
    }

    #[test]
    fn test_match_variants_single_char_filtered() {
        // Variants with len < 2 are filtered out.
        let variants = match_variants_for_token("a", None);
        assert!(variants.is_empty());
    }

    #[test]
    fn test_match_variants_dedup() {
        // "github" has no hyphen, so only one variant.
        let variants = match_variants_for_token("github", Some("github"));
        assert!(variants.contains(&"github".to_string()));
        assert!(variants.contains(&"git hub".to_string()));
        // No duplicates.
        assert_eq!(
            variants
                .iter()
                .filter(|v| *v == &"github".to_string())
                .count(),
            1
        );
    }

    // ── earliest match ─────────────────────────────────────────────

    #[test]
    fn test_earliest_match_clawhub_spaced() {
        let goal = "is there skill of drawio on claw hub";
        let pos = earliest_corpus_match(goal, "clawhub", Some("clawhub"));
        assert!(pos.is_some());
        let pos = pos.unwrap();
        assert_eq!(&goal[pos..pos + 8], "claw hub");
    }

    #[test]
    fn test_earliest_match_skill_creator() {
        for goal in &[
            "help me create a skill creator guide",
            "update the skill-creator docs",
        ] {
            let pos = earliest_corpus_match(goal, "skill-creator", Some("skill-creator"));
            assert!(pos.is_some(), "failed for: {goal}");
        }
    }

    #[test]
    fn test_earliest_match_mcp_builder() {
        let goal = "help me build an mcp server for github issues";
        let pos = earliest_corpus_match(goal, "mcp-builder", Some("mcp-builder"));
        assert!(pos.is_some());
    }

    #[test]
    fn test_earliest_match_github_git_hub() {
        let goal = "check ci on git hub for soothe repo";
        let pos = earliest_corpus_match(goal, "github", Some("github"));
        assert!(pos.is_some());
    }

    #[test]
    fn test_earliest_match_no_false_positive_short() {
        assert_eq!(earliest_corpus_match("hi", "gh", Some("github")), None);
    }

    #[test]
    fn test_earliest_match_pr_boundary() {
        let continuation = "execution task:\naddress the follow-up request: what subagents do you have. use the prior goal's projected completion report as authoritative background.";
        assert_eq!(
            earliest_corpus_match(continuation, "pr", Some("github")),
            None
        );
        assert_eq!(
            earliest_corpus_match(continuation, "ci", Some("github")),
            None
        );
        assert_eq!(
            earliest_corpus_match("make a decision soon", "ci", Some("github")),
            None
        );
        assert!(earliest_corpus_match("list open pr on git hub", "pr", Some("github")).is_some());
    }

    #[test]
    fn test_earliest_match_empty_corpus() {
        assert_eq!(earliest_corpus_match("", "clawhub", Some("clawhub")), None);
        assert_eq!(
            earliest_corpus_match("   ", "clawhub", Some("clawhub")),
            None
        );
    }
}
