"""Tests for the Muse-Glimmer response adapter (``muse_glimmer.py``).

These tests drive the shipped pure-transform functions against realistic
Muse-Glimmer wire samples captured from the vLLM-Metal server on
``localhost:9543``. The model emits an internal self-talk protocol
(``to=self<|message|>...<|eom|>``, ``to=user<|message|>``) and embeds tool
calls as XML-in-content in several dialects. The adapter must:

- detect the protocol markers and repetition loops
- parse all tool-call dialects into structured dicts
- strip self-talk, tool XML, and repetition echoes from visible content
- map positional JSON-array args to keyword names via ``tool_param_order``
- leave non-Muse-Glimmer messages untouched

The vLLM 422 fix (empty content -> " " when tool_calls present) is tested
via :func:`_apply_protocol_adapter_to_chat_result`.
"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage

from soothe_nano.utils.llm.muse_glimmer import (
    build_tool_calls_for_message,
    detect_muse_glimmer_protocol,
    detect_muse_glimmer_repetition,
    extract_user_reply,
    parse_atem_tool_calls,
    strip_repetition_loop,
    transform_muse_glimmer_message,
)
from soothe_nano.utils.llm.wrappers import _apply_protocol_adapter_to_chat_result


class TestDetectProtocol:
    def test_detects_message_marker(self) -> None:
        assert detect_muse_glimmer_protocol("to=self<|message|>thinking...<|eom|>")

    def test_detects_eom_marker(self) -> None:
        assert detect_muse_glimmer_protocol("some text<|eom|>")

    def test_detects_atem_tag(self) -> None:
        assert detect_muse_glimmer_protocol("<atem:function_calls>stuff</atem:function_calls>")

    def test_detects_to_user(self) -> None:
        assert detect_muse_glimmer_protocol("to=user<|message|>reply")

    def test_negative_plain_text(self) -> None:
        assert not detect_muse_glimmer_protocol("Just a normal response.")

    def test_negative_empty(self) -> None:
        assert not detect_muse_glimmer_protocol("")


class TestDetectRepetition:
    def test_detects_loop_after_answer(self) -> None:
        text = "2+2 equals 4.\n\nUser: What is 2+2?\nAssistant: 2+2 equals 4."
        idx = detect_muse_glimmer_repetition(text)
        assert idx > 0
        assert "2+2 equals 4." in text[:idx]

    def test_no_loop_plain_text(self) -> None:
        assert detect_muse_glimmer_repetition("Just a normal response.") == -1

    def test_no_loop_single_answer_only(self) -> None:
        # A single answer with no further User:/Assistant: turns is not a loop.
        text = "The answer is 4. Here is some explanation."
        assert detect_muse_glimmer_repetition(text) == -1

    def test_empty(self) -> None:
        assert detect_muse_glimmer_repetition("") == -1


class TestStripRepetition:
    def test_cuts_loop(self) -> None:
        text = "The answer is 4.\n\nUser: What is it?\nAssistant: 4."
        result = strip_repetition_loop(text)
        assert result == "The answer is 4."

    def test_no_loop_unchanged(self) -> None:
        text = "Just a normal response."
        assert strip_repetition_loop(text) == text


class TestExtractUserReply:
    def test_extracts_after_final_to_user(self) -> None:
        text = "to=self<|message|>thinking<|eom|>to=user<|message|>Hello."
        assert extract_user_reply(text) == "Hello."

    def test_no_marker_returns_original(self) -> None:
        text = "Just a normal response."
        assert extract_user_reply(text) == text

    def test_empty(self) -> None:
        assert extract_user_reply("") == ""


# --- parse_atem_tool_calls dialect tests ---


class TestParseDialect1AtemInvoke:
    def test_single_invoke(self) -> None:
        text = (
            "<atem:function_calls>"
            '<atem:invoke name="calculator">'
            '<atem:parameter name="expression">2+2</atem:parameter>'
            "</atem:invoke>"
            "</atem:function_calls>"
        )
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "calculator"
        assert calls[0]["args"] == {"expression": "2+2"}

    def test_multiple_invokes(self) -> None:
        text = (
            "<atem:function_calls>"
            '<atem:invoke name="read_file">'
            '<atem:parameter name="file_path">/a</atem:parameter>'
            "</atem:invoke>"
            '<atem:invoke name="read_file">'
            '<atem:parameter name="file_path">/b</atem:parameter>'
            "</atem:invoke>"
            "</atem:function_calls>"
        )
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["args"]["file_path"] == "/a"
        assert calls[1]["args"]["file_path"] == "/b"


class TestParseDialect2FunctionBlock:
    def test_function_with_arg(self) -> None:
        text = '<function name="read_file"><arg name="file_path">/x</arg></function>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["args"] == {"file_path": "/x"}

    def test_function_call_variant(self) -> None:
        text = '<function_call name="ls"><arg name="path">/tmp</arg></function_call>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"

    def test_tool_variant(self) -> None:
        text = '<tool name="ls"><arg name="path">/tmp</arg></tool>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"

    def test_parameter_tag_variant(self) -> None:
        text = '<function name="read_file"><parameter name="file_path">/x</parameter></function>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["args"] == {"file_path": "/x"}

    def test_argument_tag_variant(self) -> None:
        text = '<tool name="write_file"><argument name="file_path">/y</argument></tool>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["args"] == {"file_path": "/y"}


class TestParseDialect2bFunctionAttr:
    def test_self_closing_function_call_attr(self) -> None:
        text = '<function_call name="read_file" file_path="/x" />'
        calls = parse_atem_tool_calls(text)
        found = [c for c in calls if c["name"] == "read_file"]
        assert found
        assert found[0]["args"] == {"file_path": "/x"}


class TestParseDialect3SelfNamed:
    def test_self_closing(self) -> None:
        text = '<read_file file_path="/x"/>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["args"] == {"file_path": "/x"}

    def test_paired(self) -> None:
        text = '<read_file file_path="/y"></read_file>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["args"] == {"file_path": "/y"}

    def test_structural_tags_not_parsed_as_tools(self) -> None:
        text = '<function name="x"></function>'
        calls = parse_atem_tool_calls(text)
        assert all(c["name"] != "function" for c in calls)


class TestParseDialect4AtemToolBlock:
    def test_json_body(self) -> None:
        text = '<atem:run_command>{"args": "ls -la"}</atem:run_command>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "run_command"
        assert calls[0]["args"] == {"args": "ls -la"}

    def test_structural_atem_names_skipped(self) -> None:
        text = (
            "<atem:function_calls>"
            '<atem:invoke name="calc">'
            '<atem:parameter name="x">1</atem:parameter>'
            "</atem:invoke>"
            "</atem:function_calls>"
        )
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "calc"


class TestParseDialect5ToArgs:
    def test_json_array_positional(self) -> None:
        text = 'to=ls<|message|><args>["/tmp"]</args>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"
        assert calls[0]["args"] == {"path": "/tmp"}

    def test_json_array_with_param_order(self) -> None:
        text = 'to=ls<|message|><args>["/tmp", true]</args>'
        calls = parse_atem_tool_calls(text, tool_param_order={"ls": ["path", "include_info"]})
        assert len(calls) == 1
        assert calls[0]["args"] == {"path": "/tmp", "include_info": True}

    def test_python_single_quoted_array(self) -> None:
        text = "to=ls<|message|><args>['/tmp']</args>"
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["args"] == {"path": "/tmp"}

    def test_xml_key_value_elements(self) -> None:
        text = "to=read_file<|message|><args><file_path>/path/to/file</file_path></args>"
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["args"] == {"file_path": "/path/to/file"}

    def test_assistant_prefix_consumed(self) -> None:
        text = 'assistant to=ls<|message|><args>["/tmp"]</args>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"


class TestParseDialect5bBareParams:
    def test_bare_atem_parameters(self) -> None:
        text = 'to=read_file<|message|><atem:parameter name="file_path">/x</atem:parameter>'
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["args"] == {"file_path": "/x"}

    def test_multiple_bare_params(self) -> None:
        text = (
            "to=write_file<|message|>"
            '<atem:parameter name="file_path">/y</atem:parameter>'
            '<atem:parameter name="content">hello</atem:parameter>'
        )
        calls = parse_atem_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["args"] == {"file_path": "/y", "content": "hello"}


class TestBuildToolCalls:
    def test_returns_name_args_id(self) -> None:
        text = '<read_file file_path="/x"/>'
        calls = build_tool_calls_for_message(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["args"] == {"file_path": "/x"}
        assert calls[0]["id"].startswith("musegl_")

    def test_deterministic_ids(self) -> None:
        text = '<read_file file_path="/x"/>'
        calls_a = build_tool_calls_for_message(text)
        calls_b = build_tool_calls_for_message(text)
        assert calls_a[0]["id"] == calls_b[0]["id"]

    def test_distinct_ids_for_different_calls(self) -> None:
        text = '<read_file file_path="/a"/><read_file file_path="/b"/>'
        calls = build_tool_calls_for_message(text)
        assert len(calls) == 2
        assert calls[0]["id"] != calls[1]["id"]

    def test_threads_tool_param_order(self) -> None:
        text = 'to=ls<|message|><args>["/tmp", true]</args>'
        calls = build_tool_calls_for_message(
            text, tool_param_order={"ls": ["path", "include_info"]}
        )
        assert calls[0]["args"] == {"path": "/tmp", "include_info": True}


class TestTransformMessage:
    def test_protocol_with_tool_calls_only(self) -> None:
        content = (
            "to=self<|message|>I need to read a file<|eom|>"
            "<|start|>assistant to=read_file<|message|>"
            '<read_file file_path="/x"/>'
            "</atem:assistant>"
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.tool_calls
        assert msg.tool_calls[0]["name"] == "read_file"
        assert msg.tool_calls[0]["args"] == {"file_path": "/x"}
        assert msg.content == ""

    def test_protocol_with_user_reply(self) -> None:
        content = (
            "to=self<|message|>reasoning<|eom|>"
            "<|start|>assistant to=user<|message|>The answer is 42."
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.content == "The answer is 42."
        assert not msg.tool_calls

    def test_protocol_with_reply_and_tool_calls(self) -> None:
        content = (
            "to=self<|message|>thinking<|eom|>"
            "<|start|>assistant to=user<|message|>I'll read the file."
            " to=read_file<|message|>"
            '<read_file file_path="/x"/>'
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert "I'll read the file." in msg.content
        assert "<read_file" not in msg.content
        assert "to=" not in msg.content
        assert msg.tool_calls
        assert msg.tool_calls[0]["name"] == "read_file"

    def test_repetition_loop_cut(self) -> None:
        content = "2+2 equals 4.\n\nUser: What is 2+2?\nAssistant: 2+2 equals 4."
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.content == "2+2 equals 4."
        assert not msg.tool_calls

    def test_plain_text_unchanged(self) -> None:
        content = "This is a normal response with no protocol markers."
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.content == content
        assert not msg.tool_calls

    def test_no_leaked_tokens_in_reply(self) -> None:
        content = (
            "to=self<|message|>internal reasoning<|eom|>"
            "<|start|>assistant to=user<|message|>Hello world."
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert "to=self" not in msg.content
        assert "<|eom|>" not in msg.content
        assert "<|message|>" not in msg.content
        assert "<|start|>" not in msg.content
        assert msg.content == "Hello world."

    def test_tool_call_chunks_populated(self) -> None:
        # Content must carry protocol markers so detect_muse_glimmer_protocol
        # returns True and the tool-call parsing path is engaged.
        content = (
            "to=self<|message|>I need to read<|eom|>"
            "<|start|>assistant to=read_file<|message|>"
            '<read_file file_path="/x"/>'
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        chunks = getattr(msg, "tool_call_chunks", [])
        assert chunks
        assert chunks[0]["name"] == "read_file"
        assert chunks[0]["index"] == 0


class TestApplyToChatResult:
    def _make_result(self, content: str):
        msg = AIMessage(content=content)
        gen = SimpleNamespace(message=msg)
        return SimpleNamespace(generations=[gen])

    def test_transforms_protocol_message(self) -> None:
        result = self._make_result(
            "to=self<|message|>thinking<|eom|><|start|>assistant to=user<|message|>Done."
        )
        _apply_protocol_adapter_to_chat_result(result)
        msg = result.generations[0].message
        assert msg.content == "Done."

    def test_vllm_422_fix_empty_content_with_tool_calls(self) -> None:
        content = (
            "to=self<|message|>I need to read<|eom|>"
            "<|start|>assistant to=read_file<|message|>"
            '<read_file file_path="/x"/>'
        )
        result = self._make_result(content)
        _apply_protocol_adapter_to_chat_result(result)
        msg = result.generations[0].message
        assert msg.tool_calls
        assert msg.content == " "

    def test_plain_result_unchanged(self) -> None:
        result = self._make_result("Just a normal response.")
        _apply_protocol_adapter_to_chat_result(result)
        msg = result.generations[0].message
        assert msg.content == "Just a normal response."
        assert not msg.tool_calls

    def test_none_result_passthrough(self) -> None:
        assert _apply_protocol_adapter_to_chat_result(None) is None

    def test_empty_generations_passthrough(self) -> None:
        result = SimpleNamespace(generations=[])
        assert _apply_protocol_adapter_to_chat_result(result) is result


class TestWireSamples:
    def test_simple_reply_wire_sample(self) -> None:
        content = (
            "to=self<|message|>"
            "The user is asking about 2+2. This is simple arithmetic. "
            "The answer is 4."
            "<|eom|>"
            "<|start|>assistant to=user<|message|>"
            "2+2 equals 4."
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.content == "2+2 equals 4."
        assert "to=self" not in msg.content
        assert "<|eom|>" not in msg.content
        assert not msg.tool_calls

    def test_tool_call_wire_sample_dialect3(self) -> None:
        content = (
            "to=self<|message|>"
            "The user wants me to read a file. I'll use read_file."
            "<|eom|>"
            "<|start|>assistant to=read_file<|message|>"
            '<read_file file_path="/Users/test/LICENSE"/>'
            "</atem:assistant>"
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.tool_calls
        assert msg.tool_calls[0]["name"] == "read_file"
        assert msg.tool_calls[0]["args"]["file_path"] == "/Users/test/LICENSE"
        assert msg.content == ""

    def test_tool_call_wire_sample_dialect2(self) -> None:
        content = (
            "to=self<|message|>"
            "I need to read the LICENSE file."
            "<|eom|>"
            "<|start|>assistant to=read_file<|message|>"
            '<function name="read_file">'
            '<arg name="file_path">/Users/test/MIT</arg>'
            "</function>"
            "</atem:assistant>"
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.tool_calls
        assert msg.tool_calls[0]["name"] == "read_file"
        assert msg.tool_calls[0]["args"]["file_path"] == "/Users/test/MIT"

    def test_tool_call_wire_sample_dialect5_json(self) -> None:
        content = (
            "to=self<|message|>"
            "I'll list the directory."
            "<|eom|>"
            '<|start|>assistant to=ls<|message|><args>["/tmp"]</args>'
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.tool_calls
        assert msg.tool_calls[0]["name"] == "ls"
        assert msg.tool_calls[0]["args"]["path"] == "/tmp"

    def test_tool_call_wire_sample_dialect5_xml(self) -> None:
        content = (
            "to=self<|message|>"
            "I'll read the file."
            "<|eom|>"
            "<|start|>assistant to=read_file<|message|><args>"
            "<file_path>/etc/hosts</file_path>"
            "</args>"
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.tool_calls
        assert msg.tool_calls[0]["name"] == "read_file"
        assert msg.tool_calls[0]["args"]["file_path"] == "/etc/hosts"

    def test_repetition_loop_wire_sample(self) -> None:
        content = (
            "The capital of France is Paris.\n\n"
            "User: What is the capital of France?\n"
            "Assistant: The capital of France is Paris.\n\n"
            "User: What is the capital of France?\n"
            "Assistant: The capital of France is Paris."
        )
        msg = AIMessage(content=content)
        transform_muse_glimmer_message(msg)
        assert msg.content == "The capital of France is Paris."
        assert "User:" not in msg.content
        assert "Assistant:" not in msg.content
        assert not msg.tool_calls
