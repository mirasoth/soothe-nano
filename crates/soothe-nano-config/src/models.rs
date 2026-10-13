//! Config model structs (ported from `config/models.py`).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SootheConfig {
    #[serde(default)]
    pub agent: AgentConfig,
    #[serde(default)]
    pub providers: Vec<ModelProviderConfig>,
    #[serde(default)]
    pub security: SecurityConfig,
    #[serde(default)]
    pub persistence: PersistenceConfig,
    #[serde(default)]
    pub tools: ToolsConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AgentConfig {
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub max_iterations: u32,
    #[serde(default)]
    pub recursion_limit: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelProviderConfig {
    pub name: String,
    pub provider: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default)]
    pub base_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SecurityConfig {
    #[serde(default)]
    pub enable_path_validation: bool,
    #[serde(default)]
    pub max_file_size: u64,
    #[serde(default)]
    pub rate_limit_per_minute: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PersistenceConfig {
    #[serde(default)]
    pub backend: String,
    #[serde(default)]
    pub sqlite_path: Option<String>,
    #[serde(default)]
    pub postgres_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ToolsConfig {
    #[serde(default)]
    pub enabled: Vec<String>,
    #[serde(default)]
    pub disabled: Vec<String>,
}

impl SootheConfig {
    pub fn from_yaml_str(yaml: &str) -> Result<Self, crate::ConfigError> {
        let config: SootheConfig = serde_yaml::from_str(yaml)?;
        Ok(config)
    }

    pub fn from_yaml_file(path: &std::path::Path) -> Result<Self, crate::ConfigError> {
        let contents = std::fs::read_to_string(path)?;
        Self::from_yaml_str(&contents)
    }

    /// Resolve the model name for a given role (e.g. "default", "planner").
    pub fn resolve_model(&self, role: &str) -> Option<&str> {
        if (role == "default" || role == "agent") && !self.agent.model.is_empty() {
            return Some(&self.agent.model);
        }
        self.providers
            .iter()
            .find(|p| p.name == role)
            .map(|p| p.model.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_minimal_yaml() {
        let yaml = "agent:\n  model: gpt-4\n  max_iterations: 25\n";
        let cfg = SootheConfig::from_yaml_str(yaml).unwrap();
        assert_eq!(cfg.agent.model, "gpt-4");
        assert_eq!(cfg.agent.max_iterations, 25);
    }

    #[test]
    fn resolve_default_model() {
        let yaml = "agent:\n  model: claude-3.5\n";
        let cfg = SootheConfig::from_yaml_str(yaml).unwrap();
        assert_eq!(cfg.resolve_model("default"), Some("claude-3.5"));
    }
}
