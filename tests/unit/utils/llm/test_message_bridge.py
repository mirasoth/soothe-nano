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
