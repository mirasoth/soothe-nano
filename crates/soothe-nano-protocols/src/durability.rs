//! DurabilityProtocol data models — thread lifecycle management.

use serde::{Deserialize, Serialize};

/// Thread priority levels.
pub const PRIORITIES: &[&str] = &["low", "normal", "high"];

/// Thread status values.
pub const STATUSES: &[&str] = &["active", "suspended", "archived"];

/// Extended filter statuses.
pub const FILTER_STATUSES: &[&str] = &[
    "active",
    "suspended",
    "archived",
    "idle",
    "running",
    "error",
];

/// True when `priority` is a valid priority level.
pub fn is_valid_priority(priority: &str) -> bool {
    PRIORITIES.contains(&priority)
}

/// True when `status` is a valid thread status.
pub fn is_valid_status(status: &str) -> bool {
    STATUSES.contains(&status)
}

/// True when `status` is a valid filter status.
pub fn is_valid_filter_status(status: &str) -> bool {
    FILTER_STATUSES.contains(&status)
}

/// Metadata associated with a thread.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadMetadata {
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub plan_summary: Option<String>,
    #[serde(default = "default_policy_profile")]
    pub policy_profile: String,
    #[serde(default)]
    pub labels: Vec<String>,
    #[serde(default = "default_priority")]
    pub priority: String,
    #[serde(default)]
    pub category: Option<String>,
}

fn default_policy_profile() -> String {
    "standard".to_string()
}
fn default_priority() -> String {
    "normal".to_string()
}

impl Default for ThreadMetadata {
    fn default() -> Self {
        Self {
            tags: Vec::new(),
            plan_summary: None,
            policy_profile: default_policy_profile(),
            labels: Vec::new(),
            priority: default_priority(),
            category: None,
        }
    }
}

impl ThreadMetadata {
    pub fn new() -> Self {
        Self::default()
    }

    /// Strip the legacy `claude_sessions` key from a JSON object (if present).
    /// Returns the (possibly modified) value.
    pub fn strip_legacy_claude_sessions(value: serde_json::Value) -> serde_json::Value {
        if let serde_json::Value::Object(mut map) = value {
            map.remove("claude_sessions");
            serde_json::Value::Object(map)
        } else {
            value
        }
    }
}

/// Full information about a thread.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadInfo {
    pub thread_id: String,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
    #[serde(default)]
    pub metadata: ThreadMetadata,
}

impl ThreadInfo {
    pub fn new(thread_id: String, status: String, created_at: String, updated_at: String) -> Self {
        Self {
            thread_id,
            status,
            created_at,
            updated_at,
            metadata: ThreadMetadata::new(),
        }
    }

    /// True when the thread is active.
    pub fn is_active(&self) -> bool {
        self.status == "active"
    }

    /// True when the thread is suspended.
    pub fn is_suspended(&self) -> bool {
        self.status == "suspended"
    }

    /// True when the thread is archived.
    pub fn is_archived(&self) -> bool {
        self.status == "archived"
    }
}

/// Filter criteria for listing threads.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ThreadFilter {
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub tags: Option<Vec<String>>,
    #[serde(default)]
    pub labels: Option<Vec<String>>,
    #[serde(default)]
    pub priority: Option<String>,
    #[serde(default)]
    pub category: Option<String>,
    #[serde(default)]
    pub created_after: Option<String>,
    #[serde(default)]
    pub created_before: Option<String>,
    #[serde(default)]
    pub updated_after: Option<String>,
    #[serde(default)]
    pub updated_before: Option<String>,
}

impl ThreadFilter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Check if a thread matches this filter.
    ///
    /// All non-None fields must match (AND logic). Tags and labels use
    /// subset matching (thread must have all specified tags/labels).
    pub fn matches(&self, info: &ThreadInfo) -> bool {
        if let Some(ref status) = self.status {
            if &info.status != status {
                return false;
            }
        }
        if let Some(ref tags) = self.tags {
            if !tags.iter().all(|t| info.metadata.tags.contains(t)) {
                return false;
            }
        }
        if let Some(ref labels) = self.labels {
            if !labels.iter().all(|l| info.metadata.labels.contains(l)) {
                return false;
            }
        }
        if let Some(ref priority) = self.priority {
            if &info.metadata.priority != priority {
                return false;
            }
        }
        if let Some(ref category) = self.category {
            if info.metadata.category.as_deref() != Some(category.as_str()) {
                return false;
            }
        }
        if let Some(ref after) = self.created_after {
            if info.created_at.as_str() < after.as_str() {
                return false;
            }
        }
        if let Some(ref before) = self.created_before {
            if info.created_at.as_str() > before.as_str() {
                return false;
            }
        }
        if let Some(ref after) = self.updated_after {
            if info.updated_at.as_str() < after.as_str() {
                return false;
            }
        }
        if let Some(ref before) = self.updated_before {
            if info.updated_at.as_str() > before.as_str() {
                return false;
            }
        }
        true
    }

    /// True when the filter has no constraints (matches everything).
    pub fn is_empty(&self) -> bool {
        self.status.is_none()
            && self.tags.is_none()
            && self.labels.is_none()
            && self.priority.is_none()
            && self.category.is_none()
            && self.created_after.is_none()
            && self.created_before.is_none()
            && self.updated_after.is_none()
            && self.updated_before.is_none()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_defaults() {
        let m = ThreadMetadata::new();
        assert_eq!(m.policy_profile, "standard");
        assert_eq!(m.priority, "normal");
        assert!(m.tags.is_empty());
    }

    #[test]
    fn strip_legacy() {
        let json = serde_json::json!({"tags": ["a"], "claude_sessions": [1, 2, 3]});
        let stripped = ThreadMetadata::strip_legacy_claude_sessions(json);
        let map = stripped.as_object().unwrap();
        assert!(!map.contains_key("claude_sessions"));
        assert!(map.contains_key("tags"));
    }

    #[test]
    fn thread_info_status() {
        let info = ThreadInfo::new(
            "t1".into(),
            "active".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-01-02T00:00:00Z".into(),
        );
        assert!(info.is_active());
        assert!(!info.is_suspended());
    }

    #[test]
    fn filter_matches_all_when_empty() {
        let f = ThreadFilter::new();
        assert!(f.is_empty());
        let info = ThreadInfo::new(
            "t1".into(),
            "active".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-01-02T00:00:00Z".into(),
        );
        assert!(f.matches(&info));
    }

    #[test]
    fn filter_by_status() {
        let mut f = ThreadFilter::new();
        f.status = Some("active".into());
        let active = ThreadInfo::new(
            "t1".into(),
            "active".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-01-02T00:00:00Z".into(),
        );
        let archived = ThreadInfo::new(
            "t2".into(),
            "archived".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-01-02T00:00:00Z".into(),
        );
        assert!(f.matches(&active));
        assert!(!f.matches(&archived));
    }

    #[test]
    fn filter_by_tags() {
        let mut info = ThreadInfo::new(
            "t1".into(),
            "active".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-01-02T00:00:00Z".into(),
        );
        info.metadata.tags = vec!["alpha".into(), "beta".into()];
        let mut f = ThreadFilter::new();
        f.tags = Some(vec!["alpha".into()]);
        assert!(f.matches(&info));
        f.tags = Some(vec!["gamma".into()]);
        assert!(!f.matches(&info));
    }

    #[test]
    fn filter_by_time_range() {
        let info = ThreadInfo::new(
            "t1".into(),
            "active".into(),
            "2024-06-15T00:00:00Z".into(),
            "2024-06-20T00:00:00Z".into(),
        );
        let mut f = ThreadFilter::new();
        f.created_after = Some("2024-01-01T00:00:00Z".into());
        assert!(f.matches(&info));
        f.created_after = Some("2024-12-01T00:00:00Z".into());
        assert!(!f.matches(&info));
    }

    #[test]
    fn valid_priorities() {
        assert!(is_valid_priority("low"));
        assert!(is_valid_priority("normal"));
        assert!(is_valid_priority("high"));
        assert!(!is_valid_priority("urgent"));
    }

    #[test]
    fn roundtrip_thread_info() {
        let info = ThreadInfo::new(
            "t1".into(),
            "active".into(),
            "2024-01-01T00:00:00Z".into(),
            "2024-01-02T00:00:00Z".into(),
        );
        let s = serde_json::to_string(&info).unwrap();
        let back: ThreadInfo = serde_json::from_str(&s).unwrap();
        assert_eq!(back.thread_id, "t1");
        assert_eq!(back.metadata.policy_profile, "standard");
    }
}
