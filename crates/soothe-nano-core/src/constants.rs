//! Wire-safe event type string constants.
//!
//! Canonical home for event type strings used across CLI/TUI event processing.

/// Plan events.
pub const PLAN_CREATED: &str = "soothe.cognition.plan.created";

/// Agent loop events (DEBUG level; wire ``mode=custom`` types).
pub const STRANGE_LOOP_STARTED: &str = "soothe.cognition.strange_loop.started";
pub const STRANGE_LOOP_COMPLETED: &str = "soothe.cognition.strange_loop.completed";
pub const STRANGE_LOOP_STEP_STARTED: &str = "soothe.cognition.strange_loop.step.started";
pub const STRANGE_LOOP_STEP_QUEUED: &str = "soothe.cognition.strange_loop.step.queued";
pub const STRANGE_LOOP_STEP_COMPLETED: &str = "soothe.cognition.strange_loop.step.completed";
pub const STRANGE_LOOP_PLAN_DECISION: &str = "soothe.cognition.strange_loop.plan.decision";
pub const STRANGE_LOOP_PLAN_PHASE: &str = "soothe.cognition.strange_loop.plan.phase";

/// Wired specialist lifecycle (orphan SubAgent card).
pub const WIRED_SUBAGENT_STARTED: &str = "soothe.cognition.wired_subagent.started";
pub const WIRED_SUBAGENT_COMPLETED: &str = "soothe.cognition.wired_subagent.completed";
pub const WIRED_SUBAGENT_FAILED: &str = "soothe.cognition.wired_subagent.failed";
pub const WIRED_SUBAGENT_CANCELLED: &str = "soothe.cognition.wired_subagent.cancelled";

pub const INTENT_CLASSIFIED: &str = "soothe.cognition.intent.classified";

/// Clarification relay events.
pub const LOOP_CLARIFICATION_REQUESTED: &str = "soothe.loop.clarification.requested";
pub const LOOP_CLARIFICATION_ANSWERED: &str = "soothe.loop.clarification.answered";
pub const LOOP_CLARIFICATION_DEFERRED: &str = "soothe.loop.clarification.deferred";

/// Stream termination.
pub const STREAM_END: &str = "soothe.stream.end";

/// Display card wire frames (RFC-413).
pub const CARD_CREATED: &str = "soothe.card.created";
pub const CARD_UPDATED: &str = "soothe.card.updated";
pub const CARD_FINALIZED: &str = "soothe.card.finalized";
pub const CARD_REPLAY_BEGIN: &str = "soothe.card.replay.begin";
pub const CARD_REPLAY_END: &str = "soothe.card.replay.end";

/// Protocol-primitive events (wire-visible constants shared across packages).
pub const ERROR: &str = "soothe.error.general.failed";
pub const LLM_RETRY_ATTEMPT: &str = "soothe.cognition.llm.retry.attempt";
pub const MEMORY_RECALLED: &str = "soothe.internal.memory.recalled";
pub const MEMORY_STORED: &str = "soothe.internal.memory.stored";
pub const POLICY_CHECKED: &str = "soothe.internal.policy.checked";
pub const POLICY_DENIED: &str = "soothe.internal.policy.denied";

/// Agent loop configuration constant.
pub const DEFAULT_STRANGE_LOOP_MAX_ITERATIONS: u32 = 10;

/// Return the set of card wire types (created, updated, finalized).
pub fn card_wire_types() -> Vec<&'static str> {
    vec![CARD_CREATED, CARD_UPDATED, CARD_FINALIZED]
}

/// Return the set of card replay wire types (begin, end).
pub fn card_replay_wire_types() -> Vec<&'static str> {
    vec![CARD_REPLAY_BEGIN, CARD_REPLAY_END]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plan_created_constant() {
        assert_eq!(PLAN_CREATED, "soothe.cognition.plan.created");
    }

    #[test]
    fn stream_end_constant() {
        assert_eq!(STREAM_END, "soothe.stream.end");
    }

    #[test]
    fn error_constant() {
        assert_eq!(ERROR, "soothe.error.general.failed");
    }

    #[test]
    fn card_wire_types_set() {
        let types = card_wire_types();
        assert_eq!(types.len(), 3);
        assert!(types.contains(&CARD_CREATED));
        assert!(types.contains(&CARD_UPDATED));
        assert!(types.contains(&CARD_FINALIZED));
    }

    #[test]
    fn card_replay_wire_types_set() {
        let types = card_replay_wire_types();
        assert_eq!(types.len(), 2);
        assert!(types.contains(&CARD_REPLAY_BEGIN));
        assert!(types.contains(&CARD_REPLAY_END));
    }

    #[test]
    fn default_max_iterations() {
        assert_eq!(DEFAULT_STRANGE_LOOP_MAX_ITERATIONS, 10);
    }

    #[test]
    fn protocol_primitives() {
        assert_eq!(LLM_RETRY_ATTEMPT, "soothe.cognition.llm.retry.attempt");
        assert_eq!(MEMORY_RECALLED, "soothe.internal.memory.recalled");
        assert_eq!(MEMORY_STORED, "soothe.internal.memory.stored");
        assert_eq!(POLICY_CHECKED, "soothe.internal.policy.checked");
        assert_eq!(POLICY_DENIED, "soothe.internal.policy.denied");
    }

    #[test]
    fn strange_loop_constants() {
        assert_eq!(
            STRANGE_LOOP_STARTED,
            "soothe.cognition.strange_loop.started"
        );
        assert_eq!(
            STRANGE_LOOP_COMPLETED,
            "soothe.cognition.strange_loop.completed"
        );
        assert_eq!(
            STRANGE_LOOP_STEP_STARTED,
            "soothe.cognition.strange_loop.step.started"
        );
    }

    #[test]
    fn wired_subagent_constants() {
        assert_eq!(
            WIRED_SUBAGENT_STARTED,
            "soothe.cognition.wired_subagent.started"
        );
        assert_eq!(
            WIRED_SUBAGENT_COMPLETED,
            "soothe.cognition.wired_subagent.completed"
        );
        assert_eq!(
            WIRED_SUBAGENT_FAILED,
            "soothe.cognition.wired_subagent.failed"
        );
        assert_eq!(
            WIRED_SUBAGENT_CANCELLED,
            "soothe.cognition.wired_subagent.cancelled"
        );
    }

    #[test]
    fn clarification_relay_constants() {
        assert_eq!(
            LOOP_CLARIFICATION_REQUESTED,
            "soothe.loop.clarification.requested"
        );
        assert_eq!(
            LOOP_CLARIFICATION_ANSWERED,
            "soothe.loop.clarification.answered"
        );
        assert_eq!(
            LOOP_CLARIFICATION_DEFERRED,
            "soothe.loop.clarification.deferred"
        );
    }
}
