//! Vector store backends diagnose checks.

use crate::models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};

/// Check result for a vector store that is not configured.
pub fn not_configured(name: &str) -> CheckResult {
    CheckResult::new(name, CheckStatus::Info, &format!("{name} not configured"))
}

/// Check result for no config loaded (skipped).
pub fn no_config(name: &str) -> CheckResult {
    CheckResult::new(name, CheckStatus::Info, "Skipped (no config loaded)")
}

/// Check result for a successful import (backend ready).
pub fn backend_ready(name: &str, note: &str) -> CheckResult {
    CheckResult::with_details(
        name,
        CheckStatus::Ok,
        &format!("{name} backend ready"),
        vec![("note", serde_json::Value::String(note.to_string()))],
    )
}

/// Check result for a failed import.
pub fn import_failed(name: &str, error: &str, remediation: &str) -> CheckResult {
    CheckResult::with_details(
        name,
        CheckStatus::Error,
        &format!("{name} import failed: {error}"),
        vec![(
            "remediation",
            serde_json::Value::String(remediation.to_string()),
        )],
    )
}

/// Build the vector_stores category result from pre-built CheckResults.
///
/// Caller performs config inspection and import attempts, then passes results here.
pub fn check_vector_stores_from_results(checks: Vec<CheckResult>) -> CategoryResult {
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("vector_stores", aggregate_status(&statuses), checks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn not_configured_is_info() {
        let r = not_configured("pgvector");
        assert_eq!(r.status, CheckStatus::Info);
        assert!(r.message.contains("not configured"));
    }

    #[test]
    fn no_config_is_info() {
        let r = no_config("pgvector");
        assert_eq!(r.status, CheckStatus::Info);
        assert!(r.message.contains("no config"));
    }

    #[test]
    fn backend_ready_is_ok() {
        let r = backend_ready("pgvector", "Connection depends on PostgreSQL");
        assert_eq!(r.status, CheckStatus::Ok);
        assert_eq!(
            r.details["note"].as_str(),
            Some("Connection depends on PostgreSQL")
        );
    }

    #[test]
    fn import_failed_is_error() {
        let r = import_failed("weaviate", "No module", "Install weaviate-client package");
        assert_eq!(r.status, CheckStatus::Error);
        assert_eq!(
            r.details["remediation"].as_str(),
            Some("Install weaviate-client package")
        );
    }

    #[test]
    fn check_vector_stores_aggregates() {
        let checks = vec![
            not_configured("pgvector"),
            backend_ready("weaviate", "ready"),
        ];
        let cat = check_vector_stores_from_results(checks);
        assert_eq!(cat.category, "vector_stores");
        assert_eq!(cat.status, CheckStatus::Info); // Info(1) > Ok(0)
        assert_eq!(cat.checks.len(), 2);
    }
}
