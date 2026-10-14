//! PolicyProtocol data models — permission-based access control.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// All valid permission categories.
pub const CATEGORIES: &[&str] = &["fs", "shell", "net", "mcp", "subagent"];

/// All valid actions.
pub const ACTIONS: &[&str] = &["read", "write", "execute", "connect", "spawn", "outbound"];

/// True when `category` is a valid permission category.
pub fn is_valid_category(category: &str) -> bool {
    CATEGORIES.contains(&category)
}

/// True when `action` is a valid permission action.
pub fn is_valid_action(action: &str) -> bool {
    ACTIONS.contains(&action)
}

/// A structured permission with category, action, and scope.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct Permission {
    pub category: String,
    pub action: String,
    #[serde(default = "default_scope")]
    pub scope: String,
}

fn default_scope() -> String {
    "*".to_string()
}

impl Permission {
    pub fn new(category: String, action: String) -> Self {
        Self {
            category,
            action,
            scope: default_scope(),
        }
    }

    pub fn with_scope(category: String, action: String, scope: String) -> Self {
        Self {
            category,
            action,
            scope,
        }
    }

    /// Check if this granted permission covers a requested permission.
    ///
    /// Rules:
    /// - Category and action must match exactly.
    /// - Scope "*" covers any scope.
    /// - Scope starting with "!" is a negation: covers when the requested
    ///   scope does NOT match the glob after the "!".
    /// - Otherwise, scope must match via fnmatch glob semantics.
    pub fn matches(&self, requested: &Permission) -> bool {
        if self.category != requested.category || self.action != requested.action {
            return false;
        }
        if self.scope == "*" {
            return true;
        }
        if let Some(neg_pattern) = self.scope.strip_prefix('!') {
            return !glob_match(neg_pattern, &requested.scope);
        }
        glob_match(&self.scope, &requested.scope)
    }
}

/// fnmatch-style glob matching (supports `*`, `?`, `[...]`).
pub fn glob_match(pattern: &str, text: &str) -> bool {
    #[allow(dead_code)]
    fn rec(p: &[u8], t: &[u8]) -> bool {
        match (p.first(), t.first()) {
            (None, None) => true,
            (None, Some(_)) => false,
            (Some(&b'*'), _) => {
                if rec(&p[1..], t) {
                    return true;
                }
                !t.is_empty() && rec(p, &t[1..])
            }
            (Some(&b'?'), Some(_)) => rec(&p[1..], &t[1..]),
            (Some(&pc), Some(&tc)) if pc == tc => rec(&p[1..], &t[1..]),
            _ => false,
        }
    }
    // Handle character classes: [abc], [a-z], [!abc]
    let (p_norm, t_norm) = (pattern.as_bytes(), text.as_bytes());
    match_with_classes(p_norm, t_norm)
}

/// Glob matching with `[...]` character-class support.
fn match_with_classes(p: &[u8], t: &[u8]) -> bool {
    let mut pi = 0;
    let mut ti = 0;
    // For `*` backtracking, record positions
    let mut star_p: Option<usize> = None;
    let mut star_t: usize = 0;

    while ti < t.len() {
        if pi < p.len() {
            match p[pi] {
                b'*' => {
                    star_p = Some(pi);
                    star_t = ti;
                    pi += 1;
                    continue;
                }
                b'?' => {
                    pi += 1;
                    ti += 1;
                    continue;
                }
                b'[' => {
                    if let Some((matched, next_pi)) = match_class(p, pi, t[ti]) {
                        if matched {
                            pi = next_pi;
                            ti += 1;
                            continue;
                        }
                    }
                }
                pc if pc == t[ti] => {
                    pi += 1;
                    ti += 1;
                    continue;
                }
                _ => {}
            }
        }
        // Mismatch — backtrack to last `*`
        if let Some(sp) = star_p {
            pi = sp + 1;
            star_t += 1;
            ti = star_t;
            continue;
        }
        return false;
    }
    // Consume trailing `*` in pattern
    while pi < p.len() && p[pi] == b'*' {
        pi += 1;
    }
    pi == p.len()
}

/// Match a `[...]` character class at `p[start]`. Returns `(matched, index_after_class)`.
fn match_class(p: &[u8], start: usize, ch: u8) -> Option<(bool, usize)> {
    // Find closing `]`
    let mut end = start + 1;
    let negate = end < p.len() && p[end] == b'!';
    if negate {
        end += 1;
    }
    let class_start = end;
    while end < p.len() && p[end] != b']' {
        end += 1;
    }
    if end >= p.len() {
        // No closing bracket — treat `[` as literal
        return None;
    }
    let class = &p[class_start..end];
    let mut matched = false;
    let mut i = 0;
    while i < class.len() {
        if i + 2 < class.len() && class[i + 1] == b'-' {
            let lo = class[i];
            let hi = class[i + 2];
            if ch >= lo && ch <= hi {
                matched = true;
            }
            i += 3;
        } else {
            if class[i] == ch {
                matched = true;
            }
            i += 1;
        }
    }
    let result = if negate { !matched } else { matched };
    Some((result, end + 1))
}

/// Describes an action requiring permission.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActionRequest {
    pub action_type: String,
    #[serde(default)]
    pub tool_name: Option<String>,
    #[serde(default)]
    pub tool_args: HashMap<String, serde_json::Value>,
}

impl ActionRequest {
    pub fn new(action_type: String) -> Self {
        Self {
            action_type,
            tool_name: None,
            tool_args: HashMap::new(),
        }
    }
}

/// Context for policy evaluation.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PolicyContext {
    #[serde(default)]
    pub active_permissions: Option<serde_json::Value>,
    #[serde(default)]
    pub scope_id: Option<String>,
    #[serde(default)]
    pub workspace: Option<String>,
}

impl PolicyContext {
    pub fn new() -> Self {
        Self::default()
    }
}

/// All valid verdicts.
pub const POLICY_VERDICTS: &[&str] = &["allow", "deny", "need_approval"];

/// True when `verdict` is a valid policy verdict.
pub fn is_valid_policy_verdict(verdict: &str) -> bool {
    POLICY_VERDICTS.contains(&verdict)
}

/// Result of a policy check.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyDecision {
    pub verdict: String,
    pub reason: String,
    #[serde(default)]
    pub matched_permission: Option<serde_json::Value>,
}

impl PolicyDecision {
    pub fn new(verdict: String, reason: String) -> Self {
        Self {
            verdict,
            reason,
            matched_permission: None,
        }
    }

    pub fn is_allow(&self) -> bool {
        self.verdict == "allow"
    }

    pub fn is_deny(&self) -> bool {
        self.verdict == "deny"
    }

    pub fn needs_approval(&self) -> bool {
        self.verdict == "need_approval"
    }
}

/// A named policy configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyProfile {
    pub name: String,
    #[serde(default)]
    pub permissions: Option<serde_json::Value>,
    #[serde(default)]
    pub approvable: Option<serde_json::Value>,
    #[serde(default)]
    pub deny_rules: Vec<serde_json::Value>,
}

impl PolicyProfile {
    pub fn new(name: String) -> Self {
        Self {
            name,
            permissions: None,
            approvable: None,
            deny_rules: Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn permission_matches_exact() {
        let p = Permission::with_scope("fs".into(), "read".into(), "/path/to/file".into());
        assert!(p.matches(&Permission::with_scope(
            "fs".into(),
            "read".into(),
            "/path/to/file".into()
        )));
        assert!(!p.matches(&Permission::with_scope(
            "fs".into(),
            "read".into(),
            "/other/file".into()
        )));
    }

    #[test]
    fn permission_matches_wildcard() {
        let p = Permission::with_scope("fs".into(), "read".into(), "*".into());
        assert!(p.matches(&Permission::with_scope(
            "fs".into(),
            "read".into(),
            "/any/path".into()
        )));
    }

    #[test]
    fn permission_matches_glob() {
        let p = Permission::with_scope("fs".into(), "write".into(), "/tmp/**".into());
        assert!(p.matches(&Permission::with_scope(
            "fs".into(),
            "write".into(),
            "/tmp/foo".into()
        )));
        assert!(p.matches(&Permission::with_scope(
            "fs".into(),
            "write".into(),
            "/tmp/foo/bar".into()
        )));
        assert!(!p.matches(&Permission::with_scope(
            "fs".into(),
            "write".into(),
            "/etc/passwd".into()
        )));
    }

    #[test]
    fn permission_matches_negation() {
        let p = Permission::with_scope("shell".into(), "execute".into(), "!rm".into());
        assert!(p.matches(&Permission::with_scope(
            "shell".into(),
            "execute".into(),
            "ls".into()
        )));
        assert!(!p.matches(&Permission::with_scope(
            "shell".into(),
            "execute".into(),
            "rm".into()
        )));
    }

    #[test]
    fn permission_requires_same_category_action() {
        let p = Permission::with_scope("fs".into(), "read".into(), "*".into());
        assert!(!p.matches(&Permission::with_scope(
            "fs".into(),
            "write".into(),
            "*".into()
        )));
        assert!(!p.matches(&Permission::with_scope(
            "shell".into(),
            "read".into(),
            "*".into()
        )));
    }

    #[test]
    fn glob_simple() {
        assert!(glob_match("*.txt", "hello.txt"));
        assert!(!glob_match("*.txt", "hello.csv"));
        assert!(glob_match("hello", "hello"));
        assert!(glob_match("h?llo", "hello"));
        assert!(!glob_match("h?llo", "hello!"));
        assert!(glob_match("*", "anything"));
        assert!(glob_match("/tmp/**", "/tmp/a/b/c"));
        assert!(!glob_match("/tmp/**", "/etc/passwd"));
    }

    #[test]
    fn glob_classes() {
        assert!(glob_match("[abc].txt", "a.txt"));
        assert!(glob_match("[abc].txt", "b.txt"));
        assert!(!glob_match("[abc].txt", "d.txt"));
        assert!(glob_match("[!abc].txt", "d.txt"));
        assert!(!glob_match("[!abc].txt", "a.txt"));
        assert!(glob_match("file[0-9]", "file5"));
        assert!(!glob_match("file[0-9]", "fileX"));
    }

    #[test]
    fn decision_verdicts() {
        let d = PolicyDecision::new("allow".into(), "ok".into());
        assert!(d.is_allow());
        assert!(!d.is_deny());
    }

    #[test]
    fn valid_categories() {
        assert!(is_valid_category("fs"));
        assert!(is_valid_category("mcp"));
        assert!(!is_valid_category("bogus"));
    }

    #[test]
    fn valid_actions() {
        assert!(is_valid_action("read"));
        assert!(is_valid_action("outbound"));
        assert!(!is_valid_action("bogus"));
    }

    #[test]
    fn roundtrip_permission() {
        let p = Permission::with_scope("fs".into(), "read".into(), "/tmp/**".into());
        let s = serde_json::to_string(&p).unwrap();
        let back: Permission = serde_json::from_str(&s).unwrap();
        assert_eq!(back.category, "fs");
        assert_eq!(back.scope, "/tmp/**");
    }
}
