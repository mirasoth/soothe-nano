//! LLM provider connectivity diagnose checks.

use std::collections::HashSet;

use crate::models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};

/// Router roles that may reference a provider.
pub const ROUTER_ROLES: &[&str] = &["default", "think", "fast", "image", "ocr"];

/// True if value contains an unresolved `${ENV}` reference.
pub fn unresolved_env_ref(value: Option<&str>) -> bool {
    value.map(|v| v.contains("${")).unwrap_or(false)
}

/// Extract provider name from a `provider:model` router/embedding spec.
pub fn provider_from_spec(spec: Option<&str>) -> Option<String> {
    let spec = spec?;
    if spec.is_empty() {
        return None;
    }
    let (provider, model) = spec.split_once(':').unwrap_or((spec, ""));
    if model.is_empty() {
        return None;
    }
    let provider = provider.trim();
    if provider.is_empty() {
        None
    } else {
        Some(provider.to_string())
    }
}

/// Collect active provider names from router role specs and embedding config.
/// `router_specs` = (default, think, fast, image, ocr) — each Option<String>.
/// `embedding_model` and `embedding_profile_model_role` are optional specs.
pub fn active_provider_names(
    router_specs: &[Option<String>; 5],
    embedding_model: Option<&str>,
    embedding_profile_model_role: Option<&str>,
) -> HashSet<String> {
    let mut names = HashSet::new();
    for spec in router_specs.iter() {
        if let Some(name) = provider_from_spec(spec.as_deref()) {
            names.insert(name);
        }
    }
    if let Some(name) = provider_from_spec(embedding_model) {
        names.insert(name);
    }
    if let Some(name) = provider_from_spec(embedding_profile_model_role) {
        names.insert(name);
    }
    names
}

/// Validate that a configured provider has usable credentials.
pub fn check_provider_credentials(
    provider_name: &str,
    api_key: Option<&str>,
    provider_type: &str,
) -> CheckResult {
    if unresolved_env_ref(api_key) {
        return CheckResult::with_details(
            provider_name,
            CheckStatus::Error,
            &format!("{provider_name}: API key still contains unresolved ${{ENV}} reference"),
            vec![
                (
                    "provider_type",
                    serde_json::Value::String(provider_type.to_string()),
                ),
                (
                    "remediation",
                    serde_json::Value::String(format!(
                        "Export the env var referenced by {provider_name}.api_key"
                    )),
                ),
            ],
        );
    }

    if provider_type == "ollama" {
        return CheckResult::with_details(
            provider_name,
            CheckStatus::Ok,
            &format!("{provider_name}: configured (local/keyless provider_type={provider_type})"),
            vec![
                (
                    "provider_type",
                    serde_json::Value::String(provider_type.to_string()),
                ),
                (
                    "api_key_present",
                    serde_json::Value::Bool(api_key.is_some()),
                ),
            ],
        );
    }

    if api_key.map(|k| k.is_empty()).unwrap_or(true) {
        return CheckResult::with_details(
            provider_name,
            CheckStatus::Error,
            &format!("{provider_name}: API key not set"),
            vec![
                (
                    "provider_type",
                    serde_json::Value::String(provider_type.to_string()),
                ),
                (
                    "remediation",
                    serde_json::Value::String(format!(
                        "Set {provider_name}.api_key in config or the corresponding env var"
                    )),
                ),
            ],
        );
    }

    CheckResult::with_details(
        provider_name,
        CheckStatus::Ok,
        &format!("{provider_name}: credentials present (provider_type={provider_type})"),
        vec![
            (
                "provider_type",
                serde_json::Value::String(provider_type.to_string()),
            ),
            ("api_key_present", serde_json::Value::Bool(true)),
        ],
    )
}

/// Downgrade credential failures for providers not used by the active profile.
pub fn demote_inactive_provider_check(
    check: &CheckResult,
    active: &HashSet<String>,
    profile_name: Option<&str>,
) -> CheckResult {
    if active.is_empty() || active.contains(&check.name) {
        return check.clone();
    }
    if check.status != CheckStatus::Error && check.status != CheckStatus::Warning {
        return check.clone();
    }

    let profile_label = profile_name.unwrap_or("active");
    let message = if !check.message.is_empty() {
        format!(
            "{} (not used by active profile '{}')",
            check.message, profile_label
        )
    } else {
        format!(
            "{}: not used by active profile '{}'",
            check.name, profile_label
        )
    };

    // Merge active_profile fields into existing details.
    let mut merged_details = check.details.clone();
    if let Some(obj) = merged_details.as_object_mut() {
        obj.insert(
            "active_profile".into(),
            profile_name
                .map(|s| serde_json::Value::String(s.to_string()))
                .unwrap_or(serde_json::Value::Null),
        );
        obj.insert(
            "required_by_active_profile".into(),
            serde_json::Value::Bool(false),
        );
        obj.insert(
            "impact".into(),
            serde_json::Value::String(
                "Does not affect the active router/embedding providers".into(),
            ),
        );
    }

    CheckResult {
        name: check.name.clone(),
        status: CheckStatus::Info,
        message,
        details: merged_details,
    }
}

/// Check result for a missing provider referenced by the active profile.
pub fn missing_active_provider(name: &str, profile_name: Option<&str>) -> CheckResult {
    let profile_label = profile_name.unwrap_or("active");
    CheckResult::with_details(
        name,
        CheckStatus::Error,
        &format!("{name}: referenced by active profile '{profile_label}' but not in providers[]"),
        vec![
            (
                "active_profile",
                profile_name
                    .map(|s| serde_json::Value::String(s.to_string()))
                    .unwrap_or(serde_json::Value::Null),
            ),
            ("required_by_active_profile", serde_json::Value::Bool(true)),
            (
                "remediation",
                serde_json::Value::String(format!("Add a providers[] entry named '{name}'")),
            ),
        ],
    )
}

/// Check result for no config loaded (skipped).
pub fn providers_no_config() -> CategoryResult {
    CategoryResult::new(
        "providers",
        CheckStatus::Skipped,
        vec![CheckResult::new(
            "providers",
            CheckStatus::Skipped,
            "Skipped (no config loaded)",
        )],
    )
}

/// Check result for no providers configured (error).
pub fn providers_not_configured() -> CategoryResult {
    CategoryResult::new(
        "providers",
        CheckStatus::Error,
        vec![CheckResult::with_details(
            "providers",
            CheckStatus::Error,
            "No LLM providers configured",
            vec![(
                "remediation",
                serde_json::Value::String(
                    "Add providers[] in nano.yml or set OPENAI_API_KEY / ANTHROPIC_API_KEY".into(),
                ),
            )],
        )],
    )
}

/// Build the providers category result from pre-built checks and active set.
/// `status_checks` is the subset used for category status aggregation.
pub fn check_providers_from_results(
    checks: Vec<CheckResult>,
    status_checks: &[CheckResult],
) -> CategoryResult {
    let statuses: Vec<CheckStatus> = status_checks.iter().map(|c| c.status).collect();
    CategoryResult::new("providers", aggregate_status(&statuses), checks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unresolved_env_ref_detected() {
        assert!(unresolved_env_ref(Some("${MY_KEY}")));
        assert!(!unresolved_env_ref(Some("sk-real-key")));
        assert!(!unresolved_env_ref(None));
    }

    #[test]
    fn provider_from_spec_parses() {
        assert_eq!(
            provider_from_spec(Some("openrouter:model")),
            Some("openrouter".into())
        );
        assert_eq!(
            provider_from_spec(Some("dashscope:glm")),
            Some("dashscope".into())
        );
        assert_eq!(provider_from_spec(Some("no-colon")), None);
        assert_eq!(provider_from_spec(Some(":model")), None);
        assert_eq!(provider_from_spec(None), None);
    }

    #[test]
    fn active_provider_names_collects() {
        let router = [
            Some("dashscope:glm".into()),
            Some("dashscope:flash".into()),
            None,
            Some("dashscope:vision".into()),
            Some("omlx:ocr".into()),
        ];
        let names = active_provider_names(&router, Some("dashscope:emb"), None);
        assert!(names.contains("dashscope"));
        assert!(names.contains("omlx"));
        assert_eq!(names.len(), 2);
    }

    #[test]
    fn check_credentials_ok() {
        let r = check_provider_credentials("openrouter", Some("sk-test"), "openai");
        assert_eq!(r.status, CheckStatus::Ok);
        assert_eq!(r.details["api_key_present"], true);
    }

    #[test]
    fn check_credentials_missing_key() {
        let r = check_provider_credentials("openrouter", None, "openai");
        assert_eq!(r.status, CheckStatus::Error);
        assert!(r.message.contains("API key not set"));
    }

    #[test]
    fn check_credentials_env_ref() {
        let r = check_provider_credentials("agnes", Some("${AGNESAI_API_KEY}"), "openai");
        assert_eq!(r.status, CheckStatus::Error);
        assert!(r.message.contains("unresolved"));
    }

    #[test]
    fn check_credentials_ollama_keyless() {
        let r = check_provider_credentials("ollama", None, "ollama");
        assert_eq!(r.status, CheckStatus::Ok);
        assert!(r.message.contains("keyless"));
    }

    #[test]
    fn demote_inactive_downgrades() {
        let active: HashSet<String> = ["dashscope".into()].iter().cloned().collect();
        let check = check_provider_credentials("agnes", None, "openai");
        assert_eq!(check.status, CheckStatus::Error);

        let demoted = demote_inactive_provider_check(&check, &active, Some("production"));
        assert_eq!(demoted.status, CheckStatus::Info);
        assert!(demoted.message.contains("not used by active profile"));
        assert_eq!(demoted.details["required_by_active_profile"], false);
    }

    #[test]
    fn demote_keeps_active_provider() {
        let active: HashSet<String> = ["dashscope".into()].iter().cloned().collect();
        let check = check_provider_credentials("dashscope", Some("sk-ok"), "openai");
        let demoted = demote_inactive_provider_check(&check, &active, Some("production"));
        assert_eq!(demoted.status, CheckStatus::Ok); // unchanged
    }

    #[test]
    fn missing_active_provider_is_error() {
        let r = missing_active_provider("agnes", Some("agnes-eval"));
        assert_eq!(r.status, CheckStatus::Error);
        assert!(r.message.contains("not in providers[]"));
        assert_eq!(r.details["required_by_active_profile"], true);
    }

    #[test]
    fn providers_no_config_is_skipped() {
        let cat = providers_no_config();
        assert_eq!(cat.status, CheckStatus::Skipped);
    }

    #[test]
    fn providers_not_configured_is_error() {
        let cat = providers_not_configured();
        assert_eq!(cat.status, CheckStatus::Error);
    }
}
