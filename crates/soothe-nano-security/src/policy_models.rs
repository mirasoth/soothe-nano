//! Policy models (ported from `security/policy_models.py`).

use serde::{Deserialize, Serialize};

/// Action taken by the policy engine for an operation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum PolicyAction {
    #[default]
    Allow,
    Deny,
    Log,
    Notify,
    Sanitize,
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
                        return rule.action.clone();
                    }
                }
            }
        }
        self.default_action.clone()
    }
}
