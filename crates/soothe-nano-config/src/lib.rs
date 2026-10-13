//! Config models, env expansion, YAML loading.
//!
//! Ports: `config/models.py`, `config/settings.py`, `config/env.py`,
//! `config/constants.py`.
//!
//! The Rust crate owns the canonical struct definitions. Post-migration,
//! Python reads config through the PyO3-exposed struct — no Pydantic
//! model duplication.

pub mod constants;
pub mod env;
pub mod models;

pub use env::expand_env_vars;
pub use models::{
    AgentConfig, ModelProviderConfig, PersistenceConfig, SecurityConfig, SootheConfig,
};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("failed to read config file: {0}")]
    Io(#[from] std::io::Error),
    #[error("failed to parse YAML: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("missing required field: {0}")]
    MissingField(String),
}
