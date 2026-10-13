//! Path validation (ported from `security/path_security.py`).
//!
//! Compiled regex at startup (no per-call compile), zero-cost enum dispatch.

use regex::Regex;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

static DANGEROUS_PATTERNS: OnceLock<Vec<Regex>> = OnceLock::new();

fn dangerous_patterns() -> &'static Vec<Regex> {
    DANGEROUS_PATTERNS.get_or_init(|| {
        vec![
            Regex::new(r"\.\./").unwrap(),
            Regex::new(r"^/").unwrap(),
            Regex::new(r"\.\.$").unwrap(),
            Regex::new(r"^~").unwrap(),
        ]
    })
}

/// Severity of a validation violation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ViolationType {
    None,
    PathEscape,
    AbsolutePath,
    NullByte,
    SymlinkEscape,
    TooLarge,
}

/// Result of path validation.
#[derive(Debug, Clone)]
pub struct ValidationResult {
    pub is_valid: bool,
    pub normalized_path: Option<PathBuf>,
    pub violation: ViolationType,
    pub message: String,
}

impl ValidationResult {
    pub fn valid(path: PathBuf) -> Self {
        Self {
            is_valid: true,
            normalized_path: Some(path),
            violation: ViolationType::None,
            message: String::new(),
        }
    }

    pub fn invalid(violation: ViolationType, msg: impl Into<String>) -> Self {
        Self {
            is_valid: false,
            normalized_path: None,
            violation,
            message: msg.into(),
        }
    }
}

/// Path validator with workspace root context.
pub struct PathValidator {
    workspace_root: PathBuf,
}

impl PathValidator {
    pub fn new(workspace: impl Into<PathBuf>) -> Self {
        Self {
            workspace_root: workspace.into(),
        }
    }

    /// Validate a path string against security rules.
    pub fn validate(&self, path: &str) -> ValidationResult {
        // Check for null bytes
        if path.contains('\0') {
            return ValidationResult::invalid(ViolationType::NullByte, "null byte in path");
        }

        // Check dangerous patterns
        for re in dangerous_patterns() {
            if re.is_match(path) {
                if path.starts_with('/') {
                    return ValidationResult::invalid(
                        ViolationType::AbsolutePath,
                        "absolute paths not allowed",
                    );
                }
                if path.contains("..") {
                    return ValidationResult::invalid(
                        ViolationType::PathEscape,
                        "path traversal detected",
                    );
                }
            }
        }

        // Normalize and join to workspace
        match soothe_nano_utils::normalize_relative(path) {
            Ok(normalized) => {
                let joined = self.workspace_root.join(&normalized);
                ValidationResult::valid(joined)
            }
            Err(e) => ValidationResult::invalid(ViolationType::PathEscape, e),
        }
    }

    /// Validate with an explicit workspace override.
    pub fn validate_with_workspace(&self, path: &str, workspace: &Path) -> ValidationResult {
        let validator = PathValidator::new(workspace);
        validator.validate(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_relative_path() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.validate("src/main.rs");
        assert!(r.is_valid);
    }

    #[test]
    fn rejects_traversal() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.validate("../../etc/passwd");
        assert!(!r.is_valid);
        assert_eq!(r.violation, ViolationType::PathEscape);
    }

    #[test]
    fn rejects_absolute() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.validate("/etc/passwd");
        assert!(!r.is_valid);
        assert_eq!(r.violation, ViolationType::AbsolutePath);
    }

    #[test]
    fn rejects_null_byte() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.validate("file\0name");
        assert!(!r.is_valid);
        assert_eq!(r.violation, ViolationType::NullByte);
    }
}
