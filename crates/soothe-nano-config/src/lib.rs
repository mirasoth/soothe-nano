//! Config models, env expansion, YAML loading.

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
