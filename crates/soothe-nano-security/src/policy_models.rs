//! Policy models.

use std::collections::HashMap;
use std::str::FromStr;

use chrono::Utc;
use serde::{Deserialize, Serialize};

/// Action taken by the policy engine for an operation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
pub enum PolicyAction {
    #[default]
    Allow,
    Deny,
    Log,
    Notify,
    Sanitize,
}

impl PolicyAction {
    /// String label (lowercase).
    pub fn as_str(self) -> &'static str {
        match self {
            PolicyAction::Allow => "allow",
            PolicyAction::Deny => "deny",
            PolicyAction::Log => "log",
            PolicyAction::Notify => "notify",
            PolicyAction::Sanitize => "sanitize",
        }
    }
}

/// Parse error for `PolicyAction::from_str`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsePolicyActionError;

impl std::fmt::Display for ParsePolicyActionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "invalid PolicyAction label")
    }
}

impl std::error::Error for ParsePolicyActionError {}

impl FromStr for PolicyAction {
    type Err = ParsePolicyActionError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_lowercase().as_str() {
            "allow" => Ok(PolicyAction::Allow),
            "deny" => Ok(PolicyAction::Deny),
            "log" => Ok(PolicyAction::Log),
            "notify" => Ok(PolicyAction::Notify),
            "sanitize" => Ok(PolicyAction::Sanitize),
            _ => Err(ParsePolicyActionError),
        }
    }
}

/// True if `path` equals `prefix` (after rstrip '/') or sits beneath it.
pub fn path_is_under(path: &str, prefix: &str) -> bool {
    if path.is_empty() || prefix.is_empty() {
        return false;
    }
    let prefix_norm = prefix.trim_end_matches('/');
    let prefix_norm = if prefix_norm.is_empty() {
        "/"
    } else {
        prefix_norm
    };
    if path == prefix_norm {
        return true;
    }
    path.starts_with(&format!("{}/", prefix_norm))
}

/// A single policy rule.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyRule {
    pub name: String,
    pub action: PolicyAction,
    #[serde(default)]
    pub pattern: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
}

/// A policy violation record.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyViolation {
    pub policy_name: String,
    pub violation_type: String,
    pub message: String,
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default)]
    pub operation: Option<String>,
    #[serde(default = "default_severity")]
    pub severity: String,
    #[serde(default)]
    pub details: HashMap<String, serde_json::Value>,
    #[serde(default = "default_timestamp")]
    pub timestamp: String,
}

fn default_severity() -> String {
    "medium".to_string()
}

fn default_timestamp() -> String {
    Utc::now().to_rfc3339()
}

impl PolicyViolation {
    /// Build a new violation with defaults applied for optional fields.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        policy_name: impl Into<String>,
        violation_type: impl Into<String>,
        message: impl Into<String>,
        path: Option<String>,
        operation: Option<String>,
        severity: Option<String>,
        details: HashMap<String, serde_json::Value>,
    ) -> Self {
        Self {
            policy_name: policy_name.into(),
            violation_type: violation_type.into(),
            message: message.into(),
            path,
            operation,
            severity: severity.unwrap_or_else(default_severity),
            details,
            timestamp: default_timestamp(),
        }
    }

    /// Convert to a `HashMap<String, serde_json::Value>` mirroring `to_dict()`.
    pub fn to_dict(&self) -> HashMap<String, serde_json::Value> {
        let mut map = HashMap::new();
        map.insert(
            "policy_name".into(),
            serde_json::Value::String(self.policy_name.clone()),
        );
        map.insert(
            "violation_type".into(),
            serde_json::Value::String(self.violation_type.clone()),
        );
        map.insert(
            "message".into(),
            serde_json::Value::String(self.message.clone()),
        );
        map.insert(
            "path".into(),
            self.path
                .clone()
                .map(serde_json::Value::String)
                .unwrap_or(serde_json::Value::Null),
        );
        map.insert(
            "operation".into(),
            self.operation
                .clone()
                .map(serde_json::Value::String)
                .unwrap_or(serde_json::Value::Null),
        );
        map.insert(
            "severity".into(),
            serde_json::Value::String(self.severity.clone()),
        );
        map.insert(
            "details".into(),
            serde_json::to_value(&self.details)
                .unwrap_or(serde_json::Value::Object(Default::default())),
        );
        map.insert(
            "timestamp".into(),
            serde_json::Value::String(self.timestamp.clone()),
        );
        map
    }
}

/// Decision made by policy evaluation.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PathPolicyDecision {
    pub allowed: bool,
    pub action: PolicyAction,
    #[serde(default)]
    pub reason: Option<String>,
    #[serde(default)]
    pub violations: Vec<PolicyViolation>,
    #[serde(default)]
    pub sanitized_path: Option<String>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

impl PathPolicyDecision {
    /// Check if decision denies the operation.
    pub fn is_denied(&self) -> bool {
        !self.allowed || self.action == PolicyAction::Deny
    }

    /// Check if this decision should be logged.
    pub fn should_log(&self) -> bool {
        matches!(
            self.action,
            PolicyAction::Log | PolicyAction::Deny | PolicyAction::Notify
        )
    }

    /// Merge another decision into this one (most restrictive wins).
    ///
    /// If `other` is denied, return `other` (enriched with merged violations,
    /// sanitized_path, metadata). Otherwise keep `self` and merge fields.
    pub fn merge(&self, other: &PathPolicyDecision) -> PathPolicyDecision {
        let violations: Vec<PolicyViolation> = self
            .violations
            .iter()
            .cloned()
            .chain(other.violations.iter().cloned())
            .collect();
        let sanitized_path = self
            .sanitized_path
            .clone()
            .or_else(|| other.sanitized_path.clone());
        let mut metadata = self.metadata.clone();
        for (k, v) in &other.metadata {
            metadata.insert(k.clone(), v.clone());
        }
        let reason = self.reason.clone().or_else(|| other.reason.clone());

        if other.is_denied() {
            PathPolicyDecision {
                allowed: false,
                action: PolicyAction::Deny,
                reason,
                violations,
                sanitized_path,
                metadata,
            }
        } else {
            let action = if self.action != PolicyAction::Allow {
                self.action
            } else {
                other.action
            };
            PathPolicyDecision {
                allowed: self.allowed,
                action,
                reason,
                violations,
                sanitized_path,
                metadata,
            }
        }
    }
}

/// Security policy — collection of rules.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SecurityPolicy {
    #[serde(default)]
    pub rules: Vec<PolicyRule>,
    #[serde(default)]
    pub default_action: PolicyAction,
}

impl SecurityPolicy {
    /// Evaluate a path against all rules, returning the first matching action.
    pub fn evaluate_path(&self, path: &str) -> PolicyAction {
        for rule in &self.rules {
            if let Some(pattern) = &rule.pattern {
                if let Ok(re) = regex::Regex::new(pattern) {
                    if re.is_match(path) {
                        return rule.action;
                    }
                }
            }
        }
        self.default_action
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── path_is_under ────────────────────────────────────────────

    #[test]
    fn path_is_under_exact_match() {
        assert!(path_is_under("/etc", "/etc"));
        assert!(path_is_under("/workspace", "/workspace"));
    }

    #[test]
    fn path_is_under_child() {
        assert!(path_is_under("/etc/passwd", "/etc"));
        assert!(path_is_under("/workspace/src/main.rs", "/workspace"));
    }

    #[test]
    fn path_is_under_trailing_slash_prefix() {
        assert!(path_is_under("/etc/passwd", "/etc/"));
        assert!(path_is_under("/etc", "/etc/"));
    }

    #[test]
    fn path_is_under_root_prefix() {
        // "/" only matches itself, not children, because the child check
        // becomes startswith("//").
        assert!(path_is_under("/", "/"));
        assert!(!path_is_under("/anything", "/"));
    }

    #[test]
    fn path_is_under_sibling_not_match() {
        assert!(!path_is_under("/etc2", "/etc"));
        assert!(!path_is_under("/etcfoo", "/etc"));
    }

    #[test]
    fn path_is_under_empty_inputs() {
        assert!(!path_is_under("", "/etc"));
        assert!(!path_is_under("/etc", ""));
        assert!(!path_is_under("", ""));
    }

    // ── PolicyAction ────────────────────────────────────────────

    #[test]
    fn policy_action_round_trip() {
        for a in [
            PolicyAction::Allow,
            PolicyAction::Deny,
            PolicyAction::Log,
            PolicyAction::Notify,
            PolicyAction::Sanitize,
        ] {
            assert_eq!(PolicyAction::from_str(a.as_str()).ok(), Some(a));
        }
        assert!(PolicyAction::from_str("bogus").is_err());
    }

    // ── PolicyViolation ──────────────────────────────────────────

    #[test]
    fn policy_violation_to_dict_has_all_fields() {
        let mut details = HashMap::new();
        details.insert("pattern".into(), serde_json::Value::String("*.key".into()));
        let v = PolicyViolation::new(
            "test_policy",
            "blocked_pattern",
            "Path matches blocked pattern",
            Some("/secret.key".into()),
            Some("read".into()),
            Some("high".into()),
            details,
        );
        let d = v.to_dict();
        assert_eq!(
            d["policy_name"],
            serde_json::Value::String("test_policy".into())
        );
        assert_eq!(
            d["violation_type"],
            serde_json::Value::String("blocked_pattern".into())
        );
        assert_eq!(d["path"], serde_json::Value::String("/secret.key".into()));
        assert_eq!(d["operation"], serde_json::Value::String("read".into()));
        assert_eq!(d["severity"], serde_json::Value::String("high".into()));
        assert!(d["timestamp"].is_string());
        assert!(d.get("details").unwrap().is_object());
    }

    #[test]
    fn policy_violation_defaults() {
        let v = PolicyViolation::new("p", "t", "m", None, None, None, HashMap::new());
        assert_eq!(v.severity, "medium");
        assert!(v.path.is_none());
        assert!(!v.timestamp.is_empty());
    }

    // ── PathPolicyDecision ───────────────────────────────────────

    #[test]
    fn is_denied_when_not_allowed() {
        let d = PathPolicyDecision {
            allowed: false,
            action: PolicyAction::Log,
            ..Default::default()
        };
        assert!(d.is_denied());
    }

    #[test]
    fn is_denied_when_action_deny() {
        let d = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Deny,
            ..Default::default()
        };
        assert!(d.is_denied());
    }

    #[test]
    fn is_not_denied_when_allowed() {
        let d = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            ..Default::default()
        };
        assert!(!d.is_denied());
    }

    #[test]
    fn should_log_for_log_deny_notify() {
        assert!(PathPolicyDecision {
            action: PolicyAction::Log,
            ..Default::default()
        }
        .should_log());
        assert!(PathPolicyDecision {
            action: PolicyAction::Deny,
            ..Default::default()
        }
        .should_log());
        assert!(PathPolicyDecision {
            action: PolicyAction::Notify,
            ..Default::default()
        }
        .should_log());
    }

    #[test]
    fn should_not_log_for_allow_sanitize() {
        assert!(!PathPolicyDecision {
            action: PolicyAction::Allow,
            ..Default::default()
        }
        .should_log());
        assert!(!PathPolicyDecision {
            action: PolicyAction::Sanitize,
            ..Default::default()
        }
        .should_log());
    }

    // ── merge ────────────────────────────────────────────────────

    #[test]
    fn merge_other_denied_returns_other() {
        let allowed = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            ..Default::default()
        };
        let denied = PathPolicyDecision {
            allowed: false,
            action: PolicyAction::Deny,
            reason: Some("blocked".into()),
            ..Default::default()
        };
        let merged = allowed.merge(&denied);
        assert!(merged.is_denied());
        assert_eq!(merged.reason, Some("blocked".into()));
    }

    #[test]
    fn merge_both_allowed_keeps_self_action() {
        let self_d = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Log,
            reason: Some("self".into()),
            ..Default::default()
        };
        let other = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            ..Default::default()
        };
        let merged = self_d.merge(&other);
        assert!(!merged.is_denied());
        assert_eq!(merged.action, PolicyAction::Log);
        assert_eq!(merged.reason, Some("self".into()));
    }

    #[test]
    fn merge_self_allow_takes_other_action() {
        let self_d = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            ..Default::default()
        };
        let other = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Notify,
            ..Default::default()
        };
        let merged = self_d.merge(&other);
        assert_eq!(merged.action, PolicyAction::Notify);
    }

    #[test]
    fn merge_combines_violations() {
        let v1 = PolicyViolation::new("p1", "t1", "m1", None, None, None, HashMap::new());
        let v2 = PolicyViolation::new("p2", "t2", "m2", None, None, None, HashMap::new());
        let d1 = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            violations: vec![v1],
            ..Default::default()
        };
        let d2 = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            violations: vec![v2],
            ..Default::default()
        };
        let merged = d1.merge(&d2);
        assert_eq!(merged.violations.len(), 2);
    }

    #[test]
    fn merge_combines_metadata_and_sanitized_path() {
        let mut m1 = HashMap::new();
        m1.insert("a".into(), serde_json::Value::String("1".into()));
        let mut m2 = HashMap::new();
        m2.insert("b".into(), serde_json::Value::String("2".into()));
        let d1 = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            sanitized_path: Some("/safe".into()),
            metadata: m1,
            ..Default::default()
        };
        let d2 = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            metadata: m2,
            ..Default::default()
        };
        let merged = d1.merge(&d2);
        assert_eq!(merged.sanitized_path, Some("/safe".into()));
        assert_eq!(merged.metadata.len(), 2);
    }

    #[test]
    fn merge_denied_takes_other_sanitized_path_when_self_none() {
        let self_d = PathPolicyDecision {
            allowed: true,
            action: PolicyAction::Allow,
            ..Default::default()
        };
        let other = PathPolicyDecision {
            allowed: false,
            action: PolicyAction::Deny,
            sanitized_path: Some("/sanitized".into()),
            ..Default::default()
        };
        let merged = self_d.merge(&other);
        assert!(merged.is_denied());
        assert_eq!(merged.sanitized_path, Some("/sanitized".into()));
    }

    // ── SecurityPolicy::evaluate_path ───────────────────────────

    #[test]
    fn security_policy_evaluate_path_matches_rule() {
        let policy = SecurityPolicy {
            rules: vec![PolicyRule {
                name: "deny-etc".into(),
                action: PolicyAction::Deny,
                pattern: Some(r"^/etc/".into()),
                description: None,
            }],
            default_action: PolicyAction::Allow,
        };
        assert_eq!(policy.evaluate_path("/etc/passwd"), PolicyAction::Deny);
        assert_eq!(policy.evaluate_path("/home/user"), PolicyAction::Allow);
    }

    #[test]
    fn security_policy_evaluate_path_default_when_no_match() {
        let policy = SecurityPolicy {
            rules: vec![],
            default_action: PolicyAction::Log,
        };
        assert_eq!(policy.evaluate_path("/anything"), PolicyAction::Log);
    }
}
