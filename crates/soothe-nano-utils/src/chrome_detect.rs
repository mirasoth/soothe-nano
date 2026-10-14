//! Chrome/Electron process detection helpers (ported from `utils/browser_cdp.py`).
//!
//! Pure string-pattern logic for identifying Chrome-like processes and
//! extracting metadata from process command lines.

use regex::Regex;
use std::sync::OnceLock;

/// Known Chrome/Chromium/Electron/Edge/Brave executable names (lowercased).
const CHROME_EXE_NAMES: &[&str] = &[
    "google chrome",
    "google chrome helper",
    "google chrome helper (renderer)",
    "google chrome helper (gpu)",
    "google chrome helper (plugin)",
    "chrome",
    "chromium",
    "chromium-browser",
    "chromium-browser-lite",
    "microsoft edge",
    "microsoft edge helper",
    "msedge",
    "edge",
    "electron",
    "electron helper",
    "electron helper (renderer)",
    "electron helper (gpu)",
    "brave",
    "brave-browser",
];

/// Basenames that can appear as a word inside a longer name (for substring match).
const WORD_MATCH_NAMES: &[&str] = &["chrome", "chromium", "electron", "edge", "brave"];

/// Return true if an executable basename is a known Chrome/Electron name.
///
/// `exe_name` is matched case-insensitively against the known set. A bare
/// `chrome` / `electron` token embedded as a *word* in the name also counts
/// so that macOS app-bundle names like `Google Chrome Helper (Renderer)`
/// match, without false-matching `edge` inside `knowledge-agent`.
pub fn exe_name_is_chrome_like(exe_name: &str) -> bool {
    if exe_name.is_empty() {
        return false;
    }
    let lowered = exe_name.to_lowercase();
    if CHROME_EXE_NAMES.contains(&lowered.as_str()) {
        return true;
    }
    // Word-boundary match for known basenames.
    for name in WORD_MATCH_NAMES {
        if word_boundary_match(&lowered, name) {
            return true;
        }
    }
    false
}

/// Check if `name` appears as a word (bounded by non-alphanumeric chars or
/// string boundaries) in `lowered`.
fn word_boundary_match(lowered: &str, name: &str) -> bool {
    if name.is_empty() {
        return false;
    }
    let bytes = lowered.as_bytes();
    let name_bytes = name.as_bytes();
    let name_len = name_bytes.len();
    if name_len > bytes.len() {
        return false;
    }

    let mut i = 0usize;
    while i + name_len <= bytes.len() {
        // Check the substring matches.
        if &bytes[i..i + name_len] == name_bytes {
            // Check left boundary: start of string or non-alphanumeric.
            let left_ok = i == 0 || !is_alphanumeric(bytes[i - 1]);
            // Check right boundary: end of string or non-alphanumeric.
            let right_end = i + name_len;
            let right_ok = right_end >= bytes.len() || !is_alphanumeric(bytes[right_end]);
            if left_ok && right_ok {
                return true;
            }
        }
        i += 1;
    }
    false
}

/// Check if a byte is an ASCII alphanumeric character.
fn is_alphanumeric(b: u8) -> bool {
    b.is_ascii_alphanumeric()
}

/// Extract the executable path from a ps cmdline string.
///
/// `ps` output is `"<pid> <exe-and-flags>"` after the PID is stripped. The
/// executable may contain spaces (macOS app bundles), so we accumulate
/// leading tokens until the first token that starts with `-` (a flag).
/// Returns the joined executable path, or `""`.
pub fn extract_exe_path_from_args(args: &str) -> String {
    let tokens: Vec<&str> = args.split_whitespace().collect();
    let mut exe_tokens: Vec<&str> = Vec::new();
    for tok in tokens {
        if tok.starts_with('-') {
            break;
        }
        exe_tokens.push(tok);
    }
    exe_tokens.join(" ")
}

/// Check if a process looks like Chrome/Electron based on its args.
///
/// A process is relevant if it was launched with `--remote-debugging-port`
/// AND its executable name matches a known Chrome-like name.
pub fn is_chrome_like_process(args: &str, exe_name: &str) -> bool {
    if !args.contains("--remote-debugging-port=") {
        return false;
    }
    let name = if exe_name.is_empty() {
        extract_exe_path_from_args(args)
    } else {
        exe_name.to_string()
    };
    exe_name_is_chrome_like(&name)
}

/// Extract the `--user-data-dir` value from a command-line args string.
pub fn extract_user_data_dir(args: &str) -> Option<String> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"--user-data-dir=(\S+)").unwrap());
    re.captures(args).map(|c| c[1].to_string())
}

/// Extract the `--remote-debugging-port` value from a command-line args string.
pub fn extract_debug_port(args: &str) -> Option<String> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"--remote-debugging-port=(\d+)").unwrap());
    re.captures(args).map(|c| c[1].to_string())
}

/// Extract the owning PID from a Chromium SingletonLock symlink target.
///
/// Chromium writes the target as `<hostname>-<pid>`. This extracts the
/// trailing integer PID. Returns `None` if no PID can be parsed.
pub fn parse_singleton_owner_pid(symlink_target: &str) -> Option<i64> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"-(\d+)$").unwrap());
    let caps = re.captures(symlink_target)?;
    caps[1].parse::<i64>().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── exe_name_is_chrome_like ──────────────────────────────────

    #[test]
    fn exact_match_chrome() {
        assert!(exe_name_is_chrome_like("chrome"));
    }

    #[test]
    fn exact_match_chromium_browser() {
        assert!(exe_name_is_chrome_like("chromium-browser"));
    }

    #[test]
    fn case_insensitive_match() {
        assert!(exe_name_is_chrome_like("Google Chrome"));
    }

    #[test]
    fn macos_helper_variant() {
        assert!(exe_name_is_chrome_like("Google Chrome Helper (Renderer)"));
    }

    #[test]
    fn electron_match() {
        assert!(exe_name_is_chrome_like("electron"));
    }

    #[test]
    fn edge_match() {
        assert!(exe_name_is_chrome_like("msedge"));
    }

    #[test]
    fn brave_match() {
        assert!(exe_name_is_chrome_like("brave-browser"));
    }

    #[test]
    fn non_chrome_rejected() {
        assert!(!exe_name_is_chrome_like("python"));
        assert!(!exe_name_is_chrome_like("node"));
    }

    #[test]
    fn edge_inside_knowledge_agent_not_matched() {
        // "edge" inside "knowledge-agent" must NOT match (word boundary).
        assert!(!exe_name_is_chrome_like("knowledge-agent"));
    }

    #[test]
    fn empty_rejected() {
        assert!(!exe_name_is_chrome_like(""));
    }

    // ── extract_exe_path_from_args ───────────────────────────────

    #[test]
    fn extract_simple_exe() {
        let args = "/usr/bin/chrome --foo bar";
        assert_eq!(extract_exe_path_from_args(args), "/usr/bin/chrome");
    }

    #[test]
    fn extract_macos_bundle_exe() {
        let args =
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --remote-debugging-port=9222";
        assert_eq!(
            extract_exe_path_from_args(args),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        );
    }

    #[test]
    fn extract_stops_at_flag() {
        let args = "chrome --headless --port=9222";
        assert_eq!(extract_exe_path_from_args(args), "chrome");
    }

    #[test]
    fn extract_empty_args() {
        assert_eq!(extract_exe_path_from_args(""), "");
    }

    // ── is_chrome_like_process ───────────────────────────────────

    #[test]
    fn chrome_like_process_with_debug_port() {
        assert!(is_chrome_like_process(
            "chrome --remote-debugging-port=9222",
            "chrome"
        ));
    }

    #[test]
    fn chrome_like_process_without_debug_port() {
        assert!(!is_chrome_like_process("chrome --headless", "chrome"));
    }

    #[test]
    fn chrome_like_process_non_chrome_exe() {
        assert!(!is_chrome_like_process(
            "python --remote-debugging-port=9222",
            "python"
        ));
    }

    // ── extract_user_data_dir ────────────────────────────────────

    #[test]
    fn extract_udd() {
        let args = "chrome --user-data-dir=/tmp/foo --port=9222";
        assert_eq!(extract_user_data_dir(args), Some("/tmp/foo".to_string()));
    }

    #[test]
    fn extract_udd_none_when_absent() {
        assert!(extract_user_data_dir("chrome --port=9222").is_none());
    }

    // ── extract_debug_port ───────────────────────────────────────

    #[test]
    fn extract_port() {
        let args = "chrome --remote-debugging-port=9222";
        assert_eq!(extract_debug_port(args), Some("9222".to_string()));
    }

    #[test]
    fn extract_port_none_when_absent() {
        assert!(extract_debug_port("chrome --headless").is_none());
    }

    // ── parse_singleton_owner_pid ───────────────────────────────

    #[test]
    fn parse_pid_from_hostname_pid() {
        assert_eq!(parse_singleton_owner_pid("myhost-12345"), Some(12345));
    }

    #[test]
    fn parse_pid_from_dashed_hostname() {
        // Hostname with hyphens: "my-host-name-67890"
        assert_eq!(parse_singleton_owner_pid("my-host-name-67890"), Some(67890));
    }

    #[test]
    fn parse_pid_none_when_no_digits() {
        assert!(parse_singleton_owner_pid("no-pid-here").is_none());
    }

    #[test]
    fn parse_pid_none_when_empty() {
        assert!(parse_singleton_owner_pid("").is_none());
    }
}
