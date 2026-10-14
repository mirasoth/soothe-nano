//! Typed WebSocket stream events for tool-call UI.
//!
//! Pure logic for building ``soothe.stream.tool_call.update`` payloads from
//! wire AI message dicts. Extracts tool-call kwargs from ``tool_calls`` and
//! ``tool_call_chunks``, deduplicates by id, and filters out task delegations.

use crate::task_namespace::parse_unified_tool_call_id;
use serde_json::{Map, Value};

/// Wire event type constant.
pub const STREAM_TOOL_CALL_UPDATE: &str = "soothe.stream.tool_call.update";

/// True when a unified id is a step-level ``task`` delegation.
///
/// Mirrors ``is_step_level_task_tool_id``: ``{step}:s:task:…``.
fn is_step_level_task_tool_id(tool_call_id: &str) -> bool {
    let parsed = parse_unified_tool_call_id(tool_call_id);
    if parsed.type_code != "s" {
        return false;
    }
    tool_info_head(&parsed.tool_info) == "task"
}

/// True when a unified id is an inner subgraph ``task`` row.
///
/// Mirrors ``is_inner_subgraph_task_tool_id``: ``{step}:t{n}:task:…``.
fn is_inner_subgraph_task_tool_id(tool_call_id: &str) -> bool {
    let parsed = parse_unified_tool_call_id(tool_call_id);
    if parsed.type_code != "t" {
        return false;
    }
    tool_info_head(&parsed.tool_info) == "task"
}

/// First colon-separated segment of *tool_info*, or empty.
fn tool_info_head(tool_info: &str) -> &str {
    tool_info.split(':').next().unwrap_or("")
}

/// True when a wire update may omit kwargs (unified main or subgraph tool rows).
///
/// Step-level ``task`` delegations are excluded; they are ingested via dedicated
/// paths. Raw provider ids (non-unified) still require parsed args before batching.
pub fn unified_tool_update_allowed_without_args(tool_call_id: &str) -> bool {
    let tcid = tool_call_id.trim();
    if tcid.is_empty() || is_step_level_task_tool_id(tcid) || is_inner_subgraph_task_tool_id(tcid) {
        return false;
    }
    let parsed = parse_unified_tool_call_id(tcid);
    if parsed.type_code != "s" && parsed.type_code != "t" {
        return false;
    }
    tool_info_head(&parsed.tool_info) != "task"
}

/// Extract args dict from a tool call dict.
///
/// Handles ``args`` as dict/str (JSON-parsed) and ``input`` as dict.
fn args_dict_from_tool_call(tc: &Map<String, Value>) -> Value {
    if let Some(raw) = tc.get("args") {
        match raw {
            Value::Object(obj) if !obj.is_empty() => {
                return Value::Object(obj.clone());
            }
            Value::String(s) if !s.trim().is_empty() => {
                if let Ok(Value::Object(parsed)) = serde_json::from_str::<Value>(s) {
                    return Value::Object(parsed);
                }
                return Value::Object(Map::new());
            }
            _ => {}
        }
    }
    if let Some(Value::Object(obj)) = tc.get("input") {
        if !obj.is_empty() {
            return Value::Object(obj.clone());
        }
    }
    Value::Object(Map::new())
}

/// Extract the message body: return ``data`` if it's a dict, else the message itself.
fn wire_message_body(msg: &Map<String, Value>) -> &Map<String, Value> {
    if let Some(Value::Object(data)) = msg.get("data") {
        data
    } else {
        msg
    }
}

/// Build a ``mode=custom`` payload with complete tool invocation kwargs.
fn tool_call_update_event(tool_call_id: &str, name: &str, args: &Value) -> Value {
    let id = tool_call_id.trim();
    let name = if name.trim().is_empty() {
        "tool".to_string()
    } else {
        name.trim().to_string()
    };
    let args = match args {
        Value::Object(obj) => Value::Object(obj.clone()),
        _ => Value::Object(Map::new()),
    };
    let mut map = Map::new();
    map.insert(
        "type".into(),
        Value::String(STREAM_TOOL_CALL_UPDATE.to_string()),
    );
    map.insert("tool_call_id".into(), Value::String(id.to_string()));
    map.insert("name".into(), Value::String(name));
    map.insert("args".into(), args);
    Value::Object(map)
}

/// Extract ``soothe.stream.tool_call.update`` payloads from a wire AI message dict.
///
/// Iterates ``tool_calls`` and ``tool_call_chunks``, deduplicates by id, and
/// builds update events. Tool calls without args are filtered unless
/// [`unified_tool_update_allowed_without_args`] returns true.
pub fn extract_tool_call_updates_from_wire_message(msg: &Value) -> Vec<Value> {
    let msg_obj = match msg.as_object() {
        Some(obj) => obj,
        None => return Vec::new(),
    };
    let body = wire_message_body(msg_obj);
    let mut out: Vec<Value> = Vec::new();
    let mut seen: Vec<String> = Vec::new();

    // tool_calls
    if let Some(Value::Array(tool_calls)) = body.get("tool_calls") {
        for tc in tool_calls {
            let Some(tc_obj) = tc.as_object() else {
                continue;
            };
            append_update(tc_obj, &mut out, &mut seen);
        }
    }

    // tool_call_chunks
    if let Some(Value::Array(chunks)) = body.get("tool_call_chunks") {
        for chunk in chunks {
            let Some(chunk_obj) = chunk.as_object() else {
                continue;
            };
            let tid = get_str_field(chunk_obj, "id");
            if tid.is_empty() || seen.contains(&tid) {
                continue;
            }
            let name = {
                let n = get_str_field(chunk_obj, "name");
                if n.is_empty() {
                    "tool".to_string()
                } else {
                    n
                }
            };
            let args = args_dict_from_tool_call(chunk_obj);
            if args.as_object().is_none_or(|m| m.is_empty())
                && !unified_tool_update_allowed_without_args(&tid)
            {
                continue;
            }
            seen.push(tid.clone());
            out.push(tool_call_update_event(&tid, &name, &args));
        }
    }

    out
}

/// Append a tool call update for *tc* if not already seen and args are valid.
fn append_update(tc: &Map<String, Value>, out: &mut Vec<Value>, seen: &mut Vec<String>) {
    let tid = get_str_field(tc, "id");
    if tid.is_empty() || seen.contains(&tid) {
        return;
    }
    let args = args_dict_from_tool_call(tc);
    let name = {
        let n = get_str_field(tc, "name");
        if n.is_empty() {
            "tool".to_string()
        } else {
            n
        }
    };
    if args.as_object().is_none_or(|m| m.is_empty())
        && !unified_tool_update_allowed_without_args(&tid)
    {
        return;
    }
    seen.push(tid.clone());
    out.push(tool_call_update_event(&tid, &name, &args));
}

/// Extract a string field, trimming whitespace.
fn get_str_field(obj: &Map<String, Value>, key: &str) -> String {
    obj.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // ── unified_tool_update_allowed_without_args ────────────────

    #[test]
    fn empty_id_not_allowed() {
        assert!(!unified_tool_update_allowed_without_args(""));
        assert!(!unified_tool_update_allowed_without_args("   "));
    }

    #[test]
    fn step_level_task_excluded() {
        // {step}:s:task:0 — step-level task delegation
        assert!(!unified_tool_update_allowed_without_args("GHT_01:s:task:0"));
    }

    #[test]
    fn inner_subgraph_task_excluded() {
        // {step}:t1:task:0 — inner subgraph task
        assert!(!unified_tool_update_allowed_without_args(
            "GHT_01:t1:task:0"
        ));
    }

    #[test]
    fn step_level_tool_allowed() {
        // {step}:s:grep:0 — step-level non-task tool
        assert!(unified_tool_update_allowed_without_args("GHT_01:s:grep:0"));
    }

    #[test]
    fn task_level_tool_allowed() {
        // {step}:t1:grep:0 — task-level non-task tool
        assert!(unified_tool_update_allowed_without_args("GHT_01:t1:grep:0"));
    }

    #[test]
    fn non_unified_id_not_allowed() {
        // Raw provider id — no step wire fragment
        assert!(!unified_tool_update_allowed_without_args(
            "functions.grep:0"
        ));
    }

    #[test]
    fn whitespace_trimmed() {
        assert!(unified_tool_update_allowed_without_args(
            "  GHT_01:s:grep:0  "
        ));
    }

    // ── args_dict_from_tool_call ─────────────────────────────────

    #[test]
    fn args_as_dict() {
        let tc = json!({"args": {"key": "val"}});
        let result = args_dict_from_tool_call(tc.as_object().unwrap());
        assert_eq!(result, json!({"key": "val"}));
    }

    #[test]
    fn args_as_json_string() {
        let tc = json!({"args": "{\"key\": \"val\"}"});
        let result = args_dict_from_tool_call(tc.as_object().unwrap());
        assert_eq!(result, json!({"key": "val"}));
    }

    #[test]
    fn args_as_invalid_json_string() {
        let tc = json!({"args": "not json"});
        let result = args_dict_from_tool_call(tc.as_object().unwrap());
        assert!(result.as_object().unwrap().is_empty());
    }

    #[test]
    fn args_empty_string() {
        let tc = json!({"args": "  "});
        let result = args_dict_from_tool_call(tc.as_object().unwrap());
        assert!(result.as_object().unwrap().is_empty());
    }

    #[test]
    fn input_as_dict_fallback() {
        let tc = json!({"input": {"key": "val"}});
        let result = args_dict_from_tool_call(tc.as_object().unwrap());
        assert_eq!(result, json!({"key": "val"}));
    }

    #[test]
    fn no_args_no_input() {
        let tc = json!({"id": "test"});
        let result = args_dict_from_tool_call(tc.as_object().unwrap());
        assert!(result.as_object().unwrap().is_empty());
    }

    // ── extract_tool_call_updates_from_wire_message ──────────────

    #[test]
    fn extract_from_tool_calls() {
        let msg = json!({
            "tool_calls": [
                {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
                {"id": "GHT_01:s:ls:0", "name": "ls", "args": {"path": "/tmp"}},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0]["type"], "soothe.stream.tool_call.update");
        assert_eq!(result[0]["tool_call_id"], "GHT_01:s:grep:0");
        assert_eq!(result[0]["name"], "grep");
        assert_eq!(result[0]["args"]["pattern"], "foo");
    }

    #[test]
    fn extract_deduplicates_by_id() {
        let msg = json!({
            "tool_calls": [
                {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
            ],
            "tool_call_chunks": [
                {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
                {"id": "GHT_01:s:ls:0", "name": "ls", "args": {"path": "/tmp"}},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0]["tool_call_id"], "GHT_01:s:grep:0");
        assert_eq!(result[1]["tool_call_id"], "GHT_01:s:ls:0");
    }

    #[test]
    fn extract_filters_no_args_non_unified() {
        let msg = json!({
            "tool_calls": [
                {"id": "functions.grep:0", "name": "grep"},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert!(result.is_empty());
    }

    #[test]
    fn extract_allows_no_args_unified() {
        let msg = json!({
            "tool_calls": [
                {"id": "GHT_01:s:grep:0", "name": "grep"},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0]["tool_call_id"], "GHT_01:s:grep:0");
        assert!(result[0]["args"].as_object().unwrap().is_empty());
    }

    #[test]
    fn extract_excludes_task_delegations() {
        let msg = json!({
            "tool_calls": [
                {"id": "GHT_01:s:task:0", "name": "task", "args": {}},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert!(result.is_empty());
    }

    #[test]
    fn extract_from_data_wrapper() {
        let msg = json!({
            "data": {
                "tool_calls": [
                    {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
                ]
            }
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0]["tool_call_id"], "GHT_01:s:grep:0");
    }

    #[test]
    fn extract_non_dict_returns_empty() {
        let msg = json!("not a dict");
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert!(result.is_empty());
    }

    #[test]
    fn extract_empty_tool_name_defaults_to_tool() {
        let msg = json!({
            "tool_calls": [
                {"id": "GHT_01:s:grep:0", "name": "", "args": {"pattern": "foo"}},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert_eq!(result[0]["name"], "tool");
    }

    #[test]
    fn extract_from_tool_call_chunks_only() {
        let msg = json!({
            "tool_call_chunks": [
                {"id": "GHT_01:s:grep:0", "name": "grep", "args": "{\"pattern\": \"foo\"}"},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0]["args"]["pattern"], "foo");
    }

    #[test]
    fn extract_skips_non_dict_tool_calls() {
        let msg = json!({
            "tool_calls": [
                "not a dict",
                {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
            ]
        });
        let result = extract_tool_call_updates_from_wire_message(&msg);
        assert_eq!(result.len(), 1);
    }
}
