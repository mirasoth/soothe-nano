//! Text preview with truncation (ported from `utils/text_preview.py`).

/// Produce a single-line preview of `text`, truncated to `max_chars`.
pub fn text_preview(text: &str, max_chars: usize) -> String {
    let collapsed: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.chars().count() <= max_chars {
        return collapsed;
    }
    let truncated: String = collapsed
        .chars()
        .take(max_chars.saturating_sub(3))
        .collect();
    format!("{truncated}...")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_text_unchanged() {
        assert_eq!(text_preview("hello world", 100), "hello world");
    }

    #[test]
    fn long_text_truncated() {
        let out = text_preview("hello world foo bar baz", 10);
        assert!(out.ends_with("..."));
        assert!(out.chars().count() <= 10);
    }
}
