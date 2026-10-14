//! ConcurrencyPolicy — parallel execution control.

use serde::{Deserialize, Serialize};

/// Scheduling strategy for plan steps.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum StepParallelism {
    Sequential,
    #[default]
    Dependency,
    Max,
}

impl StepParallelism {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "sequential" => Some(Self::Sequential),
            "dependency" => Some(Self::Dependency),
            "max" => Some(Self::Max),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Sequential => "sequential",
            Self::Dependency => "dependency",
            Self::Max => "max",
        }
    }
}

/// All valid step-parallelism values.
pub const STEP_PARALLELISM_VALUES: &[&str] = &["sequential", "dependency", "max"];

/// Controls parallel execution of plan steps, subagents, and LLM calls.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConcurrencyPolicy {
    #[serde(default = "default_max_parallel_steps")]
    pub max_parallel_steps: i64,
    #[serde(default = "default_max_parallel_subagents")]
    pub max_parallel_subagents: i64,
    #[serde(default = "default_global_max_llm_calls")]
    pub global_max_llm_calls: i64,
    #[serde(default = "default_step_parallelism")]
    pub step_parallelism: String,
}

fn default_max_parallel_steps() -> i64 {
    2
}
fn default_max_parallel_subagents() -> i64 {
    4
}
fn default_global_max_llm_calls() -> i64 {
    5
}
fn default_step_parallelism() -> String {
    "dependency".to_string()
}

impl Default for ConcurrencyPolicy {
    fn default() -> Self {
        Self {
            max_parallel_steps: default_max_parallel_steps(),
            max_parallel_subagents: default_max_parallel_subagents(),
            global_max_llm_calls: default_global_max_llm_calls(),
            step_parallelism: default_step_parallelism(),
        }
    }
}

impl ConcurrencyPolicy {
    pub fn new() -> Self {
        Self::default()
    }

    /// True when `max_parallel_steps` means unlimited (value is 0).
    pub fn steps_unlimited(&self) -> bool {
        self.max_parallel_steps == 0
    }

    /// True when `max_parallel_subagents` means unlimited (value is 0).
    pub fn subagents_unlimited(&self) -> bool {
        self.max_parallel_subagents == 0
    }

    /// True when the global LLM call circuit breaker is disabled (value is 0).
    pub fn llm_circuit_disabled(&self) -> bool {
        self.global_max_llm_calls == 0
    }

    /// True when `step_parallelism` is "sequential".
    pub fn is_sequential(&self) -> bool {
        self.step_parallelism == "sequential"
    }

    /// True when `step_parallelism` is "dependency".
    pub fn is_dependency(&self) -> bool {
        self.step_parallelism == "dependency"
    }

    /// True when `step_parallelism` is "max".
    pub fn is_max(&self) -> bool {
        self.step_parallelism == "max"
    }
}

/// True when `value` is a valid step-parallelism strategy.
pub fn is_valid_step_parallelism(value: &str) -> bool {
    STEP_PARALLELISM_VALUES.contains(&value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults() {
        let p = ConcurrencyPolicy::default();
        assert_eq!(p.max_parallel_steps, 2);
        assert_eq!(p.max_parallel_subagents, 4);
        assert_eq!(p.global_max_llm_calls, 5);
        assert_eq!(p.step_parallelism, "dependency");
    }

    #[test]
    fn unlimited_flags() {
        let p = ConcurrencyPolicy {
            max_parallel_steps: 0,
            max_parallel_subagents: 0,
            global_max_llm_calls: 0,
            ..Default::default()
        };
        assert!(p.steps_unlimited());
        assert!(p.subagents_unlimited());
        assert!(p.llm_circuit_disabled());
    }

    #[test]
    fn parallelism_strategies() {
        let p = ConcurrencyPolicy::default();
        assert!(p.is_dependency());
        assert!(!p.is_sequential());
        assert!(!p.is_max());

        let p = ConcurrencyPolicy {
            step_parallelism: "sequential".into(),
            ..Default::default()
        };
        assert!(p.is_sequential());

        let p = ConcurrencyPolicy {
            step_parallelism: "max".into(),
            ..Default::default()
        };
        assert!(p.is_max());
    }

    #[test]
    fn valid_parallelism() {
        assert!(is_valid_step_parallelism("sequential"));
        assert!(is_valid_step_parallelism("dependency"));
        assert!(is_valid_step_parallelism("max"));
        assert!(!is_valid_step_parallelism("bogus"));
    }

    #[test]
    fn roundtrip_json() {
        let p = ConcurrencyPolicy::default();
        let s = serde_json::to_string(&p).unwrap();
        let back: ConcurrencyPolicy = serde_json::from_str(&s).unwrap();
        assert_eq!(back.max_parallel_steps, 2);
        assert_eq!(back.step_parallelism, "dependency");
    }

    #[test]
    fn deserialize_with_defaults() {
        let json = r#"{"max_parallel_steps": 10}"#;
        let p: ConcurrencyPolicy = serde_json::from_str(json).unwrap();
        assert_eq!(p.max_parallel_steps, 10);
        assert_eq!(p.max_parallel_subagents, 4);
        assert_eq!(p.global_max_llm_calls, 5);
        assert_eq!(p.step_parallelism, "dependency");
    }
}
