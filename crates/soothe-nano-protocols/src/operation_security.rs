//! Operation security protocol data models — tool-level security checks.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// All valid operation kinds.
pub const OPERATION_KINDS: &[&str] = &[
    "filesystem_read",
    "filesystem_write",
    "shell_execute",
    "python_execute",
    "process_control",
    "generic",
];

/// True when `kind` is a valid operation kind.
pub fn is_valid_operation_kind(kind: &str) -> bool {
    OPERATION_KINDS.contains(&kind)
}

/// Normalized security request for a single operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperationSecurityRequest {
    pub action_type: String,
    #[serde(default)]
    pub tool_name: Option<String>,
    #[serde(default)]
    pub tool_args: HashMap<String, serde_json::Value>,
    #[serde(default = "default_operation_kind")]
    pub operation_kind: String,
    #[serde(default)]
    pub target_path: Option<String>,
    #[serde(default)]
    pub command: Option<String>,
}

fn default_operation_kind() -> String {
    "generic".to_string()
}

impl OperationSecurityRequest {
    pub fn new(action_type: String) -> Self {
        Self {
            action_type,
            tool_name: None,
            tool_args: HashMap::new(),
            operation_kind: default_operation_kind(),
            target_path: None,
            command: None,
        }
    }
}

/// Context for operation security evaluation.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct OperationSecurityContext {
    #[serde(default)]
    pub thread_id: Option<String>,
    #[serde(default)]
    pub workspace: Option<String>,
    #[serde(default)]
    pub security_config: Option<serde_json::Value>,
    #[serde(default)]
    pub bypass_security: bool,
}

impl OperationSecurityContext {
    pub fn new() -> Self {
        Self::default()
    }
}

/// All valid verdicts.
pub const VERDICTS: &[&str] = &["allow", "deny", "need_approval"];

/// True when `verdict` is a valid verdict.
pub fn is_valid_verdict(verdict: &str) -> bool {
    VERDICTS.contains(&verdict)
}

/// Security verdict for an operation request.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperationSecurityDecision {
    pub verdict: String,
    pub reason: String,
    #[serde(default)]
    pub rule_id: Option<String>,
}

impl OperationSecurityDecision {
    pub fn new(verdict: String, reason: String) -> Self {
        Self {
            verdict,
            reason,
            rule_id: None,
        }
    }

    /// True when the verdict is "allow".
    pub fn is_allow(&self) -> bool {
        self.verdict == "allow"
    }

    /// True when the verdict is "deny".
    pub fn is_deny(&self) -> bool {
        self.verdict == "deny"
    }

    /// True when the verdict is "need_approval".
    pub fn needs_approval(&self) -> bool {
        self.verdict == "need_approval"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_defaults() {
        let r = OperationSecurityRequest::new("tool_call".into());
        assert_eq!(r.action_type, "tool_call");
        assert_eq!(r.operation_kind, "generic");
        assert!(r.tool_args.is_empty());
    }

    #[test]
    fn decision_verdicts() {
        let d = OperationSecurityDecision::new("allow".into(), "ok".into());
        assert!(d.is_allow());
        assert!(!d.is_deny());
        let d2 = OperationSecurityDecision::new("deny".into(), "no".into());
        assert!(d2.is_deny());
        let d3 = OperationSecurityDecision::new("need_approval".into(), "?".into());
        assert!(d3.needs_approval());
    }

    #[test]
    fn valid_kinds() {
        assert!(is_valid_operation_kind("shell_execute"));
        assert!(is_valid_operation_kind("generic"));
        assert!(!is_valid_operation_kind("bogus"));
    }

    #[test]
    fn valid_verdicts() {
        assert!(is_valid_verdict("allow"));
        assert!(is_valid_verdict("deny"));
        assert!(is_valid_verdict("need_approval"));
        assert!(!is_valid_verdict("maybe"));
    }

    #[test]
    fn roundtrip_request() {
        let r = OperationSecurityRequest::new("tool_call".into());
        let s = serde_json::to_string(&r).unwrap();
        let back: OperationSecurityRequest = serde_json::from_str(&s).unwrap();
        assert_eq!(back.action_type, "tool_call");
        assert_eq!(back.operation_kind, "generic");
    }
}
