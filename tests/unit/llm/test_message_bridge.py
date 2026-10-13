"""Tests for the langchain <-> litellm message bridges in :mod:`soothe_nano.llm.message`.

Covers the dict-tolerance fix for ``lc_to_litellm_messages``: callers like the
planner engine (``soothe_nano.subagents.plan.engine``) build message lists as
plain ``{"role", "content"}`` dicts rather than ``BaseMessage`` objects, and
LangChain's structured-output runnable passes them through to the provider's
``_agenerate`` uncoerced. The converter must handle dicts instead of raising
``AttributeError: 'dict' object has no attribute 'type'``.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from soothe_nano.llm.message import lc_to_litellm_messages


def test_dict_messages_pass_through_with_normalized_roles() -> None:
    """Plain dict messages (planner engine shape) convert to litellm form.

    Reproduces the deployed planner draft failure: dict messages reached
    ``lc_to_litellm_messages`` and ``m.type`` raised AttributeError.
    """
    messages = [
        {"role": "system", "content": "you are a planner"},
        {"role": "user", "content": "draft a solution report"},
    ]
    out = lc_to_litellm_messages(messages)
    assert out == [
        {"role": "system", "content": "you are a planner"},
        {"role": "user", "content": "draft a solution report"},
    ]


def test_dict_message_role_aliases_normalized() -> None:
    """OpenAI/litellm aliases ('human'/'ai') in dicts map to user/assistant."""
    messages = [
        {"role": "human", "content": "hi"},
        {"role": "ai", "content": "hello"},
    ]
    out = lc_to_litellm_messages(messages)
    assert [m["role"] for m in out] == ["user", "assistant"]


def test_dict_message_preserves_tool_fields() -> None:
    """A dict tool-response message keeps tool_call_id and role=tool."""
    messages = [
        {
            "role": "tool",
            "content": "42",
            "tool_call_id": "call_1",
        }
    ]
    out = lc_to_litellm_messages(messages)
    assert out[0]["role"] == "tool"
    assert out[0]["tool_call_id"] == "call_1"
    assert out[0]["content"] == "42"


def test_dict_message_coerces_non_string_content() -> None:
    """Non-string content (e.g. list blocks) is stringified, not passed raw."""
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    out = lc_to_litellm_messages(messages)
    assert out[0]["role"] == "user"
    assert isinstance(out[0]["content"], str)


def test_dict_message_with_missing_content_defaults_to_empty() -> None:
    """A dict lacking 'content' (None) becomes an empty string, not KeyError."""
    out = lc_to_litellm_messages([{"role": "user"}])
    assert out == [{"role": "user", "content": ""}]


def test_langchain_base_messages_still_convert_identically() -> None:
    """Regression guard: the BaseMessage path is unchanged by the dict fix."""
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        AIMessage(
            content="hello",
            tool_calls=[{"name": "do", "args": {"x": 1}, "id": "t1", "type": "tool_call"}],
        ),
        ToolMessage(content="42", tool_call_id="t1"),
    ]
    out = lc_to_litellm_messages(messages)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "hi"}
    assert out[2]["role"] == "assistant"
    assert out[2]["tool_calls"] == [
        {"id": "t1", "type": "function", "function": {"name": "do", "arguments": '{"x": 1}'}}
    ]
    assert out[3]["role"] == "tool"
    assert out[3]["tool_call_id"] == "t1"


def test_mixed_dict_and_base_messages() -> None:
    """A list mixing dicts and BaseMessage objects converts without raising."""
    messages = [
        {"role": "system", "content": "sys"},
        HumanMessage(content="hi"),
    ]
    out = lc_to_litellm_messages(messages)
    assert [m["role"] for m in out] == ["system", "user"]
    assert out[0]["content"] == "sys"
    assert out[1]["content"] == "hi"


# ==============================================================================
# Sanitization: drop tool_calls with missing/empty function.name (avoids 400)
# ==============================================================================
# Providers reject ``tool_calls[i].function missing required field "name"`` with
# a non-retriable 400 invalid_request_error. ``lc_to_litellm_messages`` must drop
# such malformed entries instead of emitting them. See deployed fjf failure:
# ``messages[400].tool_calls[0].function missing required field "name"``.


def test_basemessage_tool_call_with_empty_name_is_dropped() -> None:
    """An AIMessage tool_call whose 'name' is '' must not be emitted as-is.

    Reproduces the 400: ``tc.get("name", "")`` previously produced
    ``{"function": {"name": "", ...}}`` which providers reject.
    """
    messages = [
        AIMessage(
            content="ok",
            tool_calls=[{"name": "", "args": {"x": 1}, "id": "t1", "type": "tool_call"}],
        )
    ]
    out = lc_to_litellm_messages(messages)
    # The malformed tool_call is dropped; entry keeps content/role but no tool_calls.
    assert out[0]["role"] == "assistant"
    assert "tool_calls" not in out[0]


def test_basemessage_drops_only_malformed_tool_calls_keeps_valid_ones() -> None:
    """A mix of valid and malformed tool_calls keeps the valid ones."""
    messages = [
        AIMessage(
            content="ok",
            tool_calls=[
                {"name": "", "args": {}, "id": "bad", "type": "tool_call"},
                {"name": "read_file", "args": {"p": "x"}, "id": "good", "type": "tool_call"},
            ],
        )
    ]
    out = lc_to_litellm_messages(messages)
    tcs = out[0]["tool_calls"]
    assert len(tcs) == 1
    assert tcs[0]["function"]["name"] == "read_file"
    assert tcs[0]["id"] == "good"


def test_dict_passthrough_tool_call_missing_function_name_is_dropped() -> None:
    """A dict message with a tool_call whose function has no 'name' is dropped.

    Reproduces the exact deployed failure: dict passthrough previously emitted
    ``{"function": {"arguments": "{}"}}`` with no ``name`` key, triggering
    ``tool_calls[0].function missing required field "name"``.
    """
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "3", "type": "function", "function": {"arguments": "{}"}},
            ],
        }
    ]
    out = lc_to_litellm_messages(messages)
    assert out[0]["role"] == "assistant"
    assert "tool_calls" not in out[0]


def test_dict_passthrough_tool_call_with_empty_name_is_dropped() -> None:
    """A dict tool_call with function.name == '' is dropped."""
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "4", "type": "function", "function": {"name": "", "arguments": "{}"}},
            ],
        }
    ]
    out = lc_to_litellm_messages(messages)
    assert "tool_calls" not in out[0]


def test_dict_passthrough_keeps_valid_tool_calls_among_malformed() -> None:
    """Dict passthrough drops only malformed tool_calls, keeps valid ones."""
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "bad", "type": "function", "function": {"arguments": "{}"}},
                {
                    "id": "good",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                },
            ],
        }
    ]
    out = lc_to_litellm_messages(messages)
    tcs = out[0]["tool_calls"]
    assert len(tcs) == 1
    assert tcs[0]["function"]["name"] == "search"
    assert tcs[0]["id"] == "good"


def test_dict_passthrough_tool_call_missing_name_key_is_dropped() -> None:
    """A dict tool_call whose function has no 'name' key at all is dropped.

    The BaseMessage path cannot reach this state — langchain's AIMessage
    validator rejects constructing a tool_call without 'name' — but the dict
    passthrough path (planner engine / hand-built messages) can and does.
    """
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "5", "type": "function", "function": {"arguments": "{}"}},
            ],
        }
    ]
    out = lc_to_litellm_messages(messages)
    assert "tool_calls" not in out[0]
