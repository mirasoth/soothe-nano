//! Local wall-clock helpers for LLM prompts (ported from `utils/prompt_clock.py`).

use chrono::{DateTime, Datelike, Local, Utc};
use chrono_tz::Tz;

/// Resolve an optional IANA timezone name into a `Tz`.
fn parse_tz(tz: Option<&str>) -> Option<Tz> {
    tz.filter(|s| !s.is_empty())
        .and_then(|s| s.parse::<Tz>().ok())
}

/// Detect the system local IANA timezone name.
/// Precedence: `TZ` env var → `/etc/localtime` symlink → offset abbreviation.
fn detect_local_tz_label() -> String {
    if let Ok(tz_env) = std::env::var("TZ") {
        if !tz_env.is_empty() {
            return tz_env;
        }
    }
    if let Ok(target) = std::fs::read_link("/etc/localtime") {
        if let Some(name) = extract_zoneinfo_name(&target) {
            return name;
        }
    }
    Local::now().format("%Z").to_string()
}

/// Extract the IANA timezone name from a `/etc/localtime` symlink target.
fn extract_zoneinfo_name(path: &std::path::Path) -> Option<String> {
    let s = path.to_string_lossy();
    let marker = "zoneinfo/";
    if let Some(idx) = s.rfind(marker) {
        let rest = &s[idx + marker.len()..];
        if !rest.is_empty() {
            return Some(rest.to_string());
        }
    }
    None
}

/// Split a Unix timestamp (f64 seconds) into integer seconds + nanoseconds.
fn split_timestamp(ts: f64) -> (i64, u32) {
    let secs = ts as i64;
    let nanos = ((ts - secs as f64).abs() * 1_000_000_000.0) as u32;
    (secs, nanos)
}

/// Convert a Unix timestamp into a `DateTime<Tz>`.
fn timestamp_to_tz(ts: f64, tz_parsed: Tz) -> DateTime<Tz> {
    let (secs, nanos) = split_timestamp(ts);
    DateTime::from_timestamp(secs, nanos)
        .unwrap_or_else(|| DateTime::from_timestamp(0, 0).unwrap())
        .with_timezone(&tz_parsed)
}

/// Convert a Unix timestamp into a `DateTime<Local>`.
fn timestamp_to_local(ts: f64) -> DateTime<Local> {
    let (secs, nanos) = split_timestamp(ts);
    DateTime::from_timestamp(secs, nanos)
        .unwrap_or_else(|| DateTime::from_timestamp(0, 0).unwrap())
        .with_timezone(&Local)
}

/// Current time as ISO-8601 with offset.
pub fn now_local(tz: Option<&str>) -> String {
    if let Some(tz_parsed) = parse_tz(tz) {
        return Utc::now().with_timezone(&tz_parsed).to_rfc3339();
    }
    Local::now().to_rfc3339()
}

/// Local calendar date (`YYYY-MM-DD`) for a Unix timestamp.
pub fn local_date_str(ts: f64, tz: Option<&str>) -> String {
    match parse_tz(tz) {
        Some(tz_parsed) => timestamp_to_tz(ts, tz_parsed)
            .format("%Y-%m-%d")
            .to_string(),
        None => timestamp_to_local(ts).format("%Y-%m-%d").to_string(),
    }
}

/// Local wall time (`HH:MM:SS`) for a Unix timestamp.
pub fn local_time_str(ts: f64, tz: Option<&str>) -> String {
    match parse_tz(tz) {
        Some(tz_parsed) => timestamp_to_tz(ts, tz_parsed)
            .format("%H:%M:%S")
            .to_string(),
        None => timestamp_to_local(ts).format("%H:%M:%S").to_string(),
    }
}

/// ISO-8601 timestamp for a Unix timestamp (includes offset).
pub fn local_timestamp_iso(ts: f64, tz: Option<&str>) -> String {
    match parse_tz(tz) {
        Some(tz_parsed) => timestamp_to_tz(ts, tz_parsed).to_rfc3339(),
        None => timestamp_to_local(ts).to_rfc3339(),
    }
}

/// IANA timezone name or fallback label for the local zone.
pub fn local_timezone_label(tz: Option<&str>) -> String {
    if let Some(tz_str) = tz.filter(|s| !s.is_empty()) {
        return tz_str.to_string();
    }
    detect_local_tz_label()
}

/// Date/time fields for prompt templates as a JSON string.
pub fn prompt_datetime_context(tz: Option<&str>) -> String {
    let now = Utc::now().timestamp() as f64;
    let date = local_date_str(now, tz);
    let time = local_time_str(now, tz);
    let label = local_timezone_label(tz);
    serde_json::json!({
        "current_date": date,
        "current_time": time,
        "schedule_timezone": label,
    })
    .to_string()
}

/// User-facing local date (e.g. `October 14, 2026`) for a Unix timestamp.
pub fn format_friendly_local_date(ts: f64, tz: Option<&str>) -> String {
    let (month, day, year) = match parse_tz(tz) {
        Some(tz_parsed) => {
            let dt = timestamp_to_tz(ts, tz_parsed);
            (dt.format("%B").to_string(), dt.day(), dt.year())
        }
        None => {
            let dt = timestamp_to_local(ts);
            (dt.format("%B").to_string(), dt.day(), dt.year())
        }
    };
    format!("{month} {day}, {year}")
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Fixed timestamp: 2026-10-14T00:00:00Z (UTC).
    const FIXED_TS: f64 = 1_791_936_000.0;

    #[test]
    fn now_local_returns_iso_string() {
        let s = now_local(None);
        assert!(!s.is_empty());
        assert!(s.contains('T') || s.contains('Z') || s.contains('+'));
    }

    #[test]
    fn now_local_with_explicit_tz() {
        let s = now_local(Some("America/New_York"));
        assert!(s.contains('T'));
        assert!(s.contains("-04:00") || s.contains("-05:00"));
    }

    #[test]
    fn now_local_with_invalid_tz_falls_back_to_local() {
        let s = now_local(Some("Not/A_Real_Zone"));
        assert!(!s.is_empty());
        assert!(s.contains('T'));
    }

    #[test]
    fn local_date_str_basic_format() {
        assert_eq!(local_date_str(FIXED_TS, Some("UTC")), "2026-10-14");
    }

    #[test]
    fn local_date_str_timezone_shift() {
        assert_eq!(
            local_date_str(FIXED_TS, Some("America/New_York")),
            "2026-10-13"
        );
    }

    #[test]
    fn local_time_str_basic_format() {
        assert_eq!(local_time_str(FIXED_TS, Some("UTC")), "00:00:00");
    }

    #[test]
    fn local_time_str_timezone_shift() {
        assert_eq!(
            local_time_str(FIXED_TS, Some("America/New_York")),
            "20:00:00"
        );
    }

    #[test]
    fn local_timestamp_iso_basic() {
        let s = local_timestamp_iso(FIXED_TS, Some("UTC"));
        assert!(s.starts_with("2026-10-14T00:00:00"));
        assert!(s.contains('+') || s.ends_with('Z'));
    }

    #[test]
    fn local_timestamp_iso_includes_offset() {
        let s = local_timestamp_iso(FIXED_TS, Some("Asia/Shanghai"));
        assert!(s.contains("+08:00"));
        assert!(s.starts_with("2026-10-14T08:00:00"));
    }

    #[test]
    fn local_timezone_label_explicit_tz() {
        assert_eq!(local_timezone_label(Some("Asia/Shanghai")), "Asia/Shanghai");
        assert_eq!(
            local_timezone_label(Some("America/New_York")),
            "America/New_York"
        );
    }

    #[test]
    fn local_timezone_label_empty_falls_back_to_local() {
        let label = local_timezone_label(None);
        assert!(!label.is_empty());
    }

    #[test]
    fn local_timezone_label_unparseable_returned_as_is() {
        assert_eq!(local_timezone_label(Some("Custom/Zone")), "Custom/Zone");
    }

    #[test]
    fn prompt_datetime_context_is_valid_json() {
        let s = prompt_datetime_context(Some("UTC"));
        let v: serde_json::Value = serde_json::from_str(&s).expect("must be valid JSON");
        assert!(v.is_object());
        assert!(v.get("current_date").is_some());
        assert!(v.get("current_time").is_some());
        assert!(v.get("schedule_timezone").is_some());
    }

    #[test]
    fn prompt_datetime_context_fields_consistent() {
        let s = prompt_datetime_context(Some("UTC"));
        let v: serde_json::Value = serde_json::from_str(&s).unwrap();
        let date = v["current_date"].as_str().unwrap();
        let tz = v["schedule_timezone"].as_str().unwrap();
        assert_eq!(date.len(), 10);
        assert_eq!(tz, "UTC");
    }

    #[test]
    fn format_friendly_local_date_basic() {
        assert_eq!(
            format_friendly_local_date(FIXED_TS, Some("UTC")),
            "October 14, 2026"
        );
    }

    #[test]
    fn format_friendly_local_date_timezone_shift() {
        assert_eq!(
            format_friendly_local_date(FIXED_TS, Some("America/New_York")),
            "October 13, 2026"
        );
    }

    #[test]
    fn format_friendly_local_date_shanghai() {
        assert_eq!(
            format_friendly_local_date(FIXED_TS, Some("Asia/Shanghai")),
            "October 14, 2026"
        );
    }

    #[test]
    fn timestamp_with_fractional_seconds() {
        let ts = FIXED_TS + 30.5;
        assert_eq!(local_time_str(ts, Some("UTC")), "00:00:30");
    }

    #[test]
    fn empty_tz_string_treated_as_none() {
        let label = local_timezone_label(Some(""));
        assert!(!label.is_empty());
    }
}
