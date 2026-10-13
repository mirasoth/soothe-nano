//! Path validation, policy evaluation, rate limiting, operation guards.
//!
//! Ports: `security/path_security.py`, `security/policy_models.py`,
//! `security/policy_profiles.py`, `security/security_enforcer.py`,
//! `security/operation_guard.py`.

pub mod operation_guard;
pub mod path_security;
pub mod policy_models;
pub mod policy_profiles;
pub mod rate_limiter;

pub use operation_guard::{OperationGuard, OperationRecord};
pub use path_security::{PathValidator, ValidationResult, ViolationType};
pub use policy_models::{PolicyAction, PolicyRule, SecurityPolicy};
pub use policy_profiles::default_policy;
pub use rate_limiter::RateLimiter;

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
