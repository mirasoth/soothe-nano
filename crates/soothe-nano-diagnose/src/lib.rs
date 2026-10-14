//! Diagnose health-check models, status aggregation, and check logic.

pub mod mcp;
pub mod models;
pub mod models_check;
pub mod observability;
pub mod protocols;
pub mod providers;
pub mod tool_deps;
pub mod vector_stores;

pub use models::{aggregate_status, CategoryResult, CheckResult, CheckStatus};
