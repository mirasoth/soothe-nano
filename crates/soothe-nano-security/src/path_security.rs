//! Path validation (ported from `security/path_security.py`).

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::OnceLock;

use regex::Regex;

/// Severity levels for validation violations (mirrors `ValidationSeverity`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Default)]
pub enum ValidationSeverity {
    #[default]
    Medium = 2,
    Low = 1,
    High = 3,
    Critical = 4,
}

/// Violation type label returned to Python (string convention).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ViolationType {
    None,
    PathEscape,
    AbsolutePath,
    NullByte,
    SymlinkEscape,
    TooLarge,
    Suspicious,
    BlockedSystemPath,
    DangerousComponent,
    TooManyComponents,
    WorkspaceBoundary,
    EmptyPath,
    InvalidType,
    PathTooLong,
}

impl ViolationType {
    /// Python-convention label for the violation.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::PathEscape => "path_traversal",
            Self::AbsolutePath => "absolute_path_blocked",
            Self::NullByte => "suspicious_null_byte",
            Self::SymlinkEscape => "symlink_escape",
            Self::TooLarge => "too_large",
            Self::Suspicious => "suspicious",
            Self::BlockedSystemPath => "blocked_system_path",
            Self::DangerousComponent => "dangerous_component",
            Self::TooManyComponents => "too_many_components",
            Self::WorkspaceBoundary => "workspace_boundary_violation",
            Self::EmptyPath => "empty_path",
            Self::InvalidType => "invalid_type",
            Self::PathTooLong => "path_too_long",
        }
    }
}

/// Result of path validation (mirrors the Python `ValidationResult` dataclass).
#[derive(Debug, Clone)]
pub struct ValidationResult {
    pub is_valid: bool,
    pub normalized_path: Option<String>,
    pub violation_type: String,
    pub message: String,
    pub severity: ValidationSeverity,
    pub details: HashMap<String, String>,
}

impl ValidationResult {
    pub fn valid(normalized_path: impl Into<String>) -> Self {
        Self {
            is_valid: true,
            normalized_path: Some(normalized_path.into()),
            violation_type: String::new(),
            message: String::new(),
            severity: ValidationSeverity::default(),
            details: HashMap::new(),
        }
    }

    pub fn invalid(violation: ViolationType, msg: impl Into<String>) -> Self {
        Self {
            is_valid: false,
            normalized_path: None,
            violation_type: violation.as_str().to_string(),
            message: msg.into(),
            severity: ValidationSeverity::High,
            details: HashMap::new(),
        }
    }

    pub fn invalid_with(
        violation: ViolationType,
        msg: impl Into<String>,
        severity: ValidationSeverity,
        details: HashMap<String, String>,
    ) -> Self {
        Self {
            is_valid: false,
            normalized_path: None,
            violation_type: violation.as_str().to_string(),
            message: msg.into(),
            severity,
            details,
        }
    }

    /// `is_blocked` property mirror.
    pub fn is_blocked(&self) -> bool {
        !self.is_valid
    }
}

/// (compiled regex, name) traversal pattern.
struct TraversalPattern {
    re: Regex,
    name: &'static str,
}

/// (compiled regex, name, severity) suspicious pattern.
struct SuspiciousPattern {
    re: Regex,
    name: &'static str,
    severity: ValidationSeverity,
}

/// Compiled pattern tables (lazy-init, shared across validators).
static TRAVERSAL_PATTERNS: OnceLock<Vec<TraversalPattern>> = OnceLock::new();
static SUSPICIOUS_PATTERNS: OnceLock<Vec<SuspiciousPattern>> = OnceLock::new();

fn traversal_patterns() -> &'static Vec<TraversalPattern> {
    TRAVERSAL_PATTERNS.get_or_init(|| {
        // (pattern, name) — order matches Python TRAVERSAL_PATTERNS.
        let raw: &[(&str, &str)] = &[
            (r"\.\./", "dot_dot_slash"),
            (r"\.\.\\", "dot_dot_backslash"),
            (r"\.\.$", "dot_dot_end"),
            (r"^\.\./", "leading_dot_dot_slash"),
            (r"^\.\.\\", "leading_dot_dot_backslash"),
            (r"/\.\./", "mid_dot_dot_slash"),
            (r"\\\.\.\\", "mid_dot_dot_backslash"),
            (r"(?i)%2e%2e%2f", "url_encoded_dot_dot_slash"),
            (r"(?i)%2e%2e%5c", "url_encoded_dot_dot_backslash"),
            (r"\.\.\.\.+", "multiple_dots"),
        ];
        raw.iter()
            .map(|(pat, name)| TraversalPattern {
                re: Regex::new(pat)
                    .unwrap_or_else(|e| panic!("invalid traversal regex {pat:?}: {e}")),
                name,
            })
            .collect()
    })
}

fn suspicious_patterns() -> &'static Vec<SuspiciousPattern> {
    SUSPICIOUS_PATTERNS.get_or_init(|| {
        // (pattern, name, severity) — order matches Python SUSPICIOUS_PATTERNS.
        let raw: &[(&str, &str, ValidationSeverity)] = &[
            (r"\x00", "null_byte", ValidationSeverity::Critical),
            (r"\n", "newline", ValidationSeverity::High),
            (r"\r", "carriage_return", ValidationSeverity::High),
            (r"\t", "tab", ValidationSeverity::Low),
            (r"[\x00-\x1f]", "control_chars", ValidationSeverity::High),
            (r"\x7f", "delete_char", ValidationSeverity::Medium),
            (
                r"[\ufff0-\uffff]",
                "unicode_special",
                ValidationSeverity::Medium,
            ),
            (r"^//", "unc_path_forward", ValidationSeverity::Critical),
            (
                r"^\\\\\\\\",
                "unc_path_backslash",
                ValidationSeverity::Critical,
            ),
        ];
        raw.iter()
            .map(|(pat, name, sev)| SuspiciousPattern {
                re: Regex::new(pat)
                    .unwrap_or_else(|e| panic!("invalid suspicious regex {pat:?}: {e}")),
                name,
                severity: *sev,
            })
            .collect()
    })
}

/// Dangerous path components (mirrors `PathValidator::DANGEROUS_COMPONENTS`).
static DANGEROUS_COMPONENTS: OnceLock<Vec<&str>> = OnceLock::new();

fn dangerous_components() -> &'static Vec<&'static str> {
    DANGEROUS_COMPONENTS.get_or_init(|| {
        vec![
            "..",
            ".",
            "~",
            "",
            ".git",
            ".svn",
            ".hg",
            "__pycache__",
            ".DS_Store",
            "Thumbs.db",
            ".vscode",
            ".idea",
            ".claude",
            ".bashrc",
            ".bash_profile",
            ".zshrc",
            ".zprofile",
            ".profile",
            ".gitconfig",
            ".gitmodules",
            ".ripgreprc",
            ".mcp.json",
            ".claude.json",
        ]
    })
}

/// Blocked system paths (mirrors `PathValidator::BLOCKED_SYSTEM_PATHS`).
static BLOCKED_SYSTEM_PATHS: OnceLock<Vec<&str>> = OnceLock::new();

fn blocked_system_paths() -> &'static Vec<&'static str> {
    BLOCKED_SYSTEM_PATHS.get_or_init(|| {
        vec![
            "/etc",
            "/bin",
            "/sbin",
            "/usr",
            "/lib",
            "/lib64",
            "/dev",
            "/proc",
            "/sys",
            "/root",
            "/boot",
            "/var/log",
            "/tmp/..",
            "/home/..",
            "C:\\Windows",
            "C:\\Windows\\System32",
            "C:\\Program Files",
            "C:\\Program Files (x86)",
            "C:\\Users\\..",
        ]
    })
}

/// Path validator with workspace root context.
#[allow(dead_code)]
#[allow(clippy::result_large_err)]
pub struct PathValidator {
    workspace_root: PathBuf,
    allow_absolute: bool,
    allow_home_expansion: bool,
    follow_symlinks: bool,
    max_path_length: usize,
    max_components: usize,
    blocked_paths: Vec<String>,
}

impl PathValidator {
    /// Create a minimal validator (workspace only) — for the fast-path binding.
    pub fn new(workspace: impl Into<PathBuf>) -> Self {
        Self {
            workspace_root: workspace.into(),
            allow_absolute: false,
            allow_home_expansion: false,
            follow_symlinks: false,
            max_path_length: 4096,
            max_components: 256,
            blocked_paths: blocked_system_paths()
                .iter()
                .map(|s| s.to_string())
                .collect(),
        }
    }

    /// Create a fully-configured validator mirroring the Python constructor.
    pub fn with_config(
        workspace: impl Into<PathBuf>,
        allow_absolute: bool,
        allow_home_expansion: bool,
        follow_symlinks: bool,
        max_path_length: usize,
        max_components: usize,
        custom_blocked_paths: Option<Vec<String>>,
    ) -> Self {
        let mut blocked = blocked_system_paths()
            .iter()
            .map(|s| s.to_string())
            .collect::<Vec<_>>();
        if let Some(custom) = custom_blocked_paths {
            blocked.extend(custom);
        }
        Self {
            workspace_root: workspace.into(),
            allow_absolute,
            allow_home_expansion,
            follow_symlinks,
            max_path_length,
            max_components,
            blocked_paths: blocked,
        }
    }

    /// Fast-path pre-check: traversal (forward-slash only), absolute-path, null-byte.
    ///
    /// Only the *reject* branch is authoritative for short-circuiting. The
    /// valid branch must still flow through the full pipeline. Backslash
    /// traversal patterns are deliberately NOT checked here so they fall
    /// through to the Python regex pipeline (matching original behavior).
    pub fn fast_check(&self, path: &str) -> Option<ValidationResult> {
        if path.contains('\0') {
            return Some(ValidationResult::invalid_with(
                ViolationType::NullByte,
                "Suspicious pattern detected: null_byte (Rust fast-path)",
                ValidationSeverity::Critical,
                HashMap::from([("fast_path".to_string(), "rust".to_string())]),
            ));
        }

        // Traversal: check only forward-slash patterns (the original
        // fast-path scope). Backslash traversal falls through to Python.
        for tp in traversal_patterns() {
            // Skip backslash and URL-encoded patterns — they fall through
            // to the Python regex pipeline.
            if tp.name.contains("backslash") || tp.name.contains("url_encoded") {
                continue;
            }
            if tp.re.is_match(path) {
                return Some(ValidationResult::invalid_with(
                    ViolationType::PathEscape,
                    format!("Path traversal pattern detected: {}", tp.name),
                    ValidationSeverity::Critical,
                    HashMap::from([
                        ("fast_path".to_string(), "rust".to_string()),
                        ("pattern".to_string(), tp.name.to_string()),
                    ]),
                ));
            }
        }

        // Absolute path check (only when not allowed).
        if !self.allow_absolute && path.starts_with('/') {
            return Some(ValidationResult::invalid_with(
                ViolationType::AbsolutePath,
                "Absolute paths not allowed",
                ValidationSeverity::High,
                HashMap::from([("fast_path".to_string(), "rust".to_string())]),
            ));
        }

        None
    }

    /// Validate a path string against security rules (full pipeline).
    pub fn validate(&self, path: &str) -> ValidationResult {
        // Fast-path reject.
        if let Some(reject) = self.fast_check(path) {
            return reject;
        }

        if path.is_empty() || path.trim().is_empty() {
            return ValidationResult::invalid_with(
                ViolationType::EmptyPath,
                "Path cannot be empty",
                ValidationSeverity::High,
                HashMap::new(),
            );
        }

        if path.len() > self.max_path_length {
            return ValidationResult::invalid_with(
                ViolationType::PathTooLong,
                format!("Path exceeds maximum length of {}", self.max_path_length),
                ValidationSeverity::High,
                HashMap::from([
                    ("length".to_string(), path.len().to_string()),
                    ("max_length".to_string(), self.max_path_length.to_string()),
                ]),
            );
        }

        // Suspicious patterns.
        if let Some(result) = self.check_suspicious_patterns(path) {
            return result;
        }

        // Traversal patterns (full check — redundant with fast_check but
        // matches Python which runs both; the fast_check already rejected).
        if let Some(result) = self.check_traversal_patterns(path) {
            return result;
        }

        // Normalize.
        let normalized = match self.normalize_path(path) {
            Ok(n) => n,
            Err(vr) => return vr,
        };

        // Component count.
        let components = normalized.split('/').filter(|s| !s.is_empty()).count();
        if components > self.max_components {
            return ValidationResult::invalid_with(
                ViolationType::TooManyComponents,
                format!(
                    "Path has {} components, max is {}",
                    components, self.max_components
                ),
                ValidationSeverity::High,
                HashMap::from([
                    ("components".to_string(), components.to_string()),
                    (
                        "max_components".to_string(),
                        self.max_components.to_string(),
                    ),
                ]),
            );
        }

        // Dangerous components.
        if let Some(result) = self.check_dangerous_components(&normalized) {
            return result;
        }

        // Blocked paths.
        if let Some(result) = self.check_blocked_paths(&normalized) {
            return result;
        }

        ValidationResult::valid(normalized)
    }

    /// Validate with an explicit workspace override.
    pub fn validate_with_workspace(&self, path: &str, workspace: &str) -> ValidationResult {
        let validator = PathValidator::new(workspace);
        validator.validate(path)
    }

    /// Check suspicious patterns (null bytes, control chars, UNC paths, etc.).
    pub fn check_suspicious_patterns(&self, path: &str) -> Option<ValidationResult> {
        for sp in suspicious_patterns() {
            if sp.re.is_match(path) {
                let mut details = HashMap::new();
                details.insert("pattern".to_string(), sp.name.to_string());
                return Some(ValidationResult::invalid_with(
                    ViolationType::Suspicious,
                    format!("Suspicious pattern detected: {}", sp.name),
                    sp.severity,
                    details,
                ));
            }
        }
        None
    }

    /// Check traversal patterns.
    pub fn check_traversal_patterns(&self, path: &str) -> Option<ValidationResult> {
        for tp in traversal_patterns() {
            if tp.re.is_match(path) {
                let mut details = HashMap::new();
                details.insert("pattern".to_string(), tp.name.to_string());
                return Some(ValidationResult::invalid_with(
                    ViolationType::PathEscape,
                    format!("Path traversal pattern detected: {}", tp.name),
                    ValidationSeverity::Critical,
                    details,
                ));
            }
        }
        None
    }

    /// Normalize a path string (expanduser / absolute handling).
    #[allow(clippy::result_large_err)]
    fn normalize_path(&self, path: &str) -> Result<String, ValidationResult> {
        if path.contains('~') && !self.allow_home_expansion {
            return Err(ValidationResult::invalid_with(
                ViolationType::Suspicious,
                "Home directory expansion not allowed",
                ValidationSeverity::High,
                HashMap::new(),
            ));
        }

        // Expand ~ if allowed (simple replacement of leading ~/).
        let expanded = if self.allow_home_expansion && path.starts_with("~/") {
            if let Ok(home) = std::env::var("HOME") {
                format!("{}/{}", home, &path[2..])
            } else {
                path.to_string()
            }
        } else {
            path.to_string()
        };

        if std::path::Path::new(&expanded).is_absolute() {
            if !self.allow_absolute {
                return Err(ValidationResult::invalid_with(
                    ViolationType::AbsolutePath,
                    "Absolute paths not allowed",
                    ValidationSeverity::High,
                    HashMap::new(),
                ));
            }
            return Ok(expanded);
        }

        // Normalize: collapse ./ and ../ segments lexically.
        let normalized = normalize_path_lexical(&expanded);
        Ok(normalized)
    }

    /// Check for dangerous path components.
    pub fn check_dangerous_components(&self, path: &str) -> Option<ValidationResult> {
        for part in path.split('/') {
            if dangerous_components().contains(&part) {
                let mut details = HashMap::new();
                details.insert("component".to_string(), part.to_string());
                return Some(ValidationResult::invalid_with(
                    ViolationType::DangerousComponent,
                    format!("Dangerous path component: {}", part),
                    ValidationSeverity::High,
                    details,
                ));
            }
        }
        None
    }

    /// Check against blocked system paths.
    pub fn check_blocked_paths(&self, path: &str) -> Option<ValidationResult> {
        let path_lower = path.to_lowercase();
        for blocked in &self.blocked_paths {
            let blocked_lower = blocked.to_lowercase();
            let blocked_trimmed = blocked_lower.trim_end_matches('/');
            if blocked_trimmed.is_empty() {
                continue;
            }
            if path_lower == *blocked_trimmed
                || path_lower.starts_with(&format!("{}/", blocked_trimmed))
            {
                let mut details = HashMap::new();
                details.insert("blocked_path".to_string(), blocked.clone());
                return Some(ValidationResult::invalid_with(
                    ViolationType::BlockedSystemPath,
                    format!("Access to system path blocked: {}", blocked),
                    ValidationSeverity::Critical,
                    details,
                ));
            }
        }
        None
    }

    /// Sanitize a path: strip null bytes, replace traversal patterns, normalize.
    pub fn sanitize(&self, path: &str) -> String {
        let mut sanitized = path.replace('\0', "");
        for tp in traversal_patterns() {
            sanitized = tp.re.replace_all(&sanitized, "_").to_string();
        }
        // Lexical normalize.
        sanitized = normalize_path_lexical(&sanitized);
        if !self.allow_absolute {
            sanitized = sanitized.trim_start_matches(['/', '\\']).to_string();
        }
        sanitized
    }
}

/// Lexical path normalization (collapse `.` and `..` segments).
fn normalize_path_lexical(path: &str) -> String {
    let mut parts: Vec<&str> = Vec::new();
    let is_absolute = path.starts_with('/');
    for component in path.split('/') {
        match component {
            "" | "." => continue,
            ".." => {
                if let Some(last) = parts.last() {
                    if *last != ".." {
                        parts.pop();
                        continue;
                    }
                }
                parts.push("..");
            }
            other => parts.push(other),
        }
    }
    let joined = parts.join("/");
    if is_absolute {
        format!("/{}", joined)
    } else if joined.is_empty() {
        ".".to_string()
    } else {
        joined
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
        assert_eq!(r.violation_type, ViolationType::PathEscape.as_str());
    }

    #[test]
    fn rejects_absolute() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.validate("/etc/passwd");
        assert!(!r.is_valid);
        assert_eq!(r.violation_type, ViolationType::AbsolutePath.as_str());
    }

    #[test]
    fn rejects_null_byte() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.validate("file\0name");
        assert!(!r.is_valid);
        assert_eq!(r.violation_type, ViolationType::NullByte.as_str());
    }

    #[test]
    fn fast_check_traversal() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.fast_check("../etc/passwd");
        assert!(r.is_some());
        assert!(!r.unwrap().is_valid);
    }

    #[test]
    fn fast_check_valid_returns_none() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.fast_check("src/main.rs");
        assert!(r.is_none());
    }

    #[test]
    fn fast_check_null_byte() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.fast_check("file\0.txt");
        assert!(r.is_some());
        let r = r.unwrap();
        assert!(!r.is_valid);
        assert_eq!(r.violation_type, ViolationType::NullByte.as_str());
    }

    #[test]
    fn fast_check_absolute_when_not_allowed() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.fast_check("/etc/passwd");
        assert!(r.is_some());
        let r = r.unwrap();
        assert!(!r.is_valid);
        assert_eq!(r.violation_type, ViolationType::AbsolutePath.as_str());
    }

    #[test]
    fn fast_check_absolute_when_allowed_returns_none() {
        let v = PathValidator::with_config("/tmp/ws", true, false, false, 4096, 256, None);
        let r = v.fast_check("/etc/passwd");
        assert!(r.is_none());
    }

    #[test]
    fn suspicious_null_byte_detected() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.check_suspicious_patterns("file\x00.txt");
        assert!(r.is_some());
    }

    #[test]
    fn suspicious_control_chars_detected() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.check_suspicious_patterns("file\x01.txt");
        assert!(r.is_some());
    }

    #[test]
    fn dangerous_component_git_detected() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.check_dangerous_components("src/.git/config");
        assert!(r.is_some());
    }

    #[test]
    fn blocked_system_path_etc_detected() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.check_blocked_paths("/etc/passwd");
        assert!(r.is_some());
    }

    #[test]
    fn sanitize_strips_null_and_traversal() {
        let v = PathValidator::new("/tmp/ws");
        let s = v.sanitize("file\x00.txt");
        assert!(!s.contains('\0'));
    }

    #[test]
    fn sanitize_replaces_traversal() {
        let v = PathValidator::new("/tmp/ws");
        let s = v.sanitize("../etc/passwd");
        assert!(!s.contains(".."));
    }

    #[test]
    fn empty_path_rejected() {
        let v = PathValidator::new("/tmp/ws");
        let r = v.validate("");
        assert!(!r.is_valid);
        assert_eq!(r.violation_type, ViolationType::EmptyPath.as_str());
    }

    #[test]
    fn path_too_long_rejected() {
        let v = PathValidator::with_config("/tmp/ws", false, false, false, 10, 256, None);
        let r = v.validate("this_is_a_very_long_path_exceeding_max");
        assert!(!r.is_valid);
        assert_eq!(r.violation_type, ViolationType::PathTooLong.as_str());
    }

    #[test]
    fn normalize_lexical_collapses_dots() {
        assert_eq!(normalize_path_lexical("foo/./bar"), "foo/bar");
        assert_eq!(normalize_path_lexical("foo/bar/../baz"), "foo/baz");
        assert_eq!(normalize_path_lexical("/etc/../tmp"), "/tmp");
    }
}
