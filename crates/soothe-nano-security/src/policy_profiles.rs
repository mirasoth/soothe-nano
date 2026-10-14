//! Policy profiles.

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

/// Strict policy: maximum security, blocks all dangerous operations.
pub fn strict_policy() -> SecurityPolicy {
    SecurityPolicy {
        rules: vec![
            PolicyRule {
                name: "deny-system-paths".into(),
                action: PolicyAction::Deny,
                pattern: Some(r"^/(etc|bin|sbin|usr|lib|lib64|dev|proc|sys|root|boot)(/|$)".into()),
                description: Some("Block access to system directories".into()),
            },
            path_rule("deny-dotdot", r"\.\./", "Block path traversal"),
            path_rule("deny-dotdot-end", r"\.\.$", "Block trailing dot-dot"),
            path_rule("deny-home-escape", r"^~/", "Block home directory escapes"),
            path_rule(
                "deny-sensitive-extensions",
                r"\.(exe|dll|so|dylib|bin|sh|bat|cmd|ps1|pyz|egg|whl)$",
                "Block sensitive file extensions",
            ),
            path_rule(
                "deny-sensitive-patterns",
                r"(\.key|\.pem|\.p12|\.pfx|\.env|\.secret|\.credentials|\.git/|\.svn/|\.hg/)",
                "Block sensitive file patterns",
            ),
        ],
        default_action: PolicyAction::Deny,
    }
}

/// Permissive policy: trusted environments, allows absolute paths.
pub fn permissive_policy() -> SecurityPolicy {
    SecurityPolicy {
        rules: vec![path_rule(
            "deny-dotdot",
            r"\.\./",
            "Block path traversal even in permissive mode",
        )],
        default_action: PolicyAction::Allow,
    }
}

/// Read-only policy: read operations only.
pub fn readonly_policy() -> SecurityPolicy {
    SecurityPolicy {
        rules: vec![
            path_rule("deny-dotdot", r"\.\./", "Block path traversal"),
            path_rule(
                "deny-system-paths",
                r"^/(etc|bin|sbin|usr|lib|dev|proc|sys)",
                "Block system paths",
            ),
        ],
        default_action: PolicyAction::Allow,
    }
}

/// Sandbox policy: strict sandbox for untrusted code.
pub fn sandbox_policy() -> SecurityPolicy {
    SecurityPolicy {
        rules: vec![
            path_rule("deny-dotdot", r"\.\.", "Block any dot-dot in sandbox"),
            path_rule("deny-absolute", r"^/", "Block absolute paths in sandbox"),
            path_rule("deny-home", r"^~", "Block home expansion in sandbox"),
            path_rule(
                "deny-executables",
                r"\.(exe|dll|so|dylib|sh|bat|cmd|ps1|vbs|py|pyw|pyc|pyo|rb|pl|php|jsp|jar|war|ear)$",
                "Block executable/script extensions in sandbox",
            ),
            path_rule("deny-hidden", r"/\.", "Block hidden files in sandbox"),
        ],
        default_action: PolicyAction::Deny,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_policy_denies_system_paths() {
        let p = default_policy();
        assert_eq!(p.evaluate_path("/etc/passwd"), PolicyAction::Deny);
    }

    #[test]
    fn default_policy_allows_normal_paths() {
        let p = default_policy();
        assert_eq!(p.evaluate_path("src/main.rs"), PolicyAction::Allow);
    }

    #[test]
    fn strict_policy_denies_traversal() {
        let p = strict_policy();
        assert_eq!(p.evaluate_path("../etc/passwd"), PolicyAction::Deny);
    }

    #[test]
    fn strict_policy_denies_system_paths() {
        let p = strict_policy();
        assert_eq!(p.evaluate_path("/etc/passwd"), PolicyAction::Deny);
        assert_eq!(p.evaluate_path("/bin/sh"), PolicyAction::Deny);
    }

    #[test]
    fn strict_policy_denies_sensitive_extensions() {
        let p = strict_policy();
        assert_eq!(p.evaluate_path("malware.exe"), PolicyAction::Deny);
    }

    #[test]
    fn permissive_policy_denies_traversal() {
        let p = permissive_policy();
        assert_eq!(p.evaluate_path("../escape"), PolicyAction::Deny);
    }

    #[test]
    fn permissive_policy_allows_normal() {
        let p = permissive_policy();
        assert_eq!(p.evaluate_path("src/main.rs"), PolicyAction::Allow);
    }

    #[test]
    fn readonly_policy_denies_system_paths() {
        let p = readonly_policy();
        assert_eq!(p.evaluate_path("/etc/passwd"), PolicyAction::Deny);
    }

    #[test]
    fn sandbox_policy_denies_dotdot() {
        let p = sandbox_policy();
        assert_eq!(p.evaluate_path("foo/../bar"), PolicyAction::Deny);
    }

    #[test]
    fn sandbox_policy_denies_absolute() {
        let p = sandbox_policy();
        assert_eq!(p.evaluate_path("/etc/passwd"), PolicyAction::Deny);
    }

    #[test]
    fn sandbox_policy_denies_executables() {
        let p = sandbox_policy();
        assert_eq!(p.evaluate_path("script.sh"), PolicyAction::Deny);
    }

    #[test]
    fn sandbox_policy_default_deny() {
        let p = sandbox_policy();
        // A path that doesn't match any rule falls through to default_action.
        assert_eq!(p.default_action, PolicyAction::Deny);
    }
}
