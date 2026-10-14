//! Compact logging formatter helpers (ported from `utils/logging.py`).
//!
//! Pure string manipulation — no Python-specific dependencies.

/// Standard `logging` level constants (mirrors `logging.DEBUG` etc.).
const LEVEL_DEBUG: i32 = 10;
const LEVEL_INFO: i32 = 20;
const LEVEL_WARNING: i32 = 30;
const LEVEL_ERROR: i32 = 40;
const LEVEL_CRITICAL: i32 = 50;

/// Return the one-letter code for a logging level number.
///
/// Maps `DEBUG→'D'`, `INFO→'I'`, `WARNING→'W'`, `ERROR→'E'`,
/// `CRITICAL→'C'`, and any other value → `'?'`.
pub fn short_level_letter(levelno: i32) -> char {
    match levelno {
        LEVEL_DEBUG => 'D',
        LEVEL_INFO => 'I',
        LEVEL_WARNING => 'W',
        LEVEL_ERROR => 'E',
        LEVEL_CRITICAL => 'C',
        _ => '?',
    }
}

/// Abbreviate a dotted logger path, keeping the last two segments intact.
///
/// Each earlier segment becomes its first character (empty segments → `'?'`).
/// Strings with fewer than three segments are returned unchanged.
///
/// Example: `soothe_nano.core.events` → `s.core.events`.
pub fn abbreviate_logger_name(name: &str) -> String {
    if name.is_empty() {
        return String::new();
    }
    // Split on '.' — matches Python's str.split(".").
    let parts: Vec<&str> = name.split('.').collect();
    if parts.len() <= 2 {
        return name.to_string();
    }
    let head_count = parts.len() - 2;
    let mut pieces: Vec<String> = Vec::with_capacity(parts.len());
    for p in &parts[..head_count] {
        let c = p.chars().next().unwrap_or('?');
        pieces.push(c.to_string());
    }
    for p in &parts[head_count..] {
        pieces.push(p.to_string());
    }
    pieces.join(".")
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── short_level_letter ───────────────────────────────────────

    #[test]
    fn level_debug() {
        assert_eq!(short_level_letter(10), 'D');
    }

    #[test]
    fn level_info() {
        assert_eq!(short_level_letter(20), 'I');
    }

    #[test]
    fn level_warning() {
        assert_eq!(short_level_letter(30), 'W');
    }

    #[test]
    fn level_error() {
        assert_eq!(short_level_letter(40), 'E');
    }

    #[test]
    fn level_critical() {
        assert_eq!(short_level_letter(50), 'C');
    }

    #[test]
    fn level_unknown() {
        assert_eq!(short_level_letter(0), '?');
        assert_eq!(short_level_letter(99), '?');
        assert_eq!(short_level_letter(-1), '?');
    }

    // ── abbreviate_logger_name ───────────────────────────────────

    #[test]
    fn abbrev_empty() {
        assert_eq!(abbreviate_logger_name(""), "");
    }

    #[test]
    fn abbrev_single_segment() {
        assert_eq!(abbreviate_logger_name("root"), "root");
    }

    #[test]
    fn abbrev_two_segments() {
        assert_eq!(abbreviate_logger_name("soothe.core"), "soothe.core");
    }

    #[test]
    fn abbrev_three_segments() {
        assert_eq!(
            abbreviate_logger_name("soothe_nano.core.events"),
            "s.core.events"
        );
    }

    #[test]
    fn abbrev_many_segments() {
        // 7 segments → 5 head segments abbreviated, last 2 kept.
        assert_eq!(
            abbreviate_logger_name("a.b.c.d.e.f.events"),
            "a.b.c.d.e.f.events"
        );
    }

    #[test]
    fn abbrev_empty_head_segment() {
        // Empty segment → '?' (matches Python `p[0] if p else "?"`).
        assert_eq!(abbreviate_logger_name("..core.events"), "?.?.core.events");
    }

    #[test]
    fn abbrev_mixed_empty_segment() {
        assert_eq!(
            abbreviate_logger_name("a..b.core.events"),
            "a.?.b.core.events"
        );
    }
}
