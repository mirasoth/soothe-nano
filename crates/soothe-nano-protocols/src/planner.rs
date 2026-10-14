//! PlannerProtocol data models — goal decomposition and plan lifecycle.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

/// Resolve bounded planner-facing text from an outcome dict.
///
/// Checks keys in order: `wave_join_preview`, `task_return_preview`,
/// `output_summary`. Returns the first non-empty string value (stripped).
pub fn planner_outcome_text_preview(outcome: &Value) -> Option<String> {
    let obj = outcome.as_object()?;
    for key in ["wave_join_preview", "task_return_preview", "output_summary"] {
        if let Some(val) = obj.get(key) {
            if let Some(s) = val.as_str() {
                let trimmed = s.trim();
                if !trimmed.is_empty() {
                    return Some(trimmed.to_string());
                }
            }
        }
    }
    None
}

/// Execution hint values.
pub const EXECUTION_HINTS: &[&str] = &["tool", "subagent", "remote", "auto"];

/// Step status values.
pub const STEP_STATUSES: &[&str] = &["pending", "in_progress", "completed", "failed"];

/// Plan status values.
pub const PLAN_STATUSES: &[&str] = &["active", "completed", "failed", "revised"];

/// True when `hint` is a valid execution hint.
pub fn is_valid_execution_hint(hint: &str) -> bool {
    EXECUTION_HINTS.contains(&hint)
}

/// True when `status` is a valid step status.
pub fn is_valid_step_status(status: &str) -> bool {
    STEP_STATUSES.contains(&status)
}

/// True when `status` is a valid plan status.
pub fn is_valid_plan_status(status: &str) -> bool {
    PLAN_STATUSES.contains(&status)
}

/// A single step in a plan.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanStep {
    pub id: String,
    pub description: String,
    #[serde(default = "default_execution_hint")]
    pub execution_hint: String,
    #[serde(default)]
    pub subagent: Option<String>,
    #[serde(default = "default_step_status")]
    pub status: String,
    #[serde(default)]
    pub result: Option<String>,
    #[serde(default)]
    pub depends_on: Vec<String>,
    #[serde(default)]
    pub current_activity: Option<String>,
}

fn default_execution_hint() -> String {
    "auto".to_string()
}
fn default_step_status() -> String {
    "pending".to_string()
}

impl PlanStep {
    pub fn new(id: String, description: String) -> Self {
        Self {
            id,
            description,
            execution_hint: default_execution_hint(),
            subagent: None,
            status: default_step_status(),
            result: None,
            depends_on: Vec::new(),
            current_activity: None,
        }
    }

    /// True when the step is pending.
    pub fn is_pending(&self) -> bool {
        self.status == "pending"
    }

    /// True when the step is in progress.
    pub fn is_in_progress(&self) -> bool {
        self.status == "in_progress"
    }

    /// True when the step is completed.
    pub fn is_completed(&self) -> bool {
        self.status == "completed"
    }

    /// True when the step is failed.
    pub fn is_failed(&self) -> bool {
        self.status == "failed"
    }

    /// True when the step depends on the given step ID.
    pub fn depends_on_step(&self, step_id: &str) -> bool {
        self.depends_on.iter().any(|d| d == step_id)
    }
}

/// A structured decomposition of a goal into executable steps.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Plan {
    #[serde(default)]
    pub id: String,
    pub goal: String,
    pub steps: Vec<PlanStep>,
    #[serde(default)]
    pub current_index: i64,
    #[serde(default = "default_plan_status")]
    pub status: String,
    #[serde(default)]
    pub concurrency: crate::concurrency::ConcurrencyPolicy,
    #[serde(default)]
    pub general_activity: Option<String>,
    #[serde(default)]
    pub is_plan_only: bool,
    #[serde(default)]
    pub reasoning: Option<String>,
}

fn default_plan_status() -> String {
    "active".to_string()
}

impl Plan {
    pub fn new(goal: String) -> Self {
        Self {
            id: String::new(),
            goal,
            steps: Vec::new(),
            current_index: 0,
            status: default_plan_status(),
            concurrency: crate::concurrency::ConcurrencyPolicy::default(),
            general_activity: None,
            is_plan_only: false,
            reasoning: None,
        }
    }

    /// Get the current step (at `current_index`), if any.
    pub fn current_step(&self) -> Option<&PlanStep> {
        self.steps.get(self.current_index as usize)
    }

    /// True when the plan is active.
    pub fn is_active(&self) -> bool {
        self.status == "active"
    }

    /// True when the plan is completed.
    pub fn is_completed(&self) -> bool {
        self.status == "completed"
    }

    /// True when the plan is failed.
    pub fn is_failed(&self) -> bool {
        self.status == "failed"
    }

    /// Get a step by ID.
    pub fn get_step(&self, step_id: &str) -> Option<&PlanStep> {
        self.steps.iter().find(|s| s.id == step_id)
    }

    /// Get all pending step IDs.
    pub fn pending_step_ids(&self) -> Vec<String> {
        self.steps
            .iter()
            .filter(|s| s.is_pending())
            .map(|s| s.id.clone())
            .collect()
    }

    /// Get all completed step IDs.
    pub fn completed_step_ids(&self) -> Vec<String> {
        self.steps
            .iter()
            .filter(|s| s.is_completed())
            .map(|s| s.id.clone())
            .collect()
    }

    /// Get all failed step IDs.
    pub fn failed_step_ids(&self) -> Vec<String> {
        self.steps
            .iter()
            .filter(|s| s.is_failed())
            .map(|s| s.id.clone())
            .collect()
    }
}

/// Result of executing a plan step.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepResult {
    pub step_id: String,
    pub success: bool,
    #[serde(default)]
    pub outcome: HashMap<String, Value>,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub duration_ms: Option<i64>,
    #[serde(default)]
    pub thread_id: Option<String>,
}

impl StepResult {
    pub fn new(step_id: String, success: bool) -> Self {
        Self {
            step_id,
            success,
            outcome: HashMap::new(),
            error: None,
            duration_ms: None,
            thread_id: None,
        }
    }

    /// Convert to evidence string for reflection and planning.
    ///
    /// When `truncate` is true, generates a concise summary.
    /// When `truncate` is false, returns a detailed summary.
    pub fn to_evidence_string(&self, truncate: bool) -> String {
        if !self.success {
            return format!(
                "Step {}: ✗ Error: {}",
                self.step_id,
                self.error.as_deref().unwrap_or("unknown")
            );
        }

        let outcome_type = self
            .outcome
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("generic");
        let tool_name = self
            .outcome
            .get("tool_name")
            .and_then(|v| v.as_str())
            .unwrap_or("tool");
        let size_bytes = self
            .outcome
            .get("size_bytes")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);

        match outcome_type {
            "error" => {
                let err = self
                    .outcome
                    .get("error")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                format!("Step {}: ✗ Error: {}", self.step_id, err)
            }
            "file_read" => {
                let (lines, files) = self.read_success_indicators();
                let entity_preview = self.entities_preview();
                let entity_str = if entity_preview.is_empty() {
                    "files"
                } else {
                    &entity_preview
                };
                format!(
                    "Step {}: ✓ {} ({} lines, {} files) - {}",
                    self.step_id, tool_name, lines, files, entity_str
                )
            }
            "web_search" => {
                let results = self.web_search_results_count();
                format!(
                    "Step {}: ✓ {} ({} results)",
                    self.step_id, tool_name, results
                )
            }
            "code_exec" => {
                format!(
                    "Step {}: ✓ {} (executed successfully)",
                    self.step_id, tool_name
                )
            }
            "subagent" => {
                if let Some(preview_src) = planner_outcome_text_preview(&Value::Object(
                    self.outcome
                        .iter()
                        .map(|(k, v)| (k.clone(), v.clone()))
                        .collect(),
                )) {
                    let prev = if truncate {
                        let max = 800;
                        if preview_src.len() > max {
                            format!("{}…", &preview_src[..max])
                        } else {
                            preview_src
                        }
                    } else {
                        preview_src
                    };
                    format!("Step {}: ✓ {} — {}", self.step_id, tool_name, prev)
                } else {
                    format!(
                        "Step {}: ✓ {} (delegation completed)",
                        self.step_id, tool_name
                    )
                }
            }
            _ => {
                let preview = if size_bytes > 0 {
                    format!("{} bytes", size_bytes)
                } else {
                    "completed".to_string()
                };
                format!("Step {}: ✓ {} ({})", self.step_id, tool_name, preview)
            }
        }
    }

    fn read_success_indicators(&self) -> (i64, i64) {
        let si = self.outcome.get("success_indicators");
        let lines = si
            .and_then(|v| v.get("lines"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let files = si
            .and_then(|v| v.get("files_found"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        (lines, files)
    }

    fn web_search_results_count(&self) -> i64 {
        self.outcome
            .get("success_indicators")
            .and_then(|v| v.get("results_count"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
    }

    fn entities_preview(&self) -> String {
        self.outcome
            .get("entities")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|e| e.as_str())
                    .take(3)
                    .collect::<Vec<_>>()
                    .join(", ")
            })
            .unwrap_or_default()
    }
}

/// Context available to the planner.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PlanContext {
    #[serde(default)]
    pub recent_messages: Vec<String>,
    #[serde(default)]
    pub available_capabilities: Vec<String>,
    #[serde(default)]
    pub completed_steps: Vec<StepResult>,
    #[serde(default)]
    pub routing_classification: Option<Value>,
    #[serde(default)]
    pub workspace: Option<String>,
    #[serde(default)]
    pub working_memory_excerpt: Option<String>,
    #[serde(default)]
    pub thread_id: Option<String>,
}

impl PlanContext {
    pub fn new() -> Self {
        Self::default()
    }
}

/// Report status for a step.
pub const REPORT_STATUSES: &[&str] = &["completed", "failed", "skipped"];

/// Report from a single executed step.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepReport {
    pub step_id: String,
    pub description: String,
    #[serde(default = "default_report_status")]
    pub status: String,
    #[serde(default)]
    pub result: String,
    #[serde(default)]
    pub duration_ms: i64,
    #[serde(default)]
    pub depends_on: Vec<String>,
}

fn default_report_status() -> String {
    "completed".to_string()
}

impl StepReport {
    pub fn new(step_id: String, description: String) -> Self {
        Self {
            step_id,
            description,
            status: default_report_status(),
            result: String::new(),
            duration_ms: 0,
            depends_on: Vec::new(),
        }
    }
}

/// Goal status for reports.
pub const GOAL_REPORT_STATUSES: &[&str] = &["completed", "failed"];

/// Aggregate report from a completed goal.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoalReport {
    pub goal_id: String,
    pub description: String,
    #[serde(default)]
    pub step_reports: Vec<StepReport>,
    #[serde(default)]
    pub summary: String,
    #[serde(default = "default_goal_report_status")]
    pub status: String,
    #[serde(default)]
    pub duration_ms: i64,
    #[serde(default)]
    pub reflection_assessment: String,
    #[serde(default)]
    pub cross_validation_notes: String,
}

fn default_goal_report_status() -> String {
    "completed".to_string()
}

impl GoalReport {
    pub fn new(goal_id: String, description: String) -> Self {
        Self {
            goal_id,
            description,
            step_reports: Vec::new(),
            summary: String::new(),
            status: default_goal_report_status(),
            duration_ms: 0,
            reflection_assessment: String::new(),
            cross_validation_notes: String::new(),
        }
    }

    /// True when the goal report is completed.
    pub fn is_completed(&self) -> bool {
        self.status == "completed"
    }

    /// True when the goal report is failed.
    pub fn is_failed(&self) -> bool {
        self.status == "failed"
    }

    /// Total number of step reports.
    pub fn step_count(&self) -> usize {
        self.step_reports.len()
    }

    /// Count of step reports with a given status.
    pub fn count_by_status(&self, status: &str) -> usize {
        self.step_reports
            .iter()
            .filter(|r| r.status == status)
            .count()
    }
}

/// Goal directive action values.
pub const GOAL_DIRECTIVE_ACTIONS: &[&str] = &[
    "create",
    "decompose",
    "adjust_priority",
    "add_dependency",
    "fail",
    "complete",
];

/// True when `action` is a valid goal directive action.
pub fn is_valid_goal_directive_action(action: &str) -> bool {
    GOAL_DIRECTIVE_ACTIONS.contains(&action)
}

/// A single goal management directive from reflection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoalDirective {
    pub action: String,
    #[serde(default)]
    pub goal_id: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub priority: Option<i64>,
    #[serde(default)]
    pub parent_id: Option<String>,
    #[serde(default)]
    pub depends_on: Vec<String>,
    #[serde(default)]
    pub rationale: String,
}

impl GoalDirective {
    pub fn new(action: String) -> Self {
        Self {
            action,
            goal_id: String::new(),
            description: String::new(),
            priority: None,
            parent_id: None,
            depends_on: Vec::new(),
            rationale: String::new(),
        }
    }
}

/// Planner's assessment of plan progress.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Reflection {
    pub assessment: String,
    pub should_revise: bool,
    pub feedback: String,
    #[serde(default)]
    pub blocked_steps: Vec<String>,
    #[serde(default)]
    pub failed_details: HashMap<String, String>,
    #[serde(default)]
    pub goal_directives: Vec<GoalDirective>,
}

impl Reflection {
    pub fn new(assessment: String, should_revise: bool, feedback: String) -> Self {
        Self {
            assessment,
            should_revise,
            feedback,
            blocked_steps: Vec::new(),
            failed_details: HashMap::new(),
            goal_directives: Vec::new(),
        }
    }

    /// True when there are blocked steps.
    pub fn has_blocked_steps(&self) -> bool {
        !self.blocked_steps.is_empty()
    }

    /// True when there are failed step details.
    pub fn has_failed_details(&self) -> bool {
        !self.failed_details.is_empty()
    }

    /// True when there are goal directives.
    pub fn has_goal_directives(&self) -> bool {
        !self.goal_directives.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plan_step_defaults() {
        let s = PlanStep::new("s1".into(), "do thing".into());
        assert_eq!(s.execution_hint, "auto");
        assert_eq!(s.status, "pending");
        assert!(s.is_pending());
        assert!(!s.is_completed());
    }

    #[test]
    fn plan_step_depends_on() {
        let mut s = PlanStep::new("s2".into(), "step 2".into());
        s.depends_on = vec!["s1".into()];
        assert!(s.depends_on_step("s1"));
        assert!(!s.depends_on_step("s3"));
    }

    #[test]
    fn plan_current_step() {
        let mut p = Plan::new("goal".into());
        p.steps = vec![
            PlanStep::new("s1".into(), "first".into()),
            PlanStep::new("s2".into(), "second".into()),
        ];
        assert_eq!(p.current_step().unwrap().id, "s1");
        p.current_index = 1;
        assert_eq!(p.current_step().unwrap().id, "s2");
        p.current_index = 5;
        assert!(p.current_step().is_none());
    }

    #[test]
    fn plan_step_filters() {
        let mut p = Plan::new("goal".into());
        let mut s1 = PlanStep::new("s1".into(), "first".into());
        s1.status = "completed".into();
        let mut s2 = PlanStep::new("s2".into(), "second".into());
        s2.status = "failed".into();
        let s3 = PlanStep::new("s3".into(), "third".into());
        p.steps = vec![s1, s2, s3];
        assert_eq!(p.pending_step_ids(), vec!["s3"]);
        assert_eq!(p.completed_step_ids(), vec!["s1"]);
        assert_eq!(p.failed_step_ids(), vec!["s2"]);
    }

    #[test]
    fn evidence_string_failed() {
        let r = StepResult::new("s1".into(), false);
        let s = r.to_evidence_string(true);
        assert!(s.contains("✗ Error"));
        assert!(s.contains("s1"));
    }

    #[test]
    fn evidence_string_generic() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("size_bytes".into(), Value::from(1024));
        let s = r.to_evidence_string(true);
        assert!(s.contains("1024 bytes"));
    }

    #[test]
    fn evidence_string_file_read() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("type".into(), Value::from("file_read"));
        r.outcome
            .insert("tool_name".into(), Value::from("read_file"));
        r.outcome.insert(
            "success_indicators".into(),
            serde_json::json!({"lines": 42, "files_found": 3}),
        );
        r.outcome.insert(
            "entities".into(),
            Value::from(vec!["foo.py", "bar.py", "baz.py", "extra.py"]),
        );
        let s = r.to_evidence_string(true);
        assert!(s.contains("42 lines"));
        assert!(s.contains("3 files"));
        assert!(s.contains("foo.py"));
        assert!(!s.contains("extra.py"));
    }

    #[test]
    fn evidence_string_web_search() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("type".into(), Value::from("web_search"));
        r.outcome.insert("tool_name".into(), Value::from("search"));
        r.outcome.insert(
            "success_indicators".into(),
            serde_json::json!({"results_count": 5}),
        );
        let s = r.to_evidence_string(true);
        assert!(s.contains("5 results"));
    }

    #[test]
    fn evidence_string_code_exec() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("type".into(), Value::from("code_exec"));
        r.outcome.insert("tool_name".into(), Value::from("python"));
        let s = r.to_evidence_string(true);
        assert!(s.contains("executed successfully"));
    }

    #[test]
    fn evidence_string_subagent_with_preview() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("type".into(), Value::from("subagent"));
        r.outcome.insert("tool_name".into(), Value::from("planner"));
        r.outcome
            .insert("task_return_preview".into(), Value::from("  result text  "));
        let s = r.to_evidence_string(true);
        assert!(s.contains("result text"));
    }

    #[test]
    fn evidence_string_subagent_no_preview() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("type".into(), Value::from("subagent"));
        r.outcome.insert("tool_name".into(), Value::from("planner"));
        let s = r.to_evidence_string(true);
        assert!(s.contains("delegation completed"));
    }

    #[test]
    fn evidence_string_subagent_truncation() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("type".into(), Value::from("subagent"));
        r.outcome.insert("tool_name".into(), Value::from("planner"));
        let long_text = "x".repeat(1000);
        r.outcome
            .insert("task_return_preview".into(), Value::from(long_text));
        let truncated = r.to_evidence_string(true);
        assert!(truncated.contains('…'));
        let full = r.to_evidence_string(false);
        assert!(!full.contains('…'));
    }

    #[test]
    fn evidence_string_error_type() {
        let mut r = StepResult::new("s1".into(), true);
        r.outcome.insert("type".into(), Value::from("error"));
        r.outcome
            .insert("error".into(), Value::from("something broke"));
        let s = r.to_evidence_string(true);
        assert!(s.contains("✗ Error: something broke"));
    }

    #[test]
    fn outcome_text_preview_resolves_keys() {
        let outcome = serde_json::json!({"wave_join_preview": "  wave  "});
        assert_eq!(planner_outcome_text_preview(&outcome), Some("wave".into()));
        let outcome = serde_json::json!({"task_return_preview": "  ret  "});
        assert_eq!(planner_outcome_text_preview(&outcome), Some("ret".into()));
        let outcome = serde_json::json!({"output_summary": "  sum  "});
        assert_eq!(planner_outcome_text_preview(&outcome), Some("sum".into()));
    }

    #[test]
    fn outcome_text_preview_empty() {
        let outcome = serde_json::json!({"other": "val"});
        assert_eq!(planner_outcome_text_preview(&outcome), None);
        let outcome = serde_json::json!({"wave_join_preview": "  "});
        assert_eq!(planner_outcome_text_preview(&outcome), None);
    }

    #[test]
    fn outcome_text_preview_priority() {
        let outcome = serde_json::json!({
            "wave_join_preview": "wave",
            "task_return_preview": "ret",
        });
        assert_eq!(planner_outcome_text_preview(&outcome), Some("wave".into()));
    }

    #[test]
    fn goal_report_defaults() {
        let r = GoalReport::new("g1".into(), "do goal".into());
        assert_eq!(r.status, "completed");
        assert!(r.is_completed());
        assert_eq!(r.step_count(), 0);
    }

    #[test]
    fn goal_report_count_by_status() {
        let mut r = GoalReport::new("g1".into(), "do goal".into());
        let mut s1 = StepReport::new("s1".into(), "first".into());
        s1.status = "completed".into();
        let mut s2 = StepReport::new("s2".into(), "second".into());
        s2.status = "failed".into();
        r.step_reports = vec![s1, s2];
        assert_eq!(r.count_by_status("completed"), 1);
        assert_eq!(r.count_by_status("failed"), 1);
        assert_eq!(r.count_by_status("skipped"), 0);
    }

    #[test]
    fn reflection_flags() {
        let r = Reflection::new("assessment".into(), true, "feedback".into());
        assert!(r.should_revise);
        assert!(!r.has_blocked_steps());
        assert!(!r.has_failed_details());
        assert!(!r.has_goal_directives());
    }

    #[test]
    fn valid_statuses() {
        assert!(is_valid_execution_hint("tool"));
        assert!(is_valid_execution_hint("auto"));
        assert!(!is_valid_execution_hint("bogus"));
        assert!(is_valid_step_status("pending"));
        assert!(is_valid_plan_status("active"));
        assert!(is_valid_goal_directive_action("create"));
        assert!(!is_valid_goal_directive_action("bogus"));
    }

    #[test]
    fn roundtrip_plan() {
        let mut p = Plan::new("goal".into());
        p.steps = vec![PlanStep::new("s1".into(), "first".into())];
        let s = serde_json::to_string(&p).unwrap();
        let back: Plan = serde_json::from_str(&s).unwrap();
        assert_eq!(back.goal, "goal");
        assert_eq!(back.steps.len(), 1);
        assert_eq!(back.status, "active");
    }

    #[test]
    fn roundtrip_step_result() {
        let r = StepResult::new("s1".into(), true);
        let s = serde_json::to_string(&r).unwrap();
        let back: StepResult = serde_json::from_str(&s).unwrap();
        assert_eq!(back.step_id, "s1");
        assert!(back.success);
    }
}
