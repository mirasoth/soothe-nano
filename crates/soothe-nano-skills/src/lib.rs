//! Skill discovery, corpus matching, budget tracking.

pub mod budget;
pub mod budget_format;
pub mod corpus_match;
pub mod corpus_string;
pub mod discovery;

pub use budget::SkillBudget;
pub use budget_format::{
    format_skills_within_budget, BudgetTelemetry as BudgetFormatTelemetry,
    SkillEntry as BudgetSkillEntry,
};
pub use corpus_match::CorpusMatcher;
pub use discovery::{SkillDiscovery, SkillEntry, SkillMarkdown};
