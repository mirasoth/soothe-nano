//! Thinking-token filter for LLM output.
//!
//! Strips inline thinking blocks (``<think>``, ``<thinking>``,
//! ``<reasoning>``) so reasoning tokens never surface as visible content,
//! while capturing stripped content for forwarding to the TUI reasoning branch.
//!
//! ``strip_thinking`` handles complete blocks in a fully-assembled string;
//! ``ThinkingStreamFilter`` handles streaming chunks with partial-tag
//! buffering across chunk boundaries.

use std::sync::OnceLock;

use regex::Regex;

/// Tag variants recognised as thinking-block delimiters (lowercased).
const TAG_VARIANTS: &[&str] = &["think", "thinking", "reasoning"];

/// Lowercased opening-tag strings used for partial-prefix detection.
const OPEN_TAGS_LOWER: &[&str] = &["<think", "<thinking", "<reasoning"];

/// Compiled block regex entry: matches a complete ``<tag>...</tag>`` block.
#[allow(dead_code)]
struct BlockRegex {
    /// Compiled regex for ``<tag>(.*?)</tag>`` (case-insensitive, dotall).
    re: Regex,
    /// The tag variant name (e.g. ``"think"``).
    variant: &'static str,
}

/// Return the lazily-compiled list of per-variant block regexes.
///
/// The Rust ``regex`` crate does not support backreferences, so instead of
/// Python's ``<(thinking|reasoning|think)>(.*?)</\1>`` we compile three
/// separate regexes — one per variant — and iterate in order. The order
/// (``think``, ``thinking``, ``reasoning``) matches Python's alternation
/// order so results are consistent.
fn block_regexes() -> &'static [BlockRegex] {
    static REGEXES: OnceLock<Vec<BlockRegex>> = OnceLock::new();
    REGEXES.get_or_init(|| {
        TAG_VARIANTS
            .iter()
            .map(|tag| {
                let pattern = format!(r"(?is)<{tag}>(.*?)</{tag}>");
                BlockRegex {
                    re: Regex::new(&pattern).unwrap(),
                    variant: tag,
                }
            })
            .collect()
    })
}

/// Lazily-compiled opening-tag regex: ``<(thinking|reasoning|think)>``.
fn think_open_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)<(thinking|reasoning|think)>").unwrap())
}

/// Lazily-compiled closing-tag regex for a given variant.
fn think_close_re(variant: &str) -> &'static Regex {
    match variant {
        "think" => {
            static RE: OnceLock<Regex> = OnceLock::new();
            RE.get_or_init(|| Regex::new(r"(?i)</think>").unwrap())
        }
        "thinking" => {
            static RE: OnceLock<Regex> = OnceLock::new();
            RE.get_or_init(|| Regex::new(r"(?i)</thinking>").unwrap())
        }
        "reasoning" => {
            static RE: OnceLock<Regex> = OnceLock::new();
            RE.get_or_init(|| Regex::new(r"(?i)</reasoning>").unwrap())
        }
        _ => {
            // Unknown variant — fall back to a regex that never matches.
            static RE: OnceLock<Regex> = OnceLock::new();
            RE.get_or_init(|| Regex::new(r"$.^").unwrap())
        }
    }
}

/// Remove complete thinking blocks from *text*.
///
/// Matches ``<think>``, ``<thinking>``, and ``<reasoning>`` variants
/// (case-insensitive; content may span newlines). Only complete blocks
/// (open + matching close) are removed; an unterminated opening tag is
/// left untouched.
///
/// When *capture_sink* is provided, each stripped block's inner text
/// (without tags) is appended in order of appearance.
pub fn strip_thinking(text: &str, capture_sink: Option<&mut Vec<String>>) -> String {
    if text.is_empty() {
        return text.to_string();
    }

    // Collect all matches across all variant regexes, then sort by start
    // position so capture order matches left-to-right appearance in the text.
    // This mirrors Python's single-regex ``sub`` which processes matches
    // left-to-right.
    let mut matches: Vec<(usize, usize, String)> = Vec::new(); // (start, end, inner_content)

    for bg in block_regexes() {
        for caps in bg.re.captures_iter(text) {
            if let Some(full) = caps.get(0) {
                let inner = caps
                    .get(1)
                    .map(|m| m.as_str().to_string())
                    .unwrap_or_default();
                matches.push((full.start(), full.end(), inner));
            }
        }
    }

    if matches.is_empty() {
        return text.to_string();
    }

    // Sort by start position; on ties, prefer the longer match (more specific
    // variant). In practice variants don't overlap at the same position.
    matches.sort_by(|a, b| {
        a.0.cmp(&b.0).then_with(|| b.1.cmp(&a.1)) // longer match first on tie
    });

    // Remove overlapping matches: a match that starts inside a previous
    // match's range is skipped.
    let mut filtered: Vec<&(usize, usize, String)> = Vec::new();
    let mut last_end = 0usize;
    for m in &matches {
        if m.0 >= last_end {
            filtered.push(m);
            last_end = m.1;
        }
    }

    // Build output by stitching non-matched segments together.
    let mut out = String::with_capacity(text.len());
    let mut cursor = 0usize;
    for m in &filtered {
        out.push_str(&text[cursor..m.0]);
        cursor = m.1;
    }
    out.push_str(&text[cursor..]);

    // Push captured inner contents to the sink in order of appearance.
    if let Some(sink) = capture_sink {
        for m in &filtered {
            sink.push(m.2.clone());
        }
    }

    out
}

/// Stateful filter that strips thinking tags from a stream of text chunks.
///
/// Feed each arriving content chunk through [`feed`](Self::feed) and emit the
/// returned text to the consumer. Partial ``<think`` / ``</think`` (and
/// ``<thinking>``, ``<reasoning>``) fragments that arrive split across chunk
/// boundaries are buffered until the tag completes or is ruled out.
///
/// Captured reasoning content (the text inside thinking blocks) is accumulated
/// and available via [`captured_reasoning`](Self::captured_reasoning).
pub struct ThinkingStreamFilter {
    buffer: String,
    inside: bool,
    variant: Option<String>,
    reasoning_parts: Vec<String>,
}

impl ThinkingStreamFilter {
    /// Create a new filter.
    pub fn new() -> Self {
        Self {
            buffer: String::new(),
            inside: false,
            variant: None,
            reasoning_parts: Vec::new(),
        }
    }

    /// Concatenated reasoning text captured from all completed thinking blocks.
    pub fn captured_reasoning(&self) -> String {
        self.reasoning_parts.concat()
    }

    /// Filter *chunk* and return text safe to emit to the consumer.
    pub fn feed(&mut self, chunk: &str) -> String {
        if chunk.is_empty() {
            return String::new();
        }
        self.buffer.push_str(chunk);
        self.drain()
    }

    /// Flush remaining safe text at end-of-stream.
    pub fn finalize(&mut self) -> String {
        if self.inside {
            // Capture unterminated reasoning (the model was cut off mid-think).
            let segment = std::mem::take(&mut self.buffer);
            if !segment.is_empty() {
                self.reasoning_parts.push(segment);
            }
            self.inside = false;
            self.variant = None;
            return String::new();
        }
        std::mem::take(&mut self.buffer)
    }

    /// Core drain loop: process the buffer until no more complete operations
    /// can be performed.
    fn drain(&mut self) -> String {
        let mut out = String::new();

        loop {
            if self.buffer.is_empty() {
                break;
            }

            if self.inside {
                let variant = self.variant.clone().unwrap_or_default();
                let close_re = think_close_re(&variant);
                if let Some(m) = close_re.find(&self.buffer) {
                    let segment = &self.buffer[..m.start()];
                    if !segment.is_empty() {
                        self.reasoning_parts.push(segment.to_string());
                    }
                    self.buffer = self.buffer[m.end()..].to_string();
                    self.inside = false;
                    self.variant = None;
                    continue;
                }
                // No closing tag found — buffer the rest, wait for more chunks.
                break;
            }

            // Not inside a thinking block: look for an opening tag.
            if let Some(m) = think_open_re().find(&self.buffer) {
                out.push_str(&self.buffer[..m.start()]);
                // Extract the variant from capture group 1.
                let variant = if let Some(caps) = think_open_re().captures(&self.buffer) {
                    caps.get(1)
                        .map(|g| g.as_str().to_lowercase())
                        .unwrap_or_default()
                } else {
                    String::new()
                };
                self.variant = Some(variant);
                self.buffer = self.buffer[m.end()..].to_string();
                self.inside = true;
                continue;
            }

            // No opening tag found — check for a trailing partial open-tag prefix.
            let held = self.trailing_open_prefix_len();
            if held > 0 {
                let split_at = self.buffer.len() - held;
                out.push_str(&self.buffer[..split_at]);
                self.buffer = self.buffer[split_at..].to_string();
            } else {
                out.push_str(&self.buffer);
                self.buffer.clear();
            }
            break;
        }

        out
    }

    /// Length of the trailing buffer slice that could still become an opening tag.
    fn trailing_open_prefix_len(&self) -> usize {
        let idx = match self.buffer.rfind('<') {
            Some(i) => i,
            None => return 0,
        };
        let tail = self.buffer[idx..].to_lowercase();
        if OPEN_TAGS_LOWER
            .iter()
            .any(|tag| tag.starts_with(tail.as_str()))
        {
            self.buffer.len() - idx
        } else {
            0
        }
    }
}

impl Default for ThinkingStreamFilter {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── strip_thinking ───────────────────────────────────────────

    #[test]
    fn strip_captures_inner_content() {
        let mut sink = Vec::new();
        let result = strip_thinking(
            "before <thinking>secret reasoning</thinking> after",
            Some(&mut sink),
        );
        assert_eq!(result, "before  after");
        assert_eq!(sink, vec!["secret reasoning"]);
    }

    #[test]
    fn strip_without_sink_discards_content() {
        let result = strip_thinking("before <thinking>hidden</thinking> after", None);
        assert_eq!(result, "before  after");
    }

    #[test]
    fn strip_multiple_blocks_all_captured() {
        let mut sink = Vec::new();
        let result = strip_thinking(
            "a <think>first</think> b <reasoning>second</reasoning> c",
            Some(&mut sink),
        );
        assert_eq!(result, "a  b  c");
        assert_eq!(sink, vec!["first", "second"]);
    }

    #[test]
    fn strip_empty_block_captured_as_empty() {
        let mut sink = Vec::new();
        let result = strip_thinking("text <thinking></thinking> end", Some(&mut sink));
        assert_eq!(result, "text  end");
        assert_eq!(sink, vec![""]);
    }

    #[test]
    fn strip_multiline_content_captured() {
        let mut sink = Vec::new();
        let result = strip_thinking(
            "start <thinking>line1\nline2\nline3</thinking> end",
            Some(&mut sink),
        );
        assert_eq!(result, "start  end");
        assert_eq!(sink, vec!["line1\nline2\nline3"]);
    }

    #[test]
    fn strip_no_blocks_no_change() {
        let mut sink = Vec::new();
        let result = strip_thinking("plain text", Some(&mut sink));
        assert_eq!(result, "plain text");
        assert!(sink.is_empty());
    }

    #[test]
    fn strip_case_insensitive() {
        let mut sink = Vec::new();
        let result = strip_thinking("x <THINKING>Upper</THINKING> y", Some(&mut sink));
        assert_eq!(result, "x  y");
        assert_eq!(sink, vec!["Upper"]);
    }

    #[test]
    fn strip_empty_text() {
        let result = strip_thinking("", None);
        assert_eq!(result, "");
    }

    // ── ThinkingStreamFilter ─────────────────────────────────────

    #[test]
    fn filter_captures_complete_block() {
        let mut filt = ThinkingStreamFilter::new();
        let out1 = filt.feed("hello <thinking>reason");
        let out2 = filt.feed("ing here</thinking> world");
        assert_eq!(out1, "hello ");
        assert_eq!(out2, " world");
        assert_eq!(filt.captured_reasoning(), "reasoning here");
    }

    #[test]
    fn filter_captures_multiple_blocks() {
        let mut filt = ThinkingStreamFilter::new();
        filt.feed("<think>first</think> middle ");
        filt.feed("<reasoning>second</reasoning> end");
        assert_eq!(filt.captured_reasoning(), "firstsecond");
    }

    #[test]
    fn filter_no_capture_without_tags() {
        let mut filt = ThinkingStreamFilter::new();
        filt.feed("just regular text");
        assert_eq!(filt.captured_reasoning(), "");
    }

    #[test]
    fn filter_unterminated_block_captured_on_finalize() {
        let mut filt = ThinkingStreamFilter::new();
        filt.feed("text <thinking>unterminated");
        let result = filt.finalize();
        assert_eq!(result, "");
        assert_eq!(filt.captured_reasoning(), "unterminated");
    }

    #[test]
    fn filter_empty_content_no_capture() {
        let mut filt = ThinkingStreamFilter::new();
        filt.feed("");
        assert_eq!(filt.captured_reasoning(), "");
    }

    #[test]
    fn filter_partial_open_tag_buffered() {
        let mut filt = ThinkingStreamFilter::new();
        let out1 = filt.feed("hello <thin");
        let out2 = filt.feed("king>secret</thinking> world");
        assert_eq!(out1, "hello ");
        assert_eq!(out2, " world");
        assert_eq!(filt.captured_reasoning(), "secret");
    }

    #[test]
    fn filter_finalizes_remaining_text() {
        let mut filt = ThinkingStreamFilter::new();
        let out = filt.feed("hello world");
        assert_eq!(out, "hello world");
        let result = filt.finalize();
        assert_eq!(result, "");
    }
}
