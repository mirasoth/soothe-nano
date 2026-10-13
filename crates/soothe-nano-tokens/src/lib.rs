//! Token counting via tiktoken-rs (ported from `utils/token_counting.py`).
//!
//! Uses native Rust tiktoken — no Python GIL, no import overhead.

use dashmap::DashMap;
use std::sync::Arc;
use tiktoken_rs::{get_bpe_from_model, CoreBPE};

/// Message shape matching LangChain chat messages for token estimation.
#[derive(Debug, Clone)]
pub struct Message {
    pub role: String,
    pub content: String,
}

/// Thread-safe token counter with per-model encoding cache.
pub struct TokenCounter {
    encodings: DashMap<String, Arc<CoreBPE>>,
}

impl TokenCounter {
    pub fn new() -> Self {
        Self {
            encodings: DashMap::new(),
        }
    }

    fn get_encoding(&self, model: &str) -> Option<Arc<CoreBPE>> {
        if let Some(entry) = self.encodings.get(model) {
            return Some(Arc::clone(&entry));
        }
        let bpe = Arc::new(get_bpe_from_model(model).ok()?);
        self.encodings.insert(model.to_string(), Arc::clone(&bpe));
        Some(bpe)
    }

    /// Count tokens for a single text. Falls back to `gpt-4` encoding
    /// if the model is unknown, then to char/4 estimation.
    pub fn count(&self, text: &str, model: Option<&str>) -> usize {
        let model = model.unwrap_or("gpt-4");
        if let Some(bpe) = self.get_encoding(model) {
            return bpe.encode_with_special_tokens(text).len();
        }
        // Fallback: rough estimate
        text.len() / 4
    }

    /// Count tokens for a list of chat messages (includes per-message overhead).
    pub fn count_messages(&self, messages: &[Message], model: Option<&str>) -> usize {
        let model = model.unwrap_or("gpt-4");
        let per_message = if model.starts_with("gpt-3.5") { 5 } else { 4 };
        let mut total = per_message; // priming
        for msg in messages {
            total += per_message;
            total += self.count(&msg.content, Some(model));
            total += self.count(&msg.role, Some(model));
        }
        total
    }
}

impl Default for TokenCounter {
    fn default() -> Self {
        Self::new()
    }
}

/// Convenience free function for one-shot counting.
pub fn count_tokens(text: &str, model: Option<&str>) -> usize {
    TokenCounter::new().count(text, model)
}

impl TokenCounter {
    /// Static one-shot count (creates a temporary counter).
    pub fn count_default(text: &str, model: Option<&str>) -> usize {
        TokenCounter::new().count(text, model)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn count_basic_text() {
        let counter = TokenCounter::new();
        let n = counter.count("Hello, world!", Some("gpt-4"));
        assert!(n > 0 && n < 10);
    }

    #[test]
    fn count_messages_includes_overhead() {
        let counter = TokenCounter::new();
        let msgs = vec![
            Message {
                role: "user".into(),
                content: "Hello".into(),
            },
            Message {
                role: "assistant".into(),
                content: "Hi there".into(),
            },
        ];
        let n = counter.count_messages(&msgs, Some("gpt-4"));
        assert!(n > 10);
    }
}
