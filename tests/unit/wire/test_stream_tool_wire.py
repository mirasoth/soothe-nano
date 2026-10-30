"""Unit tests for the `soothe.stream.tool_call.update` wire event helpers."""

from __future__ import annotations

import json

from soothe_nano.wire.stream_tool_wire import (
    STREAM_TOOL_CALL_UPDATE,
    TOOL_CALL_UPDATES_BATCH,
    extract_tool_call_updates_from_wire_message,
    tool_call_update_event,
    unified_tool_update_allowed_without_args,
)


def test_event_type_constants() -> None:
    assert STREAM_TOOL_CALL_UPDATE == "soothe.stream.tool_call.update"
    assert TOOL_CALL_UPDATES_BATCH == "tool_call_updates_batch"


def test_tool_call_update_event_normalizes_fields() -> None:
    event = tool_call_update_event(tool_call_id=" tc1 ", name=" read_file ", args={"path": "/x"})
    assert event == {
        "type": STREAM_TOOL_CALL_UPDATE,
        "tool_call_id": "tc1",
        "name": "read_file",
        "args": {"path": "/x"},
    }
    # Empty name falls back to "tool"; args defaults to {}.
    assert tool_call_update_event(tool_call_id="t", name="", args=None) == {
        "type": STREAM_TOOL_CALL_UPDATE,
        "tool_call_id": "t",
        "name": "tool",
        "args": {},
    }


def test_unified_tool_update_allowed_without_args() -> None:
    assert unified_tool_update_allowed_without_args("GHT_01:s:grep:0")
    assert unified_tool_update_allowed_without_args("GHT_01:t2:grep:3")
    assert not unified_tool_update_allowed_without_args("GHT_01:s:task:0")
    assert not unified_tool_update_allowed_without_args("GHT_01:t1:task:0")
    # Raw provider ids require parsed args before batching.
    assert not unified_tool_update_allowed_without_args("grep:0")
    assert not unified_tool_update_allowed_without_args("")
    assert not unified_tool_update_allowed_without_args("GHT_01:x:grep:0")


def test_extract_from_tool_calls_dict_args() -> None:
    msg = {"tool_calls": [{"id": "a", "name": "read_file", "args": {"path": "/x"}}]}
    updates = extract_tool_call_updates_from_wire_message(msg)
    assert len(updates) == 1
    assert updates[0]["tool_call_id"] == "a"
    assert updates[0]["name"] == "read_file"
    assert updates[0]["args"] == {"path": "/x"}
    assert updates[0]["type"] == STREAM_TOOL_CALL_UPDATE


def test_extract_parses_json_string_args_and_input_fallback() -> None:
    msg = {
        "tool_calls": [
            {"id": "b", "name": "write_file", "args": json.dumps({"p": 1})},
            {"id": "c", "name": "run_command", "input": {"cmd": "ls"}},
        ]
    }
    updates = extract_tool_call_updates_from_wire_message(msg)
    assert {u["tool_call_id"]: u["args"] for u in updates} == {
        "b": {"p": 1},
        "c": {"cmd": "ls"},
    }


def test_extract_skips_unparseable_args_raw_ids() -> None:
    msg = {"tool_calls": [{"id": "d", "name": "write_file", "args": "{not json"}]}
    assert extract_tool_call_updates_from_wire_message(msg) == []


def test_extract_allows_empty_args_for_unified_non_task_ids() -> None:
    msg = {"tool_calls": [{"id": "GHT_01:s:grep:0", "name": "grep", "args": {}}]}
    updates = extract_tool_call_updates_from_wire_message(msg)
    assert len(updates) == 1
    assert updates[0]["args"] == {}
    # Task rows are excluded; they are ingested via dedicated paths.
    msg_task = {"tool_calls": [{"id": "GHT_01:s:task:0", "name": "task", "args": {}}]}
    assert extract_tool_call_updates_from_wire_message(msg_task) == []


def test_extract_from_tool_call_chunks() -> None:
    msg = {"tool_call_chunks": [{"id": "e", "name": "read_file", "args": json.dumps({"x": True})}]}
    updates = extract_tool_call_updates_from_wire_message(msg)
    assert len(updates) == 1
    assert updates[0]["tool_call_id"] == "e"
    assert updates[0]["args"] == {"x": True}


def test_extract_dedupes_across_calls_and_chunks() -> None:
    msg = {
        "tool_calls": [{"id": "f", "name": "read_file", "args": {"a": 1}}],
        "tool_call_chunks": [{"id": "f", "name": "read_file", "args": {"b": 2}}],
    }
    updates = extract_tool_call_updates_from_wire_message(msg)
    assert len(updates) == 1
    # First sighting wins.
    assert updates[0]["args"] == {"a": 1}


def test_extract_unwraps_data_body_and_rejects_non_dict() -> None:
    msg = {"data": {"tool_calls": [{"id": "g", "name": "", "args": {"k": "v"}}]}}
    updates = extract_tool_call_updates_from_wire_message(msg)
    assert len(updates) == 1
    # Empty name falls back to "tool".
    assert updates[0]["name"] == "tool"
    assert extract_tool_call_updates_from_wire_message("nope") == []  # type: ignore[arg-type]
    assert extract_tool_call_updates_from_wire_message({}) == []


def test_tool_call_update_event_partial_flag_is_opt_in() -> None:
    """``partial`` only appears when True — complete events stay byte-identical."""
    complete = tool_call_update_event(tool_call_id="tc1", name="read_file", args={"path": "/x"})
    assert complete == {
        "type": STREAM_TOOL_CALL_UPDATE,
        "tool_call_id": "tc1",
        "name": "read_file",
        "args": {"path": "/x"},
    }
    partial = tool_call_update_event(
        tool_call_id="tc1", name="read_file", args={"path": "/x"}, partial=True
    )
    assert partial == {
        "type": STREAM_TOOL_CALL_UPDATE,
        "tool_call_id": "tc1",
        "name": "read_file",
        "args": {"path": "/x"},
        "partial": True,
    }
