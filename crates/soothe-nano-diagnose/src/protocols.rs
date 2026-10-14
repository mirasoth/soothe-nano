//! Protocol backend import diagnose checks.

use crate::models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};

/// Build a CheckResult for a successful import.
pub fn import_ok(name: &str) -> CheckResult {
    CheckResult::new(name, CheckStatus::Ok, &format!("{name} import successful"))
}

/// Build a CheckResult for a failed import.
pub fn import_error(name: &str, module_path: &str, error: &str) -> CheckResult {
    CheckResult::with_details(
        name,
        CheckStatus::Error,
        &format!("{name} import failed: {error}"),
        vec![
            ("module", serde_json::Value::String(module_path.to_string())),
            (
                "remediation",
                serde_json::Value::String(format!("Install required package for {name}")),
            ),
        ],
    )
}

/// Build the protocols category result from a list of (name, module_path, ok, error_msg) tuples.
/// Python does the actual __import__ and passes the results here.
pub fn check_protocols_from_results(results: &[(String, String, bool, String)]) -> CategoryResult {
    let checks: Vec<CheckResult> = results
        .iter()
        .map(|(name, module_path, ok, error_msg)| {
            if *ok {
                import_ok(name)
            } else {
                import_error(name, module_path, error_msg)
            }
        })
        .collect();
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("protocols", aggregate_status(&statuses), checks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn import_ok_builds_correct_result() {
        let r = import_ok("PostgreSQL Durability");
        assert_eq!(r.status, CheckStatus::Ok);
        assert!(r.message.contains("import successful"));
    }

    #[test]
    fn import_error_builds_correct_result() {
        let r = import_error(
            "PGVector",
            "soothe_nano.backends.vector_store.pgvector",
            "No module",
        );
        assert_eq!(r.status, CheckStatus::Error);
        assert!(r.message.contains("import failed"));
        assert_eq!(
            r.details["module"].as_str(),
            Some("soothe_nano.backends.vector_store.pgvector")
        );
    }

    #[test]
    fn check_protocols_all_ok() {
        let results = vec![
            ("MemU Memory".into(), "m".into(), true, "".into()),
            ("PGVector".into(), "p".into(), true, "".into()),
        ];
        let cat = check_protocols_from_results(&results);
        assert_eq!(cat.category, "protocols");
        assert_eq!(cat.status, CheckStatus::Ok);
        assert_eq!(cat.checks.len(), 2);
    }

    #[test]
    fn check_protocols_mixed_status() {
        let results = vec![
            ("MemU Memory".into(), "m".into(), true, "".into()),
            ("PGVector".into(), "p".into(), false, "No module".into()),
        ];
        let cat = check_protocols_from_results(&results);
        assert_eq!(cat.status, CheckStatus::Error);
    }
}
