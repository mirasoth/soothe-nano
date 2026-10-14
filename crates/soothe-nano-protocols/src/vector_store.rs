//! VectorStoreProtocol data model — vector records.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// A stored vector record with metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VectorRecord {
    pub id: String,
    #[serde(default)]
    pub score: Option<f64>,
    #[serde(default)]
    pub payload: HashMap<String, serde_json::Value>,
}

impl VectorRecord {
    pub fn new(id: String) -> Self {
        Self {
            id,
            score: None,
            payload: HashMap::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_record() {
        let r = VectorRecord::new("rec-1".into());
        assert_eq!(r.id, "rec-1");
        assert!(r.score.is_none());
        assert!(r.payload.is_empty());
    }

    #[test]
    fn roundtrip_json() {
        let r = VectorRecord {
            id: "x".into(),
            score: Some(0.95),
            payload: HashMap::new(),
        };
        let s = serde_json::to_string(&r).unwrap();
        let back: VectorRecord = serde_json::from_str(&s).unwrap();
        assert_eq!(back.id, "x");
        assert_eq!(back.score, Some(0.95));
    }
}
