//! Event type classification and domain verbosity resolution.

use crate::verbosity::VerbosityTier;

/// Return the default verbosity tier for a top-level domain.
pub fn domain_default_tier(domain: &str) -> VerbosityTier {
    match domain {
        "internal" => VerbosityTier::Internal,
        "lifecycle" => VerbosityTier::Internal,
        "protocol" => VerbosityTier::Internal,
        "cognition" => VerbosityTier::Normal,
        "loop" => VerbosityTier::Normal,
        "tool" => VerbosityTier::Internal,
        "subagent" => VerbosityTier::Internal,
        "output" => VerbosityTier::Normal,
        "error" => VerbosityTier::Normal,
        "agentic" => VerbosityTier::Normal,
        _ => VerbosityTier::Internal,
    }
}

/// Extract the domain segment from an event type string.
///
/// For `internal` domains, returns `"internal"` regardless of further segments.
/// Strings with fewer than two segments return `"unknown"`.
pub fn classify(event_type: &str) -> String {
    let segments: Vec<&str> = event_type.split('.').collect();
    const MIN_SEGMENTS: usize = 2;
    if segments.len() >= MIN_SEGMENTS && segments[1] == "internal" {
        return "internal".to_string();
    }
    if segments.len() >= MIN_SEGMENTS {
        segments[1].to_string()
    } else {
        "unknown".to_string()
    }
}

/// Resolve the verbosity tier for an event type using the domain default.
pub fn get_verbosity(event_type: &str) -> VerbosityTier {
    let domain = classify(event_type);
    domain_default_tier(&domain)
}

/// Split a type string into `(domain, component, action, default_tier)`.
///
/// For the `internal` domain, component/action are extracted from segments 2/3+.
/// For other domains, component is segment 2 and action is segment 3.
pub fn split_domain(type_string: &str) -> (String, String, String, VerbosityTier) {
    let parts: Vec<&str> = type_string.split('.').collect();

    if parts.len() >= 2 && parts[1] == "internal" {
        let domain = "internal".to_string();
        let component = if parts.len() >= 3 {
            parts[2].to_string()
        } else {
            String::new()
        };
        let action = if parts.len() >= 4 {
            parts[3..].join(".")
        } else {
            String::new()
        };
        let default_tier = VerbosityTier::Internal;
        (domain, component, action, default_tier)
    } else {
        let domain = if parts.len() >= 2 {
            parts[1].to_string()
        } else {
            "unknown".to_string()
        };
        let component = if parts.len() >= 3 {
            parts[2].to_string()
        } else {
            String::new()
        };
        let action = if parts.len() >= 4 {
            parts[3].to_string()
        } else {
            String::new()
        };
        let default_tier = domain_default_tier(&domain);
        (domain, component, action, default_tier)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── classify ──────────────────────────────────────────────────

    #[test]
    fn classify_cognition() {
        assert_eq!(classify("soothe.cognition.plan.created"), "cognition");
    }

    #[test]
    fn classify_internal() {
        assert_eq!(classify("soothe.internal.memory.recalled"), "internal");
    }

    #[test]
    fn classify_loop() {
        assert_eq!(classify("soothe.loop.clarification.requested"), "loop");
    }

    #[test]
    fn classify_short_string() {
        assert_eq!(classify("soothe"), "unknown");
        assert_eq!(classify(""), "unknown");
    }

    #[test]
    fn classify_error() {
        assert_eq!(classify("soothe.error.general.failed"), "error");
    }

    // ── domain_default_tier ───────────────────────────────────────

    #[test]
    fn internal_domain_is_internal() {
        assert_eq!(domain_default_tier("internal"), VerbosityTier::Internal);
        assert_eq!(domain_default_tier("lifecycle"), VerbosityTier::Internal);
        assert_eq!(domain_default_tier("protocol"), VerbosityTier::Internal);
        assert_eq!(domain_default_tier("tool"), VerbosityTier::Internal);
        assert_eq!(domain_default_tier("subagent"), VerbosityTier::Internal);
    }

    #[test]
    fn visible_domains_are_normal() {
        assert_eq!(domain_default_tier("cognition"), VerbosityTier::Normal);
        assert_eq!(domain_default_tier("loop"), VerbosityTier::Normal);
        assert_eq!(domain_default_tier("output"), VerbosityTier::Normal);
        assert_eq!(domain_default_tier("error"), VerbosityTier::Normal);
        assert_eq!(domain_default_tier("agentic"), VerbosityTier::Normal);
    }

    #[test]
    fn unknown_domain_defaults_internal() {
        assert_eq!(domain_default_tier("bogus"), VerbosityTier::Internal);
    }

    // ── get_verbosity ─────────────────────────────────────────────

    #[test]
    fn get_verbosity_for_cognition() {
        assert_eq!(
            get_verbosity("soothe.cognition.plan.created"),
            VerbosityTier::Normal
        );
    }

    #[test]
    fn get_verbosity_for_internal() {
        assert_eq!(
            get_verbosity("soothe.internal.memory.recalled"),
            VerbosityTier::Internal
        );
    }

    // ── split_domain ──────────────────────────────────────────────

    #[test]
    fn split_domain_internal() {
        let (domain, component, action, tier) = split_domain("soothe.internal.memory.recalled");
        assert_eq!(domain, "internal");
        assert_eq!(component, "memory");
        assert_eq!(action, "recalled");
        assert_eq!(tier, VerbosityTier::Internal);
    }

    #[test]
    fn split_domain_internal_multi_action() {
        let (domain, component, action, tier) = split_domain("soothe.internal.policy.checked.deep");
        assert_eq!(domain, "internal");
        assert_eq!(component, "policy");
        assert_eq!(action, "checked.deep");
        assert_eq!(tier, VerbosityTier::Internal);
    }

    #[test]
    fn split_domain_cognition() {
        let (domain, component, action, tier) = split_domain("soothe.cognition.plan.created");
        assert_eq!(domain, "cognition");
        assert_eq!(component, "plan");
        assert_eq!(action, "created");
        assert_eq!(tier, VerbosityTier::Normal);
    }

    #[test]
    fn split_domain_short() {
        let (domain, component, action, tier) = split_domain("soothe");
        assert_eq!(domain, "unknown");
        assert_eq!(component, "");
        assert_eq!(action, "");
        assert_eq!(tier, VerbosityTier::Internal);
    }

    #[test]
    fn split_domain_two_segments() {
        let (domain, component, action, tier) = split_domain("soothe.cognition");
        assert_eq!(domain, "cognition");
        assert_eq!(component, "");
        assert_eq!(action, "");
        assert_eq!(tier, VerbosityTier::Normal);
    }

    #[test]
    fn split_domain_empty() {
        let (domain, component, action, tier) = split_domain("");
        assert_eq!(domain, "unknown");
        assert_eq!(component, "");
        assert_eq!(action, "");
        assert_eq!(tier, VerbosityTier::Internal);
    }
}
