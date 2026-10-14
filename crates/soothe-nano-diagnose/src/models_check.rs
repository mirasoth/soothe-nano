//! Embedding / models diagnose checks.

use crate::models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};

/// Build the models category result when no config is loaded (skipped).
pub fn check_models_no_config() -> CategoryResult {
    let checks = vec![CheckResult::new(
        "embedding_role_configured",
        CheckStatus::Skipped,
        "No agent config loaded",
    )];
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("models", aggregate_status(&statuses), checks)
}

/// Build the models category result when embedding_profile is not set (warning).
pub fn check_models_no_profile(
    resolved: Option<&str>,
    skillify_model_role: &str,
    skillify_resolved: Option<&str>,
    embedding_dims: Option<i64>,
) -> CategoryResult {
    let details = vec![
        (
            "resolved",
            resolved
                .map(|s| serde_json::Value::String(s.to_string()))
                .unwrap_or(serde_json::Value::Null),
        ),
        (
            "skillify_model_role",
            serde_json::Value::String(skillify_model_role.to_string()),
        ),
        (
            "skillify_resolved",
            skillify_resolved
                .map(|s| serde_json::Value::String(s.to_string()))
                .unwrap_or(serde_json::Value::Null),
        ),
        (
            "embedding_dims",
            embedding_dims
                .map(|d| serde_json::Value::Number(serde_json::Number::from(d)))
                .unwrap_or(serde_json::Value::Null),
        ),
        (
            "remediation",
            serde_json::Value::String(
                "Set top-level embedding_profile with a stable model + dimensions, \
                 for example model_role=openai:text-embedding-3-small \
                 and embedding_dims=1536"
                    .to_string(),
            ),
        ),
    ];
    let checks = vec![CheckResult::with_details(
        "embedding_role_configured",
        CheckStatus::Warning,
        "embedding_profile is not configured; embeddings may drift across restarts",
        details,
    )];
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("models", aggregate_status(&statuses), checks)
}

/// Build the models category result when embedding_profile is configured (ok).
pub fn check_models_ok(
    resolved: &str,
    skillify_model_role: &str,
    skillify_resolved: Option<&str>,
    embedding_dims: Option<i64>,
) -> CategoryResult {
    let details = vec![
        (
            "skillify_model_role",
            serde_json::Value::String(skillify_model_role.to_string()),
        ),
        (
            "skillify_resolved",
            skillify_resolved
                .map(|s| serde_json::Value::String(s.to_string()))
                .unwrap_or(serde_json::Value::Null),
        ),
        (
            "embedding_dims",
            embedding_dims
                .map(|d| serde_json::Value::Number(serde_json::Number::from(d)))
                .unwrap_or(serde_json::Value::Null),
        ),
    ];
    let checks = vec![CheckResult::with_details(
        "embedding_role_configured",
        CheckStatus::Ok,
        &format!("Embedding role configured ({resolved})"),
        details,
    )];
    let statuses: Vec<CheckStatus> = checks.iter().map(|c| c.status).collect();
    CategoryResult::new("models", aggregate_status(&statuses), checks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_config_is_skipped() {
        let cat = check_models_no_config();
        assert_eq!(cat.category, "models");
        assert_eq!(cat.status, CheckStatus::Skipped);
        assert_eq!(cat.checks[0].name, "embedding_role_configured");
    }

    #[test]
    fn no_profile_is_warning() {
        let cat =
            check_models_no_profile(Some("openai:gpt-4o-mini"), "embedding", None, Some(1536));
        assert_eq!(cat.status, CheckStatus::Warning);
        assert!(cat.checks[0].message.contains("not configured"));
        assert_eq!(cat.checks[0].details["embedding_dims"], 1536);
    }

    #[test]
    fn configured_is_ok() {
        let cat = check_models_ok(
            "dashscope:text-embedding-v4",
            "embedding",
            Some("dashscope:text-embedding-v4"),
            Some(1024),
        );
        assert_eq!(cat.status, CheckStatus::Ok);
        assert!(cat.checks[0].message.contains("configured"));
        assert_eq!(cat.checks[0].details["embedding_dims"], 1024);
    }

    #[test]
    fn null_dims_handled() {
        let cat = check_models_no_profile(None, "embedding", None, None);
        assert_eq!(
            cat.checks[0].details["embedding_dims"],
            serde_json::Value::Null
        );
        assert_eq!(cat.checks[0].details["resolved"], serde_json::Value::Null);
    }
}
