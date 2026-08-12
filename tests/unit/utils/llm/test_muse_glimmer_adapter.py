"""Tests for the Muse-Glimmer response adapter.

The ``Muse-Glimmer-30B-4bit`` model served by the oMLX endpoint emits an
internal self-talk protocol as raw ``content`` text and embeds tool calls as
``<atem:function_calls>`` XML (never structured ``tool_calls``). These tests
pin the adapter that converts that wire shape into clean ``content`` +
structured ``tool_calls``.

The fixtures below are real (slightly trimmed) captured responses from the
live omlx server, so regressions in marker parsing show up clearly.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from soothe_nano.utils.llm.muse_glimmer import (
    build_tool_calls_for_message,
    detect_muse_glimmer_protocol,
    extract_user_reply,
    parse_atem_tool_calls,
    transform_muse_glimmer_message,
)
from soothe_nano.utils.llm.wrappers import (
    OpenAICompatModelWrapper,
    _build_muse_glimmer_synthesized_chunk,
)

# --- captured protocol samples ---------------------------------------------

PROSE_CONTENT = (
    "to=self<|message|>In one short sentence, what is a firewall?\n\n"
    "We need one short sentence. Probably definition.\n\n"
    "Final.<|eom|><|start|>assistant to=user<|message|>"
    "A firewall is a security system that filters and monitors network "
    "traffic to block unauthorized access."
)

TOOL_CONTENT = (
    "to=self<|message|>What is 2+2? Use the calculator tool.\n\n"
    'We need to use calculator tool. So call calculator with expression "2+2".'
    "<|eom|><|start|>assistant to=calculator<|message|>"
    "<atem:function_calls>\n"
    '<atem:invoke name="calculator">\n'
    '<atem:parameter name="expression">2+2</atem:parameter>\n'
    "</atem:invoke>\n"
    "</atem:function_calls>"
)

MULTI_TOOL_CONTENT = (
    "to=self<|message|>Use both.<|eom|>"
    "<|start|>assistant to=calculator<|message|>"
    "<atem:function_calls>\n"
    '<atem:invoke name="calculator">\n'
    '<atem:parameter name="expression">3*7</atem:parameter>\n'
    "</atem:invoke>\n"
    '<atem:invoke name="clock">\n'
    '<atem:parameter name="timezone">UTC</atem:parameter>\n'
    "</atem:invoke>\n"
    "</atem:function_calls>"
)

# Agentic dialects seen when the model is given tools via bind_tools rather
# than the OpenAI ``tools`` API param. The model is inconsistent — it picks
# among these forms turn-by-turn — so the adapter must handle all of them.

SELF_NAMED_CONTENT = (
    "to=self<|message|>Read the file.<|eom|>"
    "<|start|>assistant to=read_file<|message|>"
    '<read_file file_path="/path/to/nano.yml"></read_file>'
)

FUNCTION_ARG_CONTENT = (
    "to=self<|message|>Read the file.<|eom|>"
    "<|start|>assistant to=read_file<|message|>"
    '<function name="read_file">\n'
    '<arg name="file_path">/path/to/nano.yml</arg>\n'
    "</function></atem:assistant>"
)

FUNCTION_CALL_SELF_CLOSING_CONTENT = (
    "to=self<|message|>Read the file.<|eom|>"
    "<|start|>assistant to=read_file<|message|>"
    '<function_call name="read_file" file_path="/path/to/nano.yml"/>'
)

FUNCTION_CALL_CHILDREN_CONTENT = (
    "to=self<|message|>Read the file.<|eom|>"
    "<|start|>assistant to=read_file<|message|>"
    '<function_call name="read_file">\n'
    '<arg name="file_path">/path/to/nano.yml</arg>\n'
    "</function_call>"
)

# Dialect where the whole arg dict is serialized into a single ``args``
# attribute (Python-dict-repr). Seen with run_command / shell tools.
ARGS_ATTR_CONTENT = (
    "to=self<|message|>Run it.<|eom|>"
    "<|start|>assistant to=run_command<|message|>"
    "<run_command args=\"{'command': 'echo hello'}\"/>"
)

# Dialect 4: <atem:TOOLNAME>{json args}</atem:TOOLNAME>
ATEM_TOOL_BLOCK_CONTENT = (
    "to=self<|message|>Run it.<|eom|>"
    "<|start|>assistant to=run_command<|message|>"
    '<atem:run_command>{"args": "echo hello > ./out.txt"}</atem:run_command>'
)

MIXED_CONTENT = (
    "to=self<|message|>Let me compute.<|eom|>"
    "<|start|>assistant to=user<|message|>Computing 2+2 now."
    "<|eom|><|start|>assistant to=calculator<|message|>"
    "<atem:function_calls>\n"
    '<atem:invoke name="calculator">\n'
    '<atem:parameter name="expression">2+2</atem:parameter>\n'
    "</atem:invoke>\n"
    "</atem:function_calls>"
)

TRUNCATED_NO_REPLY = (
    "to=self<|message|>Hmm, what is a firewall?\n\n"
    "Let me think about the definition. Probably a security system. "
    "I should output one sentence. But I am running out of"
)


# --- detect_muse_glimmer_protocol ------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PROSE_CONTENT, True),
        (TOOL_CONTENT, True),
        ("plain answer with no markers", False),
        ("", False),
        ("to=self something", True),
        ('<atem:invoke name="x">', True),
    ],
)
def test_detect_muse_glimmer_protocol(text: str, expected: bool) -> None:
    assert detect_muse_glimmer_protocol(text) is expected


# --- extract_user_reply ----------------------------------------------------


def test_extract_user_reply_returns_tail_after_final_marker() -> None:
    reply = extract_user_reply(PROSE_CONTENT)
    assert reply == (
        "A firewall is a security system that filters and monitors network "
        "traffic to block unauthorized access."
    )


def test_extract_user_reply_no_marker_returns_original() -> None:
    # Safe fallback: truncated self-talk with no to=user yields the original
    # so the caller still sees something rather than an empty string.
    assert extract_user_reply(TRUNCATED_NO_REPLY) == TRUNCATED_NO_REPLY


def test_extract_user_reply_empty() -> None:
    assert extract_user_reply("") == ""


# --- parse_atem_tool_calls -------------------------------------------------


def test_parse_atem_tool_calls_single() -> None:
    calls = parse_atem_tool_calls(TOOL_CONTENT)
    assert len(calls) == 1
    assert calls[0]["name"] == "calculator"
    assert calls[0]["args"] == {"expression": "2+2"}
    assert "<atem:invoke" in calls[0]["raw_text"]


def test_parse_atem_tool_calls_multiple() -> None:
    calls = parse_atem_tool_calls(MULTI_TOOL_CONTENT)
    assert [c["name"] for c in calls] == ["calculator", "clock"]
    assert calls[0]["args"] == {"expression": "3*7"}
    assert calls[1]["args"] == {"timezone": "UTC"}


def test_parse_atem_tool_calls_empty_text() -> None:
    assert parse_atem_tool_calls("") == []
    assert parse_atem_tool_calls("no xml here") == []


def test_parse_self_named_element_dialect() -> None:
    calls = parse_atem_tool_calls(SELF_NAMED_CONTENT)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"
    assert calls[0]["args"] == {"file_path": "/path/to/nano.yml"}


def test_parse_function_arg_dialect() -> None:
    calls = parse_atem_tool_calls(FUNCTION_ARG_CONTENT)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"
    assert calls[0]["args"] == {"file_path": "/path/to/nano.yml"}


def test_parse_function_call_self_closing_dialect() -> None:
    calls = parse_atem_tool_calls(FUNCTION_CALL_SELF_CLOSING_CONTENT)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"
    assert calls[0]["args"] == {"file_path": "/path/to/nano.yml"}


def test_parse_function_call_children_dialect() -> None:
    calls = parse_atem_tool_calls(FUNCTION_CALL_CHILDREN_CONTENT)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"
    assert calls[0]["args"] == {"file_path": "/path/to/nano.yml"}


def test_parse_args_attr_dialect_unpacks_dict_repr() -> None:
    """A single ``args="{'k': 'v'}"`` attribute must unpack into real args."""
    calls = parse_atem_tool_calls(ARGS_ATTR_CONTENT)
    assert len(calls) == 1
    assert calls[0]["name"] == "run_command"
    assert calls[0]["args"] == {"command": "echo hello"}


def test_parse_atem_tool_block_dialect() -> None:
    """``<atem:TOOLNAME>{json}</atem:TOOLNAME>`` must surface as a tool call."""
    calls = parse_atem_tool_calls(ATEM_TOOL_BLOCK_CONTENT)
    assert len(calls) == 1
    assert calls[0]["name"] == "run_command"
    # JSON body parsed; "args" stays as-is (the model's serialization is lossy
    # here, but the tool name is correctly extracted).
    assert "args" in calls[0]["args"]


def test_transform_each_dialect_yields_structured_tool_call() -> None:
    """Every agentic dialect must surface as a read_file tool_call."""
    for label, content in [
        ("self-named", SELF_NAMED_CONTENT),
        ("function/arg", FUNCTION_ARG_CONTENT),
        ("function_call self-closing", FUNCTION_CALL_SELF_CLOSING_CONTENT),
        ("function_call children", FUNCTION_CALL_CHILDREN_CONTENT),
    ]:
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.content == "", f"{label}: content not empty: {msg.content!r}"
        assert len(msg.tool_calls) == 1, f"{label}: expected 1 tool_call"
        assert msg.tool_calls[0]["name"] == "read_file", f"{label}: wrong name"
        assert msg.tool_calls[0]["args"] == {"file_path": "/path/to/nano.yml"}, (
            f"{label}: wrong args: {msg.tool_calls[0]['args']!r}"
        )


def test_parse_atem_tool_calls_value_with_xml_chars() -> None:
    text = (
        "<atem:function_calls>"
        '<atem:invoke name="run">'
        '<atem:parameter name="code">print("<b>")</atem:parameter>'
        "</atem:invoke>"
        "</atem:function_calls>"
    )
    calls = parse_atem_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["args"] == {"code": 'print("<b>")'}


# --- build_tool_calls_for_message (id determinism) ------------------------


def test_build_tool_calls_ids_are_deterministic() -> None:
    a = build_tool_calls_for_message(TOOL_CONTENT)
    b = build_tool_calls_for_message(TOOL_CONTENT)
    assert a == b
    assert a[0]["id"].startswith("musegl_0_")
    # Different tool args -> different id.
    other = build_tool_calls_for_message(MULTI_TOOL_CONTENT)
    assert other[0]["id"] != a[0]["id"]


# --- transform_muse_glimmer_message ----------------------------------------


def test_transform_prose_strips_self_talk_keeps_reply() -> None:
    msg = AIMessage(content=PROSE_CONTENT)
    transform_muse_glimmer_message(msg)
    assert msg.content == (
        "A firewall is a security system that filters and monitors network "
        "traffic to block unauthorized access."
    )
    assert msg.tool_calls == []


def test_transform_tool_call_populates_tool_calls_empties_content() -> None:
    msg = AIMessage(content=TOOL_CONTENT)
    transform_muse_glimmer_message(msg)
    assert msg.content == ""
    assert len(msg.tool_calls) == 1
    tc = msg.tool_calls[0]
    assert tc["name"] == "calculator"
    assert tc["args"] == {"expression": "2+2"}
    assert tc["id"].startswith("musegl_0_")


def test_transform_tool_call_mirrors_tool_call_chunks() -> None:
    msg = AIMessage(content=TOOL_CONTENT)
    transform_muse_glimmer_message(msg)
    assert len(msg.tool_call_chunks) == 1
    chunk = msg.tool_call_chunks[0]
    assert chunk["index"] == 0
    assert chunk["name"] == "calculator"
    assert chunk["args"] == '{"expression": "2+2"}'
    assert chunk["id"] == msg.tool_calls[0]["id"]


def test_transform_multi_tool() -> None:
    msg = AIMessage(content=MULTI_TOOL_CONTENT)
    transform_muse_glimmer_message(msg)
    assert msg.content == ""
    assert [c["name"] for c in msg.tool_calls] == ["calculator", "clock"]
    assert msg.tool_calls[0]["args"] == {"expression": "3*7"}
    assert msg.tool_calls[1]["args"] == {"timezone": "UTC"}
    # chunks indexed in order
    assert [c["index"] for c in msg.tool_call_chunks] == [0, 1]


def test_transform_mixed_reply_and_tool_call() -> None:
    msg = AIMessage(content=MIXED_CONTENT)
    transform_muse_glimmer_message(msg)
    assert msg.content == "Computing 2+2 now."
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0]["name"] == "calculator"


def test_transform_passthrough_for_non_muse_content() -> None:
    original = "just a normal answer with no protocol markers"
    msg = AIMessage(content=original)
    transform_muse_glimmer_message(msg)
    assert msg.content == original
    assert msg.tool_calls == []


def test_transform_truncated_self_talk_returns_original_content() -> None:
    msg = AIMessage(content=TRUNCATED_NO_REPLY)
    transform_muse_glimmer_message(msg)
    # No to=user marker and no tool XML: content is returned (possibly with
    # scaffolding stripped, but here there is none to strip).
    assert "firewall" in msg.content
    assert msg.tool_calls == []


def test_transform_handles_none_and_non_str_content() -> None:
    assert transform_muse_glimmer_message(None) is None
    msg = AIMessage(content="")
    out = transform_muse_glimmer_message(msg)
    assert out is msg
    assert msg.content == ""


# --- wrapper-level (OpenAICompatModelWrapper) -------------------------------


def _fake_model_returning(content: str) -> Any:
    """Build a fake inner model whose _generate returns one AIMessage."""
    from unittest.mock import MagicMock

    from langchain_core.outputs import ChatGeneration, ChatResult

    result = ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])
    model = MagicMock()
    model._generate.return_value = result
    model._llm_type = "fake"
    model._identifying_params = {}
    model._model_name = "fake"
    return model


def test_wrapper_generate_prose_clean_content() -> None:
    model = _fake_model_returning(PROSE_CONTENT)
    wrapper = OpenAICompatModelWrapper(model, "omlx", muse_glimmer=True)
    result = wrapper._generate(messages=[], stop=None, run_manager=None)
    msg = result.generations[0].message
    assert "to=self" not in msg.content
    assert "<|eom|>" not in msg.content
    assert msg.content.startswith("A firewall is a security system")
    assert msg.tool_calls == []


def test_wrapper_generate_tool_call_structured() -> None:
    model = _fake_model_returning(TOOL_CONTENT)
    wrapper = OpenAICompatModelWrapper(model, "omlx", muse_glimmer=True)
    result = wrapper._generate(messages=[], stop=None, run_manager=None)
    msg = result.generations[0].message
    assert msg.content == ""
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0]["name"] == "calculator"
    assert msg.tool_calls[0]["args"] == {"expression": "2+2"}


def test_wrapper_default_muse_glimmer_false_passthrough_thinking() -> None:
    """Without muse_glimmer, the wrapper must NOT run the adapter."""
    model = _fake_model_returning(TOOL_CONTENT)
    wrapper = OpenAICompatModelWrapper(model, "omlx")  # muse_glimmer defaults False
    result = wrapper._generate(messages=[], stop=None, run_manager=None)
    msg = result.generations[0].message
    # Untouched: tool_calls still empty, raw content preserved.
    assert msg.tool_calls == []
    assert "to=self" in msg.content


# --- streaming synthesis ----------------------------------------------------


def test_build_muse_glimmer_synthesized_chunk_prose() -> None:
    chunk = _build_muse_glimmer_synthesized_chunk(PROSE_CONTENT)
    msg = chunk.message
    assert msg.content.startswith("A firewall is a security system")
    assert msg.tool_calls == []


def test_build_muse_glimmer_synthesized_chunk_tool_call() -> None:
    chunk = _build_muse_glimmer_synthesized_chunk(TOOL_CONTENT)
    msg = chunk.message
    assert msg.content == ""
    assert len(msg.tool_calls) == 1
    assert len(msg.tool_call_chunks) == 1
    assert msg.tool_call_chunks[0]["name"] == "calculator"


def test_wrapper_astream_buffers_and_emits_single_transformed_chunk() -> None:
    """Muse-Glimmer streaming buffers deltas then emits one clean chunk."""
    import asyncio

    async def _astream(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Stream the prose content in small deltas (mimics the live server).
        for i in range(0, len(PROSE_CONTENT), 7):
            yield _text_chunk(PROSE_CONTENT[i : i + 7])

    from unittest.mock import MagicMock

    model = MagicMock()
    model._astream = _astream
    model._llm_type = "fake"
    model._identifying_params = {}
    model._model_name = "fake"

    wrapper = OpenAICompatModelWrapper(model, "omlx", muse_glimmer=True)

    async def _drain() -> list[Any]:
        out: list[Any] = []
        async for chunk in wrapper._astream(messages=[], stop=None, run_manager=None):  # noqa: SLF001
            out.append(chunk)
        return out

    chunks = asyncio.new_event_loop().run_until_complete(_drain())
    # Exactly one transformed chunk (buffered), carrying clean content.
    assert len(chunks) == 1
    msg = chunks[0].message
    assert "to=self" not in msg.content
    assert msg.content.startswith("A firewall is a security system")
    assert msg.tool_calls == []


def _text_chunk(text: str) -> Any:
    """Build a minimal ChatGenerationChunk carrying a text delta."""
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk

    return ChatGenerationChunk(message=AIMessageChunk(content=text))


def test_wrapper_astream_tool_call_emits_structured_chunk() -> None:
    """A streamed tool-call turn becomes one chunk with tool_calls."""
    import asyncio

    async def _astream(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        for i in range(0, len(TOOL_CONTENT), 11):
            yield _text_chunk(TOOL_CONTENT[i : i + 11])

    from unittest.mock import MagicMock

    model = MagicMock()
    model._astream = _astream
    model._llm_type = "fake"
    model._identifying_params = {}
    model._model_name = "fake"

    wrapper = OpenAICompatModelWrapper(model, "omlx", muse_glimmer=True)

    async def _drain() -> list[Any]:
        out: list[Any] = []
        async for chunk in wrapper._astream(messages=[], stop=None, run_manager=None):  # noqa: SLF001
            out.append(chunk)
        return out

    chunks = asyncio.new_event_loop().run_until_complete(_drain())
    assert len(chunks) == 1
    msg = chunks[0].message
    assert msg.content == ""
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0]["name"] == "calculator"
