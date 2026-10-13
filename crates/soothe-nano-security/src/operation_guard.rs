//! Operation guard (ported from `security/operation_guard.py`).
//!
//! Guards each file operation against security policy + rate limits.

use crate::path_security::{PathValidator, ValidationResult};
use crate::policy_models::PolicyAction;
use crate::rate_limiter::RateLimiter;
use crate::SecurityPolicy;

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

    /// Check an operation. Returns Ok(ValidationResult) if allowed,
    /// Err(SecurityError) if denied.
    pub fn check(&self, op: &OperationRecord) -> Result<ValidationResult, crate::SecurityError> {
        // Rate limit check
        if !self.rate_limiter.try_consume(&op.operation) {
            return Err(crate::SecurityError::RateLimited);
        }

        // Policy check
        let action = self.policy.evaluate_path(&op.path);
        if action == PolicyAction::Deny {
            return Err(crate::SecurityError::PolicyDeny(format!(
                "path '{}' denied by policy",
                op.path
            )));
        }

        // Path validation
        let result = self.validator.validate(&op.path);
        if !result.is_valid {
            return Err(crate::SecurityError::PathValidation(result.message));
        }

        Ok(result)
    }
}
