//! Policy profiles (ported from `security/policy_profiles.py`).

use crate::policy_models::{PolicyAction, PolicyRule, SecurityPolicy};

/// Default security policy: deny known dangerous patterns, allow everything else.
pub fn default_policy() -> SecurityPolicy {
    SecurityPolicy {
        rules: vec![
            PolicyRule {
                name: "deny-system-paths".into(),
                action: PolicyAction::Deny,
                pattern: Some(r"^/(etc|proc|sys|dev)/".into()),
                description: Some("Block access to system directories".into()),
            },
            path_rule("deny-dotdot", r"\.\./", "Block path traversal"),
            path_rule("deny-home-escape", r"^~/", "Block home directory escapes"),
        ],
        default_action: PolicyAction::Allow,
    }
}

fn path_rule(name: &str, pattern: &str, desc: &str) -> PolicyRule {
    PolicyRule {
        name: name.into(),
        action: PolicyAction::Deny,
        pattern: Some(pattern.into()),
        description: Some(desc.into()),
    }
}
