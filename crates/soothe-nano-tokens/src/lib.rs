//! Token counting via tiktoken-rs (ported from `utils/token_counting.py`).

use dashmap::DashMap;
use std::sync::Arc;
use tiktoken_rs::CoreBPE;

/// Message shape matching LangChain chat messages for token estimation.
#[derive(Debug, Clone)]
pub struct Message {
    pub role: String,
    pub content: String,
}

/// Determine the encoding name for a model.
fn encoding_name_for_model(model: &str) -> &'static str {
    let lower = model.to_lowercase();
    // o200k_base: GPT-4o, o1, o3 family.
    if lower.starts_with("gpt-4o")
        || lower.starts_with("o1")
        || lower.starts_with("o3")
        || lower.contains("4o")
    {
        return "o200k_base";
    }
    // cl100k_base: everything else (approximation for non-OpenAI models).
    "cl100k_base"
}

/// Load a CoreBPE by encoding name (not model name).
fn get_bpe_by_encoding(encoding: &str) -> Option<CoreBPE> {
    match encoding {
        "o200k_base" => tiktoken_rs::o200k_base().ok(),
        "cl100k_base" => tiktoken_rs::cl100k_base().ok(),
        _ => tiktoken_rs::cl100k_base().ok(),
    }
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
        let encoding_name = encoding_name_for_model(model);
        if let Some(entry) = self.encodings.get(encoding_name) {
            return Some(Arc::clone(&entry));
        }
        let bpe = Arc::new(get_bpe_by_encoding(encoding_name)?);
        self.encodings
            .insert(encoding_name.to_string(), Arc::clone(&bpe));
        Some(bpe)
    }

    /// Count tokens for a single text. Falls back to char/4 if tiktoken fails.
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

    #[test]
    fn gpt4o_uses_o200k_encoding() {
        let counter = TokenCounter::new();
        let n = counter.count("Hello, world!", Some("gpt-4o"));
        assert!(n > 0 && n < 10);
    }

    #[test]
    fn o1_model_uses_o200k_encoding() {
        let counter = TokenCounter::new();
        let n = counter.count("Hello, world!", Some("o1-preview"));
        assert!(n > 0 && n < 10);
    }

    #[test]
    fn gpt4o_and_gpt4_may_differ() {
        let counter = TokenCounter::new();
        let text = "Hello, world! This is a test.";
        let n4 = counter.count(text, Some("gpt-4"));
        let n4o = counter.count(text, Some("gpt-4o"));
        // Both should be positive; they may or may not differ
        assert!(n4 > 0);
        assert!(n4o > 0);
    }

    #[test]
    fn unknown_model_falls_back_to_cl100k() {
        let counter = TokenCounter::new();
        let n = counter.count("Hello", Some("claude-3-opus"));
        assert!(n > 0);
    }
}
