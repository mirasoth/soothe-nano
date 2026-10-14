//! MemoryItem — cross-thread long-term memory.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// A unit of long-term knowledge.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryItem {
    #[serde(default = "default_id")]
    pub id: String,
    pub content: String,
    #[serde(default)]
    pub source_thread: Option<String>,
    #[serde(default = "default_created_at")]
    pub created_at: String,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default = "default_importance")]
    pub importance: f64,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

fn default_id() -> String {
    // Placeholder; caller assigns a UUID. Struct is used for serde only.
    String::new()
}
fn default_created_at() -> String {
    // Placeholder; caller assigns now(UTC). Struct is used for serde only.
    String::new()
}
fn default_importance() -> f64 {
    0.5
}

impl MemoryItem {
    pub fn new(content: String) -> Self {
        Self {
            id: default_id(),
            content,
            source_thread: None,
            created_at: default_created_at(),
            tags: Vec::new(),
            importance: default_importance(),
            metadata: HashMap::new(),
        }
    }

    /// True when importance is within [0.0, 1.0].
    pub fn has_valid_importance(&self) -> bool {
        (0.0..=1.0).contains(&self.importance)
    }

    /// True when the item has all of the specified tags (AND logic).
    pub fn has_all_tags(&self, tags: &[String]) -> bool {
        tags.iter().all(|t| self.tags.contains(t))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_item() {
        let m = MemoryItem::new("hello".into());
        assert_eq!(m.content, "hello");
        assert_eq!(m.importance, 0.5);
        assert!(m.tags.is_empty());
    }

    #[test]
    fn importance_bounds() {
        let mut m = MemoryItem::new("x".into());
        assert!(m.has_valid_importance());
        m.importance = 1.5;
        assert!(!m.has_valid_importance());
        m.importance = -0.1;
        assert!(!m.has_valid_importance());
    }

    #[test]
    fn tag_matching() {
        let mut m = MemoryItem::new("x".into());
        m.tags = vec!["alpha".into(), "beta".into()];
        assert!(m.has_all_tags(&["alpha".into()]));
        assert!(m.has_all_tags(&["alpha".into(), "beta".into()]));
        assert!(!m.has_all_tags(&["gamma".into()]));
    }

    #[test]
    fn roundtrip_json() {
        let mut m = MemoryItem::new("test".into());
        m.tags = vec!["a".into()];
        m.importance = 0.8;
        let s = serde_json::to_string(&m).unwrap();
        let back: MemoryItem = serde_json::from_str(&s).unwrap();
        assert_eq!(back.content, "test");
        assert_eq!(back.importance, 0.8);
        assert_eq!(back.tags, vec!["a"]);
    }
}
