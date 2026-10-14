//! Operation guard: path validation, policy, and rate limiting.

use crate::command_guard::rule_family;
use crate::path_security::{PathValidator, ValidationResult};
use crate::policy_models::PolicyAction;
use crate::rate_limiter::RateLimiter;
use crate::SecurityPolicy;
use fancy_regex::Regex;
use std::collections::HashSet;
use std::sync::OnceLock;

/// Record of an operation to be checked.
#[derive(Debug, Clone)]
pub struct OperationRecord {
    pub operation: String,
    pub path: String,
    pub size: Option<u64>,
}

/// Guards operations against path validation, policy, and rate limiting.
pub struct OperationGuard {
    validator: PathValidator,
    policy: SecurityPolicy,
    rate_limiter: RateLimiter,
}

impl OperationGuard {
    pub fn new(
        workspace: impl Into<std::path::PathBuf>,
        policy: SecurityPolicy,
        rate_limiter: RateLimiter,
    ) -> Self {
        Self {
            validator: PathValidator::new(workspace),
            policy,
            rate_limiter,
        }
    }

    /// Check an operation against rate limit, policy, and path validation.
    pub fn check(&self, op: &OperationRecord) -> Result<ValidationResult, crate::SecurityError> {
        if !self.rate_limiter.try_consume(&op.operation) {
            return Err(crate::SecurityError::RateLimited);
        }

        let action = self.policy.evaluate_path(&op.path);
        if action == PolicyAction::Deny {
            return Err(crate::SecurityError::PolicyDeny(format!(
                "path '{}' denied by policy",
                op.path
            )));
        }

        let result = self.validator.validate(&op.path);
        if !result.is_valid {
            return Err(crate::SecurityError::PathValidation(result.message));
        }

        Ok(result)
    }
}

/// Bypass-immune dangerous path components.
static DANGEROUS_PATH_COMPONENTS: OnceLock<HashSet<&'static str>> = OnceLock::new();

fn dangerous_path_components() -> &'static HashSet<&'static str> {
    DANGEROUS_PATH_COMPONENTS.get_or_init(|| {
        [
            ".git",
            ".svn",
            ".hg",
            ".vscode",
            ".idea",
            ".claude",
            ".bashrc",
            ".bash_profile",
            ".zshrc",
            ".zprofile",
            ".profile",
            ".gitconfig",
            ".gitmodules",
            ".ripgreprc",
            ".mcp.json",
            ".claude.json",
        ]
        .into_iter()
        .collect()
    })
}

/// Find a dangerous path component in `path`.
///
/// Returns `Some(component)` when a dangerous component is found.
pub fn find_dangerous_path_component(path: &str) -> Option<&'static str> {
    for part in path.split('/') {
        if let Some(&comp) = dangerous_path_components().get(part) {
            return Some(comp);
        }
    }
    // Also check backslash-separated components (Windows-style).
    for part in path.split('\\') {
        if let Some(&comp) = dangerous_path_components().get(part) {
            return Some(comp);
        }
    }
    None
}

/// Sensitive system path patterns (mirrors `_SENSITIVE_SYSTEM_PATH_PATTERNS`).
static SENSITIVE_SYSTEM_PATH_PATTERNS: OnceLock<Vec<&str>> = OnceLock::new();

fn sensitive_system_path_patterns() -> &'static Vec<&'static str> {
    SENSITIVE_SYSTEM_PATH_PATTERNS.get_or_init(|| {
        vec![
            "/etc/**",
            "/bin/**",
            "/sbin/**",
            "/usr/**",
            "/System/**",
            "/Library/**",
            "/private/etc/**",
        ]
    })
}

/// Check if a path matches a sensitive system path pattern using fnmatch-style glob.
pub fn matches_sensitive_system_path(path: &str) -> Option<&'static str> {
    for pattern in sensitive_system_path_patterns() {
        if glob_match(pattern, path) {
            return Some(*pattern);
        }
    }
    None
}

/// `kill [-signal…] <pid>…` invocation regex (not killall).
static KILL_INVOCATION_RE: OnceLock<Regex> = OnceLock::new();

fn kill_invocation_regex() -> &'static Regex {
    KILL_INVOCATION_RE.get_or_init(|| {
        Regex::new(r"(?:^|[;&|\n])\s*kill\b(?!\s*all\b)(?P<args>[^\n;&|]*)")
            .expect("invalid kill invocation regex")
    })
}

/// Parse numeric PIDs from `kill` argument text (skip signal tokens).
pub fn pids_from_kill_args(args: &str) -> Vec<i64> {
    let mut pids: Vec<i64> = Vec::new();
    let tokens: Vec<&str> = args.split_whitespace().collect();
    let mut i = 0;
    while i < tokens.len() {
        let token = tokens[i];
        if token == "-s" && i + 1 < tokens.len() {
            i += 2;
            continue;
        }
        if token.starts_with('-') {
            // Signal form: -9, -TERM, -SIGKILL — not a PID.
            i += 1;
            continue;
        }
        if let Ok(pid) = token.parse::<i64>() {
            pids.push(pid);
        }
        i += 1;
    }
    pids
}

/// Find all `kill <pid>` invocations in a command string and return their PIDs.
pub fn kill_invocation_pids(command: &str) -> Vec<i64> {
    let re = kill_invocation_regex();
    let mut pids: Vec<i64> = Vec::new();
    for caps in re.captures_iter(command).flatten() {
        if let Some(args) = caps.name("args") {
            pids.extend(pids_from_kill_args(args.as_str()));
        }
    }
    pids
}

/// Check if a command was already approved by an allowlist entry.
///
/// An allowlist entry is either:
/// - `{"tool": "run_command", "signature": "<exact command>"}` — exact match
/// - `{"rule": "<rule_id>"}` — rule family match
///
/// `allowlist` is a list of `(tool, signature, rule)` tuples.
pub fn command_approved_by_allowlist(
    command: &str,
    rule_id: Option<&str>,
    allowlist: &[(String, Option<String>, Option<String>)],
) -> bool {
    if allowlist.is_empty() {
        return false;
    }
    let cmd = command.trim();
    let approved_rules: HashSet<String> = rule_id
        .map(|rid| rule_family(rid).into_iter().collect())
        .unwrap_or_default();

    for (tool, signature, rule) in allowlist {
        if tool == "run_command" && !cmd.is_empty() {
            if let Some(sig) = signature {
                if sig == cmd {
                    return true;
                }
            }
        }
        if let Some(rule) = rule {
            if !rule.is_empty() && approved_rules.contains(rule) {
                return true;
            }
        }
    }
    false
}

/// Simple fnmatch-style glob matcher (supports `*` and `?`).
pub fn glob_match(pattern: &str, path: &str) -> bool {
    if path.starts_with(pattern.trim_end_matches('*')) {
        return true;
    }
    fnmatch(pattern, path)
}

/// fnmatch implementation (case-sensitive on Unix).
fn fnmatch(pattern: &str, text: &str) -> bool {
    let pat: Vec<char> = pattern.chars().collect();
    let txt: Vec<char> = text.chars().collect();
    fnmatch_inner(&pat[..], &txt[..])
}

fn fnmatch_inner(pat: &[char], txt: &[char]) -> bool {
    let (mut pi, mut ti) = (0, 0);
    let mut star_pat: Option<usize> = None;
    let mut star_txt: usize = 0;

    while ti < txt.len() {
        if pi < pat.len() && pat[pi] == '?' {
            pi += 1;
            ti += 1;
        } else if pi < pat.len() && pat[pi] == '*' {
            star_pat = Some(pi);
            star_txt = ti;
            pi += 1;
        } else if pi < pat.len() && pat[pi] == txt[ti] {
            pi += 1;
            ti += 1;
        } else if let Some(sp) = star_pat {
            pi = sp + 1;
            star_txt += 1;
            ti = star_txt;
        } else {
            return false;
        }
    }
    while pi < pat.len() && pat[pi] == '*' {
        pi += 1;
    }
    pi == pat.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_dangerous_component_git() {
        assert_eq!(
            find_dangerous_path_component("src/.git/config"),
            Some(".git")
        );
    }

    #[test]
    fn finds_dangerous_component_bashrc() {
        assert_eq!(
            find_dangerous_path_component("home/.bashrc"),
            Some(".bashrc")
        );
    }

    #[test]
    fn no_dangerous_component_in_clean_path() {
        assert!(find_dangerous_path_component("src/main.rs").is_none());
    }

    #[test]
    fn matches_sensitive_system_etc() {
        assert_eq!(
            matches_sensitive_system_path("/etc/passwd"),
            Some("/etc/**")
        );
    }

    #[test]
    fn no_match_for_workspace_path() {
        assert!(matches_sensitive_system_path("/workspace/src/main.rs").is_none());
    }

    #[test]
    fn pids_from_kill_args_simple() {
        let pids = pids_from_kill_args("12345 67890");
        assert_eq!(pids, vec![12345, 67890]);
    }

    #[test]
    fn pids_from_kill_args_with_signal() {
        let pids = pids_from_kill_args("-9 12345");
        assert_eq!(pids, vec![12345]);
    }

    #[test]
    fn pids_from_kill_args_with_s_flag() {
        let pids = pids_from_kill_args("-s TERM 12345");
        assert_eq!(pids, vec![12345]);
    }

    #[test]
    fn pids_from_kill_args_skips_non_numeric() {
        let pids = pids_from_kill_args("abc 12345 def");
        assert_eq!(pids, vec![12345]);
    }

    #[test]
    fn kill_invocation_pids_extracts_from_command() {
        let pids = kill_invocation_pids("kill 12345");
        assert_eq!(pids, vec![12345]);
    }

    #[test]
    fn kill_invocation_pids_multiple() {
        let pids = kill_invocation_pids("kill -9 12345 67890");
        assert_eq!(pids, vec![12345, 67890]);
    }

    #[test]
    fn kill_invocation_pids_in_pipeline() {
        let pids = kill_invocation_pids("echo hi; kill 11111");
        assert_eq!(pids, vec![11111]);
    }

    #[test]
    fn kill_invocation_ignores_killall() {
        let pids = kill_invocation_pids("killall soothe");
        assert!(pids.is_empty());
    }

    #[test]
    fn glob_match_star_matches_any() {
        assert!(glob_match("/etc/**", "/etc/passwd"));
        assert!(glob_match("/etc/**", "/etc/hosts"));
    }

    #[test]
    fn glob_match_exact_prefix() {
        assert!(glob_match("/bin/**", "/bin/sh"));
        assert!(!glob_match("/bin/**", "/usr/bin/sh"));
    }

    #[test]
    fn glob_match_question_mark() {
        assert!(glob_match("file?.txt", "file1.txt"));
        assert!(!glob_match("file?.txt", "file12.txt"));
    }

    #[test]
    fn command_approved_exact_match() {
        let allowlist = vec![("run_command".to_string(), Some("ls -la".to_string()), None)];
        assert!(command_approved_by_allowlist("ls -la", None, &allowlist));
    }

    #[test]
    fn command_approved_not_in_allowlist() {
        let allowlist = vec![("run_command".to_string(), Some("ls -la".to_string()), None)];
        assert!(!command_approved_by_allowlist("rm -rf /", None, &allowlist));
    }

    #[test]
    fn command_approved_by_rule_family() {
        let allowlist = vec![(
            "".to_string(),
            None,
            Some("command.dangerous.rm_rf".to_string()),
        )];
        // rule_family("command.dangerous.rm_root") includes rm_rf.
        assert!(command_approved_by_allowlist(
            "rm -rf /",
            Some("command.dangerous.rm_root"),
            &allowlist
        ));
    }

    #[test]
    fn command_approved_empty_allowlist() {
        assert!(!command_approved_by_allowlist("ls", None, &[]));
    }

    #[test]
    fn fnmatch_basic_star() {
        assert!(fnmatch("*.txt", "file.txt"));
        assert!(!fnmatch("*.txt", "file.rs"));
    }

    #[test]
    fn fnmatch_exact_string() {
        assert!(fnmatch("exact", "exact"));
        assert!(!fnmatch("exact", "other"));
    }
}
