//! Path validation, policy evaluation, rate limiting, operation guards.

pub mod command_guard;
pub mod operation_guard;
pub mod path_security;
pub mod policy_models;
pub mod policy_profiles;
pub mod rate_limiter;

pub use command_guard::{dangerous_command_rule_id, rule_family};
pub use operation_guard::{
    command_approved_by_allowlist, find_dangerous_path_component, glob_match, kill_invocation_pids,
    matches_sensitive_system_path, pids_from_kill_args, OperationGuard, OperationRecord,
};
pub use path_security::{PathValidator, ValidationResult, ValidationSeverity, ViolationType};
pub use policy_models::{
    path_is_under, PathPolicyDecision, PolicyAction, PolicyRule, PolicyViolation, SecurityPolicy,
};
pub use policy_profiles::{
    default_policy, permissive_policy, readonly_policy, sandbox_policy, strict_policy,
};
pub use rate_limiter::{RateLimiter, SlidingWindowRateLimiter};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum SecurityError {
    #[error("path validation failed: {0}")]
    PathValidation(String),
    #[error("operation denied by policy: {0}")]
    PolicyDeny(String),
    #[error("rate limit exceeded")]
    RateLimited,
}
