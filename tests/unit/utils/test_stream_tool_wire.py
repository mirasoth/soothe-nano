"""Tests for stream tool wire helpers (Rust-backed)."""

from __future__ import annotations

from soothe_nano.ux.stream_tool_wire import (
    STREAM_TOOL_CALL_UPDATE,
    extract_tool_call_updates_from_wire_message,
    tool_call_update_event,
    unified_tool_update_allowed_without_args,
)

# ── tool_call_update_event ────────────────────────────────────


def test_tool_call_update_event_basic() -> None:
    event = tool_call_update_event(tool_call_id="GHT_01:s:grep:0", name="grep", args={"pattern": "foo"})
    assert event["type"] == STREAM_TOOL_CALL_UPDATE
    assert event["tool_call_id"] == "GHT_01:s:grep:0"
    assert event["name"] == "grep"
    assert event["args"] == {"pattern": "foo"}


def test_tool_call_update_event_strips_id() -> None:
    event = tool_call_update_event(tool_call_id="  x  ", name="tool", args={})
    assert event["tool_call_id"] == "x"


def test_tool_call_update_event_empty_name_defaults_to_tool() -> None:
    event = tool_call_update_event(tool_call_id="x", name="", args={})
    assert event["name"] == "tool"


def test_tool_call_update_event_none_args_becomes_empty_dict() -> None:
    event = tool_call_update_event(tool_call_id="x", name="t", args=None)  # type: ignore[arg-type]
    assert event["args"] == {}


# ── unified_tool_update_allowed_without_args ──────────────────


def test_allowed_without_args_step_level_non_task() -> None:
    assert unified_tool_update_allowed_without_args("GHT_01:s:grep:0") is True


def test_allowed_without_args_task_level_non_task() -> None:
    assert unified_tool_update_allowed_without_args("GHT_01:t1:grep:0") is True


def test_allowed_without_args_step_level_task_excluded() -> None:
    assert unified_tool_update_allowed_without_args("GHT_01:s:task:0") is False


def test_allowed_without_args_task_level_task_excluded() -> None:
    assert unified_tool_update_allowed_without_args("GHT_01:t1:task:0") is False


def test_allowed_without_args_non_unified_id_returns_false() -> None:
    assert unified_tool_update_allowed_without_args("call_abc123") is False


def test_allowed_without_args_empty_returns_false() -> None:
    assert unified_tool_update_allowed_without_args("") is False


def test_allowed_without_args_whitespace_only_returns_false() -> None:
    assert unified_tool_update_allowed_without_args("   ") is False


def test_allowed_without_args_strips_whitespace() -> None:
    assert unified_tool_update_allowed_without_args("  GHT_01:s:grep:0  ") is True


# ── extract_tool_call_updates_from_wire_message ───────────────


def test_extract_empty_msg_returns_empty() -> None:
    assert extract_tool_call_updates_from_wire_message({}) == []


def test_extract_non_dict_returns_empty() -> None:
    assert extract_tool_call_updates_from_wire_message("not a dict") == []  # type: ignore[arg-type]


def test_extract_from_tool_calls() -> None:
    msg = {
        "tool_calls": [
            {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["type"] == STREAM_TOOL_CALL_UPDATE
    assert result[0]["tool_call_id"] == "GHT_01:s:grep:0"
    assert result[0]["name"] == "grep"
    assert result[0]["args"] == {"pattern": "foo"}


def test_extract_from_tool_call_chunks() -> None:
    msg = {
        "tool_call_chunks": [
            {"id": "GHT_01:s:grep:0", "name": "grep", "args": '{"pattern": "bar"}'},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["args"] == {"pattern": "bar"}


def test_extract_deduplicates_by_id() -> None:
    msg = {
        "tool_calls": [
            {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
        ],
        "tool_call_chunks": [
            {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "bar"}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["args"] == {"pattern": "foo"}


def test_extract_skips_empty_id() -> None:
    msg = {
        "tool_calls": [
            {"id": "", "name": "grep", "args": {"pattern": "foo"}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert result == []


def test_extract_skips_non_dict_tool_call() -> None:
    msg = {
        "tool_calls": ["not a dict"],  # type: ignore[list-item]
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert result == []


def test_extract_skips_no_args_non_unified_id() -> None:
    msg = {
        "tool_calls": [
            {"id": "call_abc123", "name": "grep", "args": {}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert result == []


def test_extract_allows_no_args_for_unified_id() -> None:
    msg = {
        "tool_calls": [
            {"id": "GHT_01:s:grep:0", "name": "grep", "args": {}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["args"] == {}


def test_extract_excludes_step_level_task() -> None:
    msg = {
        "tool_calls": [
            {"id": "GHT_01:s:task:0", "name": "task", "args": {}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert result == []


def test_extract_uses_input_field_when_no_args() -> None:
    msg = {
        "tool_calls": [
            {"id": "call_abc", "name": "grep", "input": {"pattern": "baz"}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["args"] == {"pattern": "baz"}


def test_extract_invalid_json_args_returns_empty_dict() -> None:
    msg = {
        "tool_calls": [
            {"id": "GHT_01:s:grep:0", "name": "grep", "args": "{invalid json}"},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["args"] == {}


def test_extract_unwraps_data_key() -> None:
    msg = {
        "data": {
            "tool_calls": [
                {"id": "GHT_01:s:grep:0", "name": "grep", "args": {"pattern": "foo"}},
            ],
        },
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["tool_call_id"] == "GHT_01:s:grep:0"


def test_extract_empty_name_defaults_to_tool() -> None:
    msg = {
        "tool_calls": [
            {"id": "GHT_01:s:grep:0", "name": "", "args": {"pattern": "foo"}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["name"] == "tool"


def test_extract_strips_id_whitespace() -> None:
    msg = {
        "tool_calls": [
            {"id": "  GHT_01:s:grep:0  ", "name": "grep", "args": {"pattern": "foo"}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert len(result) == 1
    assert result[0]["tool_call_id"] == "GHT_01:s:grep:0"


def test_extract_chunk_without_id_skipped() -> None:
    msg = {
        "tool_call_chunks": [
            {"name": "grep", "args": {"pattern": "foo"}},
        ],
    }
    result = extract_tool_call_updates_from_wire_message(msg)
    assert result == []
