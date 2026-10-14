//! Diagnose result models (dict-contract compatible).

use serde::{Deserialize, Serialize};

/// Diagnose check status levels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum CheckStatus {
    Ok,
    Warning,
    Error,
    Info,
    Skipped,
}

impl CheckStatus {
    /// String value matching the Python StrEnum contract.
    pub fn as_str(&self) -> &'static str {
        match self {
            CheckStatus::Ok => "ok",
            CheckStatus::Warning => "warning",
            CheckStatus::Error => "error",
            CheckStatus::Info => "info",
            CheckStatus::Skipped => "skipped",
        }
    }

    /// Numeric severity for aggregation (higher = worse).
    pub fn severity(&self) -> i32 {
        match self {
            CheckStatus::Ok => 0,
            CheckStatus::Info => 1,
            CheckStatus::Skipped => 2,
            CheckStatus::Warning => 3,
            CheckStatus::Error => 4,
        }
    }

    /// Parse a status from its string value.
    pub fn parse_str(s: &str) -> Option<Self> {
        match s {
            "ok" => Some(CheckStatus::Ok),
            "warning" => Some(CheckStatus::Warning),
            "error" => Some(CheckStatus::Error),
            "info" => Some(CheckStatus::Info),
            "skipped" => Some(CheckStatus::Skipped),
            _ => None,
        }
    }
}

impl PartialOrd for CheckStatus {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for CheckStatus {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.severity().cmp(&other.severity())
    }
}

/// Result of a single diagnose check.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CheckResult {
    pub name: String,
    pub status: CheckStatus,
    pub message: String,
    pub details: serde_json::Value,
}

impl CheckResult {
    /// Create a new CheckResult with empty details.
    pub fn new(name: &str, status: CheckStatus, message: &str) -> Self {
        Self {
            name: name.to_string(),
            status,
            message: message.to_string(),
            details: serde_json::Value::Object(serde_json::Map::new()),
        }
    }

    /// Create a CheckResult with a details JSON object built from key-value pairs.
    pub fn with_details(
        name: &str,
        status: CheckStatus,
        message: &str,
        details: Vec<(&str, serde_json::Value)>,
    ) -> Self {
        let mut map = serde_json::Map::new();
        for (k, v) in details {
            map.insert(k.to_string(), v);
        }
        Self {
            name: name.to_string(),
            status,
            message: message.to_string(),
            details: serde_json::Value::Object(map),
        }
    }

    /// Serialize to the shared diagnose dict contract (as serde_json::Value).
    pub fn to_dict(&self) -> serde_json::Value {
        let mut map = serde_json::Map::new();
        map.insert(
            "name".to_string(),
            serde_json::Value::String(self.name.clone()),
        );
        map.insert(
            "status".to_string(),
            serde_json::Value::String(self.status.as_str().to_string()),
        );
        map.insert(
            "message".to_string(),
            serde_json::Value::String(self.message.clone()),
        );
        map.insert("details".to_string(), self.details.clone());
        serde_json::Value::Object(map)
    }
}

/// Results for one diagnose category.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CategoryResult {
    pub category: String,
    pub status: CheckStatus,
    pub checks: Vec<CheckResult>,
    pub message: Option<String>,
}

impl CategoryResult {
    pub fn new(category: &str, status: CheckStatus, checks: Vec<CheckResult>) -> Self {
        Self {
            category: category.to_string(),
            status,
            checks,
            message: None,
        }
    }

    pub fn with_message(
        category: &str,
        status: CheckStatus,
        checks: Vec<CheckResult>,
        message: &str,
    ) -> Self {
        Self {
            category: category.to_string(),
            status,
            checks,
            message: Some(message.to_string()),
        }
    }

    /// Serialize to the shared diagnose dict contract (as serde_json::Value).
    pub fn to_dict(&self) -> serde_json::Value {
        let mut map = serde_json::Map::new();
        map.insert(
            "category".to_string(),
            serde_json::Value::String(self.category.clone()),
        );
        map.insert(
            "status".to_string(),
            serde_json::Value::String(self.status.as_str().to_string()),
        );
        map.insert(
            "checks".to_string(),
            serde_json::Value::Array(self.checks.iter().map(|c| c.to_dict()).collect()),
        );
        map.insert(
            "message".to_string(),
            match &self.message {
                Some(m) => serde_json::Value::String(m.clone()),
                None => serde_json::Value::Null,
            },
        );
        serde_json::Value::Object(map)
    }
}

/// Aggregate multiple statuses into one (worst wins).
pub fn aggregate_status(statuses: &[CheckStatus]) -> CheckStatus {
    if statuses.is_empty() {
        return CheckStatus::Ok;
    }
    statuses.iter().copied().max().unwrap_or(CheckStatus::Ok)
}

/// Helper: build a JSON object from key-value string pairs.
pub fn details_from_strings(pairs: Vec<(&str, String)>) -> serde_json::Value {
    let mut map = serde_json::Map::new();
    for (k, v) in pairs {
        map.insert(k.to_string(), serde_json::Value::String(v));
    }
    serde_json::Value::Object(map)
}

/// Helper: merge two JSON details objects (other overlays self).
pub fn merge_details(base: &serde_json::Value, overlay: &serde_json::Value) -> serde_json::Value {
    match (base, overlay) {
        (serde_json::Value::Object(a), serde_json::Value::Object(b)) => {
            let mut merged = a.clone();
            for (k, v) in b {
                merged.insert(k.clone(), v.clone());
            }
            serde_json::Value::Object(merged)
        }
        _ => overlay.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn check_status_severity_ordering() {
        assert!(CheckStatus::Ok < CheckStatus::Info);
        assert!(CheckStatus::Info < CheckStatus::Skipped);
        assert!(CheckStatus::Skipped < CheckStatus::Warning);
        assert!(CheckStatus::Warning < CheckStatus::Error);
    }

    #[test]
    fn check_status_as_str_roundtrip() {
        for s in [
            CheckStatus::Ok,
            CheckStatus::Warning,
            CheckStatus::Error,
            CheckStatus::Info,
            CheckStatus::Skipped,
        ] {
            assert_eq!(CheckStatus::parse_str(s.as_str()), Some(s));
        }
        assert_eq!(CheckStatus::parse_str("bogus"), None);
    }

    #[test]
    fn aggregate_empty_returns_ok() {
        assert_eq!(aggregate_status(&[]), CheckStatus::Ok);
    }

    #[test]
    fn aggregate_worst_wins() {
        let statuses = [CheckStatus::Ok, CheckStatus::Warning, CheckStatus::Info];
        assert_eq!(aggregate_status(&statuses), CheckStatus::Warning);

        let statuses = [CheckStatus::Ok, CheckStatus::Error];
        assert_eq!(aggregate_status(&statuses), CheckStatus::Error);
    }

    #[test]
    fn check_result_to_dict_contract() {
        let cr = CheckResult::with_details(
            "rg",
            CheckStatus::Ok,
            "rg available",
            vec![("path", serde_json::Value::String("/usr/bin/rg".into()))],
        );
        let d = cr.to_dict();
        let obj = d.as_object().unwrap();
        assert_eq!(obj["name"], serde_json::Value::String("rg".into()));
        assert_eq!(obj["status"], serde_json::Value::String("ok".into()));
        assert_eq!(
            obj["message"],
            serde_json::Value::String("rg available".into())
        );
        assert!(obj["details"].is_object());
    }

    #[test]
    fn category_result_to_dict_contract() {
        let checks = vec![CheckResult::new("git", CheckStatus::Ok, "ok")];
        let cat = CategoryResult::new("tool_deps", CheckStatus::Ok, checks);
        let d = cat.to_dict();
        let obj = d.as_object().unwrap();
        assert_eq!(
            obj["category"],
            serde_json::Value::String("tool_deps".into())
        );
        assert_eq!(obj["status"], serde_json::Value::String("ok".into()));
        assert!(obj["checks"].is_array());
        assert_eq!(obj["message"], serde_json::Value::Null);
    }

    #[test]
    fn merge_details_overlay_wins() {
        let base = serde_json::json!({"a": 1, "b": 2});
        let overlay = serde_json::json!({"b": 3, "c": 4});
        let merged = merge_details(&base, &overlay);
        assert_eq!(merged["a"], 1);
        assert_eq!(merged["b"], 3);
        assert_eq!(merged["c"], 4);
    }

    #[test]
    fn details_from_strings_builds_object() {
        let d = details_from_strings(vec![("key", "value".into()), ("key2", "val2".into())]);
        let obj = d.as_object().unwrap();
        assert_eq!(obj["key"], serde_json::Value::String("value".into()));
        assert_eq!(obj["key2"], serde_json::Value::String("val2".into()));
    }
}
