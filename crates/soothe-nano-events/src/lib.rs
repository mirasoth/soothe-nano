//! Event type definitions ported from `events/catalog.py`.
//!
//! Each event is a `serde`-serializable struct that maps 1:1 to the
//! Python `StreamChunk` / custom event schema.

use serde::{Deserialize, Serialize};

/// A chunk emitted during streaming, serialized to JSON for the Python bridge.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum StreamChunk {
    Text(String),
    Event(serde_json::Value),
}

// ── Event structs ──────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StreamEndEvent {
    pub scope: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelFallbackEvent {
    pub from_model: String,
    pub to_model: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolStartEvent {
    pub tool: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolEndEvent {
    pub tool: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillInvokeEvent {
    pub skill: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub query: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextEvent {
    pub context_type: String,
    pub data: serde_json::Value,
}

/// Helper to build a custom event chunk from arbitrary JSON.
pub fn custom_event(data: serde_json::Value) -> StreamChunk {
    StreamChunk::Event(data)
}

/// Helper to build a text chunk.
pub fn text_chunk(text: impl Into<String>) -> StreamChunk {
    StreamChunk::Text(text.into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stream_end_roundtrip() {
        let ev = StreamEndEvent {
            scope: "agent".into(),
            phase: Some("complete".into()),
            reason: None,
        };
        let json = serde_json::to_string(&ev).unwrap();
        let back: StreamEndEvent = serde_json::from_str(&json).unwrap();
        assert_eq!(back.scope, "agent");
        assert_eq!(back.phase, Some("complete".into()));
        assert!(back.reason.is_none());
    }

    #[test]
    fn custom_event_serializes() {
        let chunk = custom_event(serde_json::json!({"type": "custom", "v": 42}));
        let json = serde_json::to_string(&chunk).unwrap();
        assert!(json.contains("custom"));
    }
}
