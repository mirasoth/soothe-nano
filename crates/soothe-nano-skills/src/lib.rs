//! Skill discovery, corpus matching, budget tracking.
//!
//! Ports: `skills/discovery_tools.py`, `skills/corpus_match.py`,
//! `skills/budget.py`, `skills/search.py`.
//!
//! The Rust part handles filesystem scanning + embedding cosine similarity.
//! Skill *invocation* (LangChain tool wiring) stays Python.

pub mod budget;
pub mod corpus_match;
pub mod discovery;

pub use budget::SkillBudget;
pub use corpus_match::CorpusMatcher;
pub use discovery::{SkillDiscovery, SkillEntry, SkillMarkdown};
