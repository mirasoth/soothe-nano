//! Langfuse trace/run display-name helpers.

const ROOT_GRAPH_RUN_NAME: &str = "nanoagent-graph";
const EXECUTE_STEP_RUN_NAME: &str = "execute-step";

/// Return the root graph run display name for a trace.
pub fn loop_graph_langfuse_run_display_name(trace_name: Option<&str>) -> String {
    let tn = trace_name.unwrap_or("").trim();
    if tn.is_empty() {
        ROOT_GRAPH_RUN_NAME.to_string()
    } else {
        format!("{tn}:{ROOT_GRAPH_RUN_NAME}")
    }
}

/// Return the execute-phase child run display name for a trace.
pub fn execute_step_langfuse_run_display_name(trace_name: Option<&str>) -> String {
    let tn = trace_name.unwrap_or("").trim();
    if tn.is_empty() {
        EXECUTE_STEP_RUN_NAME.to_string()
    } else {
        format!("{tn}:{EXECUTE_STEP_RUN_NAME}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_loop_graph_with_trace_name() {
        assert_eq!(
            loop_graph_langfuse_run_display_name(Some("my-trace")),
            "my-trace:nanoagent-graph"
        );
    }

    #[test]
    fn test_loop_graph_no_trace_name() {
        assert_eq!(
            loop_graph_langfuse_run_display_name(None),
            "nanoagent-graph"
        );
        assert_eq!(
            loop_graph_langfuse_run_display_name(Some("")),
            "nanoagent-graph"
        );
        assert_eq!(
            loop_graph_langfuse_run_display_name(Some("  ")),
            "nanoagent-graph"
        );
    }

    #[test]
    fn test_execute_step_with_trace_name() {
        assert_eq!(
            execute_step_langfuse_run_display_name(Some("my-trace")),
            "my-trace:execute-step"
        );
    }

    #[test]
    fn test_execute_step_no_trace_name() {
        assert_eq!(execute_step_langfuse_run_display_name(None), "execute-step");
    }
}
