//! Observability and tracing diagnose checks.

use crate::models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};

/// Check result for Langfuse disabled (skipped).
pub fn langfuse_disabled() -> CheckResult {
    CheckResult::with_details(
        "langfuse",
        CheckStatus::Skipped,
        "Langfuse disabled (observability.langfuse.enabled=false)",
        vec![("enabled", serde_json::Value::Bool(false))],
    )
}

/// Check result for no config loaded (skipped).
pub fn langfuse_no_config() -> CheckResult {
    CheckResult::new(
        "langfuse",
        CheckStatus::Skipped,
        "Langfuse: no config loaded (skipped)",
    )
}

/// Check result for Langfuse package not installed (warning).
pub fn langfuse_not_installed() -> CheckResult {
    CheckResult::with_details(
        "langfuse",
        CheckStatus::Warning,
        "Langfuse enabled but the langfuse package is not installed",
        vec![
            ("enabled", serde_json::Value::Bool(true)),
            (
                "remediation",
                serde_json::Value::String("pip install langfuse".into()),
            ),
        ],
    )
}

/// Check result for Langfuse package installed (ok).
pub fn langfuse_installed() -> CheckResult {
    CheckResult::with_details(
        "langfuse",
        CheckStatus::Ok,
        "Langfuse package installed",
        vec![("enabled", serde_json::Value::Bool(true))],
    )
}

/// Check result for Langfuse credentials available (ok).
pub fn langfuse_credentials_ok(
    public_key_present: bool,
    secret_key_present: bool,
    host: &str,
) -> CheckResult {
    CheckResult::with_details(
        "langfuse_credentials",
        CheckStatus::Ok,
        "Langfuse credentials available",
        vec![
            ("enabled", serde_json::Value::Bool(true)),
            (
                "public_key_present",
                serde_json::Value::Bool(public_key_present),
            ),
            (
                "secret_key_present",
                serde_json::Value::Bool(secret_key_present),
            ),
            ("host", serde_json::Value::String(host.to_string())),
        ],
    )
}

/// Check result for Langfuse credentials incomplete (warning).
pub fn langfuse_credentials_incomplete(
    public_key_present: bool,
    secret_key_present: bool,
    host: &str,
) -> CheckResult {
    let details = vec![
        ("enabled", serde_json::Value::Bool(true)),
        (
            "public_key_present",
            serde_json::Value::Bool(public_key_present),
        ),
        (
            "secret_key_present",
            serde_json::Value::Bool(secret_key_present),
        ),
        ("host", serde_json::Value::String(host.to_string())),
        (
            "remediation",
            serde_json::Value::String(
                "Set observability.langfuse.public_key / secret_key \
                 (or LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY)"
                    .into(),
            ),
        ),
    ];
    CheckResult::with_details(
        "langfuse_credentials",
        CheckStatus::Warning,
        "Langfuse enabled but credentials are incomplete",
        details,
    )
}

/// Check result for Langfuse health probe OK.
pub fn langfuse_health_ok(host: &str, url: &str, http_status: u16) -> CheckResult {
    CheckResult::with_details(
        "langfuse_health",
        CheckStatus::Ok,
        &format!("Langfuse healthy at {host}"),
        vec![
            ("host", serde_json::Value::String(host.to_string())),
            ("url", serde_json::Value::String(url.to_string())),
            (
                "http_status",
                serde_json::Value::Number(serde_json::Number::from(http_status)),
            ),
        ],
    )
}

/// Check result for Langfuse health probe warning (non-200 status).
pub fn langfuse_health_warning(
    host: &str,
    url: &str,
    http_status: u16,
    remediation: &str,
) -> CheckResult {
    CheckResult::with_details(
        "langfuse_health",
        CheckStatus::Warning,
        &format!("Langfuse health returned HTTP {http_status}"),
        vec![
            ("host", serde_json::Value::String(host.to_string())),
            ("url", serde_json::Value::String(url.to_string())),
            (
                "http_status",
                serde_json::Value::Number(serde_json::Number::from(http_status)),
            ),
            (
                "remediation",
                serde_json::Value::String(remediation.to_string()),
            ),
        ],
    )
}

/// Check result for Langfuse unreachable (warning).
pub fn langfuse_unreachable(host: &str, url: &str, error: &str) -> CheckResult {
    CheckResult::with_details(
        "langfuse_health",
        CheckStatus::Warning,
        &format!("Langfuse unreachable: {error}"),
        vec![
            ("host", serde_json::Value::String(host.to_string())),
            ("url", serde_json::Value::String(url.to_string())),
            (
                "remediation",
                serde_json::Value::String(
                    "Check observability.langfuse.host and network connectivity".into(),
                ),
            ),
        ],
    )
}

/// Build the observability category result from a list of pre-built CheckResults.
pub fn check_observability_from_results(checks: Vec<CheckResult>) -> CategoryResult {
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("observability", aggregate_status(&statuses), checks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_is_skipped() {
        let r = langfuse_disabled();
        assert_eq!(r.status, CheckStatus::Skipped);
        assert_eq!(r.details["enabled"], false);
    }

    #[test]
    fn no_config_is_skipped() {
        let r = langfuse_no_config();
        assert_eq!(r.status, CheckStatus::Skipped);
    }

    #[test]
    fn not_installed_is_warning() {
        let r = langfuse_not_installed();
        assert_eq!(r.status, CheckStatus::Warning);
        assert_eq!(r.details["enabled"], true);
    }

    #[test]
    fn installed_is_ok() {
        let r = langfuse_installed();
        assert_eq!(r.status, CheckStatus::Ok);
    }

    #[test]
    fn credentials_ok_is_ok() {
        let r = langfuse_credentials_ok(true, true, "https://cloud.langfuse.com");
        assert_eq!(r.status, CheckStatus::Ok);
        assert_eq!(r.details["public_key_present"], true);
    }

    #[test]
    fn credentials_incomplete_is_warning() {
        let r = langfuse_credentials_incomplete(true, false, "https://cloud.langfuse.com");
        assert_eq!(r.status, CheckStatus::Warning);
        assert_eq!(r.details["secret_key_present"], false);
    }

    #[test]
    fn health_ok_is_ok() {
        let r = langfuse_health_ok("host", "url", 200);
        assert_eq!(r.status, CheckStatus::Ok);
        assert_eq!(r.details["http_status"], 200);
    }

    #[test]
    fn unreachable_is_warning() {
        let r = langfuse_unreachable("host", "url", "connection refused");
        assert_eq!(r.status, CheckStatus::Warning);
        assert!(r.message.contains("unreachable"));
    }

    #[test]
    fn check_observability_from_results_aggregates() {
        let checks = vec![langfuse_disabled()];
        let cat = check_observability_from_results(checks);
        assert_eq!(cat.category, "observability");
        assert_eq!(cat.status, CheckStatus::Skipped);
    }
}
