//! Thread ID log suffix.

const THREAD_ID_LOG_SUFFIX_LEN: usize = 4;

/// Return the last N characters of a thread ID for compact, distinctive log tags.
pub fn short_thread_id_for_log(thread_id: &str) -> String {
    let tid = thread_id.trim();
    if tid.is_empty() {
        return String::new();
    }
    if tid.len() <= THREAD_ID_LOG_SUFFIX_LEN {
        return tid.to_string();
    }
    tid[tid.len() - THREAD_ID_LOG_SUFFIX_LEN..].to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty() {
        assert_eq!(short_thread_id_for_log(""), "");
        assert_eq!(short_thread_id_for_log("  "), "");
    }

    #[test]
    fn test_short_id() {
        assert_eq!(short_thread_id_for_log("abc"), "abc");
        assert_eq!(short_thread_id_for_log("abcd"), "abcd");
    }

    #[test]
    fn test_long_id() {
        assert_eq!(short_thread_id_for_log("abcdef123456"), "3456");
    }

    #[test]
    fn test_whitespace_trimmed() {
        assert_eq!(short_thread_id_for_log("  abcdef123456  "), "3456");
    }
}
