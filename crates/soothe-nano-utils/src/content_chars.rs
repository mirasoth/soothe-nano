//! Content character counting and token-usage coercion.

/// Best-effort character count for a plain string.
pub fn count_str_chars(s: &str) -> usize {
    s.chars().count()
}

/// Coerce an arbitrary value into a non-negative `i64` token count.
///
/// `None`, empty string, or non-numeric values yield `0`; negative values are clamped to `0`.
pub fn coerce_total_tokens_used(value: Option<i64>) -> i64 {
    value.unwrap_or(0).max(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn count_str_chars_ascii() {
        assert_eq!(count_str_chars("hello"), 5);
    }

    #[test]
    fn count_str_chars_empty() {
        assert_eq!(count_str_chars(""), 0);
    }

    #[test]
    fn count_str_chars_multibyte() {
        // Each CJK char is one Unicode scalar → 9 chars.
        assert_eq!(count_str_chars("使用浏览器获取信息"), 9);
    }

    #[test]
    fn coerce_none() {
        assert_eq!(coerce_total_tokens_used(None), 0);
    }

    #[test]
    fn coerce_positive() {
        assert_eq!(coerce_total_tokens_used(Some(42)), 42);
    }

    #[test]
    fn coerce_negative_clamps() {
        assert_eq!(coerce_total_tokens_used(Some(-5)), 0);
    }

    #[test]
    fn coerce_zero() {
        assert_eq!(coerce_total_tokens_used(Some(0)), 0);
    }
}
