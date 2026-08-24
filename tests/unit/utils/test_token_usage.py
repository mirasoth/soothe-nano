"""Unit tests for the unified ``estimate_token_usage`` API (IG-761).

Covers:
- Actual-first path: when AI messages carry ``usage_metadata``, real counts
  are returned and no estimated counts are added (no double-counting).
- Estimate path: when no usage metadata is present, input AND output tokens
  are estimated via model-aware ``count_tokens`` plus structural overhead.
- Mixed message types (Human / System / AI / Tool) handled consistently.
- Block-list content (text blocks) estimated correctly.
- Empty message list returns all-zero counts.
- Loop-scoped token accumulation helpers (scopes, sinks, coercion).
- ``extract_token_usage_from_messages`` covering ``response_metadata`` and
  ``AIMessageChunk`` paths.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import LLMResult

from soothe_nano.utils.token_usage import (
    DirectLLMTokenTarget,
    accumulate_loop_tokens_from_llm_result,
    coerce_total_tokens_used,
    direct_llm_token_call_scope,
    estimate_token_usage,
    extract_token_usage_from_messages,
    loop_token_accumulation_scope,
    merge_direct_llm_tokens_into_state,
)


class TestEstimateTokenUsageActualFirst:
    """When usage_metadata is present, actual counts win (no double-count)."""

    def test_single_ai_message_with_usage_returns_actual(self) -> None:
        messages = [
            HumanMessage(content="What is 2+2?"),
            AIMessage(
                content="4",
                usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
            ),
        ]
        usage = estimate_token_usage(messages)
        assert usage == {
            "input_tokens": 10,
            "output_tokens": 1,
            "total_tokens": 11,
            "source": "actual",
        }

    def test_multiple_ai_turns_sum_actual_usage(self) -> None:
        messages = [
            HumanMessage(content="q1"),
            AIMessage(
                content="a1",
                usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            ),
            HumanMessage(content="q2"),
            AIMessage(
                content="a2",
                usage_metadata={"input_tokens": 200, "output_tokens": 20, "total_tokens": 220},
            ),
        ]
        usage = estimate_token_usage(messages)
        assert usage["input_tokens"] == 300
        assert usage["output_tokens"] == 30
        assert usage["total_tokens"] == 330

    def test_actual_path_does_not_add_estimated_overhead(self) -> None:
        """Actual counts must not have structural overhead added."""
        messages = [
            HumanMessage(content="x" * 1000),
            AIMessage(
                content="y" * 1000,
                usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
            ),
        ]
        usage = estimate_token_usage(messages)
        # Exact actual counts, no overhead added
        assert usage["total_tokens"] == 8


class TestEstimateTokenUsageEstimatePath:
    """When usage_metadata is absent, estimate input AND output."""

    def test_no_usage_metadata_estimates_both_input_and_output(self) -> None:
        messages = [
            HumanMessage(content="What is the capital of France?"),
            AIMessage(content="The capital of France is Paris."),
        ]
        usage = estimate_token_usage(messages)
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] > 0
        assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]

    def test_estimated_output_not_alone(self) -> None:
        """IG-761 core fix: estimation must count input, not output alone."""
        messages = [
            HumanMessage(content="Tell me a long story about a brave knight"),
            AIMessage(content="Once upon a time there was a brave knight..."),
        ]
        usage = estimate_token_usage(messages)
        # Before the fix, the executor fallback counted output only.
        # After: input_tokens must be positive and total > output_tokens.
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] > 0
        assert usage["total_tokens"] > usage["output_tokens"]

    def test_empty_message_list_returns_zeros(self) -> None:
        usage = estimate_token_usage([])
        assert usage == {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "source": "estimated",
        }

    def test_structural_overhead_added_on_estimate_path(self) -> None:
        """Per-message structural overhead (role tags) is included."""
        one_msg = [HumanMessage(content="hello")]
        two_msgs = [HumanMessage(content="hello"), HumanMessage(content="world")]
        u1 = estimate_token_usage(one_msg)
        u2 = estimate_token_usage(two_msgs)
        # Second message adds its text tokens PLUS structural overhead,
        # so u2 > u1 by more than just the text token count of "world".
        assert u2["input_tokens"] > u1["input_tokens"]


class TestEstimateTokenUsageMixedTypes:
    """Mixed message types and block content."""

    def test_system_human_ai_tool_messages(self) -> None:
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Use the calculator tool to compute 2+2."),
            AIMessage(content=""),
            ToolMessage(content="4", tool_call_id="call_1"),
        ]
        usage = estimate_token_usage(messages)
        assert usage["input_tokens"] > 0
        assert usage["total_tokens"] > 0

    def test_block_list_content_estimated(self) -> None:
        """List content with text blocks is counted."""
        messages = [
            HumanMessage(content=[{"type": "text", "text": "First block"}]),
            AIMessage(content=[{"type": "text", "text": "Second block"}]),
        ]
        usage = estimate_token_usage(messages)
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] > 0

    def test_model_hint_does_not_break_estimation(self) -> None:
        """Passing a model hint selects an encoding without error."""
        messages = [HumanMessage(content="hello world")]
        usage_openai = estimate_token_usage(messages, model="gpt-4o")
        usage_claude = estimate_token_usage(messages, model="claude-3-5-sonnet-20241022")
        assert usage_openai["total_tokens"] > 0
        assert usage_claude["total_tokens"] > 0


class TestEstimateTokenUsageActualVsEstimated:
    """Actual-first path wins over estimation when both could apply."""

    def test_one_ai_with_usage_one_without_returns_actual_sum(self) -> None:
        """When ANY ai message has usage_metadata, the actual-first path
        sums actual usage across AI turns and does not estimate the
        AI message lacking usage_metadata (documented behavior of
        extract_token_usage_from_messages — it only sums messages that
        carry usage)."""
        messages = [
            HumanMessage(content="q1"),
            AIMessage(
                content="a1",
                usage_metadata={"input_tokens": 50, "output_tokens": 5, "total_tokens": 55},
            ),
            AIMessage(content="a2 without usage"),
        ]
        usage = estimate_token_usage(messages)
        # Actual-first path returns the sum of AI turns that carry usage.
        assert usage["total_tokens"] == 55
        assert usage["source"] == "actual"


class TestEstimateTokenUsageEdgeCases:
    """Edge-case coverage for ``estimate_token_usage`` (IG-761)."""

    def test_response_metadata_token_usage_path(self) -> None:
        """When ``usage_metadata`` is absent but ``response_metadata.token_usage``
        is present, the actual-first path still returns actual counts."""
        messages = [
            HumanMessage(content="q"),
            AIMessage(
                content="a",
                response_metadata={
                    "token_usage": {
                        "prompt_tokens": 42,
                        "completion_tokens": 7,
                        "total_tokens": 49,
                    }
                },
            ),
        ]
        usage = estimate_token_usage(messages)
        assert usage["source"] == "actual"
        assert usage["input_tokens"] == 42
        assert usage["output_tokens"] == 7
        assert usage["total_tokens"] == 49

    def test_aimessagechunk_estimated_on_fallback(self) -> None:
        """``AIMessageChunk`` without usage is estimated as output tokens."""
        messages = [
            HumanMessage(content="hello"),
            AIMessageChunk(content="world"),
        ]
        usage = estimate_token_usage(messages)
        assert usage["source"] == "estimated"
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] > 0

    def test_none_content_ai_message(self) -> None:
        """AI message with ``None`` content contributes zero output tokens.

        ``AIMessage`` validates content as str/list, so we use
        ``model_construct`` to bypass validation and exercise the
        ``_count_content_tokens(None, ...)`` branch.
        """
        messages = [
            HumanMessage(content="prompt text"),
            AIMessage.model_construct(content=None),
        ]
        usage = estimate_token_usage(messages)
        assert usage["source"] == "estimated"
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == usage["input_tokens"]

    def test_dict_content_in_ai_message(self) -> None:
        """Non-list, non-str content (e.g. a dict) is stringified and counted.

        ``AIMessage`` validates content as str/list, so we use
        ``model_construct`` to bypass validation and exercise the
        ``_count_content_tokens(dict, ...)`` branch.
        """
        messages = [
            HumanMessage(content="prompt"),
            AIMessage.model_construct(content={"key": "value"}),
        ]
        usage = estimate_token_usage(messages)
        assert usage["output_tokens"] > 0

    def test_tool_message_counted_as_input(self) -> None:
        """Tool messages are input-side, not output-side."""
        messages = [
            HumanMessage(content="run the tool"),
            AIMessage(content=""),
            ToolMessage(content="tool result text here", tool_call_id="c1"),
        ]
        usage = estimate_token_usage(messages)
        assert usage["source"] == "estimated"
        # The tool message text contributes to input, not output.
        assert usage["input_tokens"] > 0

    def test_only_human_messages(self) -> None:
        """A prompt-only message list estimates input, zero output."""
        messages = [HumanMessage(content="just a prompt")]
        usage = estimate_token_usage(messages)
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] == 0

    def test_model_hint_affects_encoding_selection(self) -> None:
        """Different model hints may produce different token counts for the
        same text when encodings differ (gpt-4o vs gpt-4)."""
        text = "Hello world " * 50
        messages = [HumanMessage(content=text)]
        u_4o = estimate_token_usage(messages, model="gpt-4o")
        u_4 = estimate_token_usage(messages, model="gpt-4")
        # Both must be positive; they may or may not differ, but must not error.
        assert u_4o["total_tokens"] > 0
        assert u_4["total_tokens"] > 0

    def test_structural_overhead_proportional_to_message_count(self) -> None:
        """More messages → more structural overhead (3 tokens per message)."""
        one = [HumanMessage(content="x")]
        two = [HumanMessage(content="x"), HumanMessage(content="x")]
        u1 = estimate_token_usage(one)
        u2 = estimate_token_usage(two)
        # Second message adds text tokens + 3 structural tokens.
        assert u2["input_tokens"] >= u1["input_tokens"] + 3


class TestCoerceTotalTokensUsed:
    """Cover ``coerce_total_tokens_used`` for all input shapes (IG-761)."""

    def test_integer_input(self) -> None:
        assert coerce_total_tokens_used(42) == 42

    def test_string_integer(self) -> None:
        assert coerce_total_tokens_used("42") == 42

    def test_negative_clamped_to_zero(self) -> None:
        assert coerce_total_tokens_used(-5) == 0
        assert coerce_total_tokens_used("-10") == 0

    def test_non_numeric_string_returns_zero(self) -> None:
        assert coerce_total_tokens_used("bad") == 0

    def test_none_returns_zero(self) -> None:
        assert coerce_total_tokens_used(None) == 0

    def test_float_truncated(self) -> None:
        assert coerce_total_tokens_used(42.9) == 42

    def test_bool_is_int(self) -> None:
        # bool is a subclass of int; True → 1
        assert coerce_total_tokens_used(True) == 1
        assert coerce_total_tokens_used(False) == 0


class TestDirectLLMTokenTarget:
    """Cover ``DirectLLMTokenTarget`` dataclass sink."""

    def test_default_zero(self) -> None:
        target = DirectLLMTokenTarget()
        assert target.total_tokens_used == 0

    def test_initial_value(self) -> None:
        target = DirectLLMTokenTarget(total_tokens_used=100)
        assert target.total_tokens_used == 100

    def test_mutable(self) -> None:
        target = DirectLLMTokenTarget()
        target.total_tokens_used += 50
        assert target.total_tokens_used == 50


class TestMergeDirectLLMTokensIntoState:
    """Cover ``merge_direct_llm_tokens_into_state`` (IG-761)."""

    def test_positive_delta_added(self) -> None:
        state = SimpleNamespace(total_tokens_used=100)
        sink = DirectLLMTokenTarget(total_tokens_used=250)
        delta = merge_direct_llm_tokens_into_state(state, sink)
        assert delta == 250
        assert state.total_tokens_used == 350

    def test_zero_delta_no_change(self) -> None:
        state = SimpleNamespace(total_tokens_used=100)
        sink = DirectLLMTokenTarget(total_tokens_used=0)
        delta = merge_direct_llm_tokens_into_state(state, sink)
        assert delta == 0
        assert state.total_tokens_used == 100

    def test_negative_source_clamped_to_zero(self) -> None:
        state = SimpleNamespace(total_tokens_used=100)
        sink = SimpleNamespace(total_tokens_used=-50)
        delta = merge_direct_llm_tokens_into_state(state, sink)
        assert delta == 0
        assert state.total_tokens_used == 100

    def test_none_source_attribute(self) -> None:
        """A source lacking ``total_tokens_used`` defaults to 0."""
        state = SimpleNamespace(total_tokens_used=10)
        sink = SimpleNamespace()
        delta = merge_direct_llm_tokens_into_state(state, sink)
        assert delta == 0
        assert state.total_tokens_used == 10


class TestLoopTokenAccumulationScope:
    """Cover ``loop_token_accumulation_scope`` context manager (IG-761)."""

    def test_scope_binds_and_resets_target(self) -> None:
        from soothe_nano.utils.token_usage import _token_target

        target = DirectLLMTokenTarget(total_tokens_used=5)
        assert _token_target.get() is None
        with loop_token_accumulation_scope(target):
            assert _token_target.get() is target
        assert _token_target.get() is None

    def test_scope_resets_even_on_exception(self) -> None:
        from soothe_nano.utils.token_usage import _token_target

        target = DirectLLMTokenTarget()
        with pytest.raises(RuntimeError, match="boom"):
            with loop_token_accumulation_scope(target):
                raise RuntimeError("boom")
        assert _token_target.get() is None


class TestDirectLLMTokenCallScope:
    """Cover ``direct_llm_token_call_scope`` context manager (IG-761)."""

    def test_scope_sets_and_resets_flag(self) -> None:
        from soothe_nano.utils.token_usage import _direct_llm_token_accumulation

        assert _direct_llm_token_accumulation.get() is False
        with direct_llm_token_call_scope():
            assert _direct_llm_token_accumulation.get() is True
        assert _direct_llm_token_accumulation.get() is False

    def test_scope_resets_even_on_exception(self) -> None:
        from soothe_nano.utils.token_usage import _direct_llm_token_accumulation

        with pytest.raises(ValueError, match="err"):
            with direct_llm_token_call_scope():
                raise ValueError("err")
        assert _direct_llm_token_accumulation.get() is False


class TestAccumulateLoopTokensFromLLMResult:
    """Cover ``accumulate_loop_tokens_from_llm_result`` (IG-761)."""

    def test_returns_zero_without_direct_scope(self) -> None:
        """No ``direct_llm_token_call_scope`` → returns 0, no mutation."""
        target = DirectLLMTokenTarget()
        response = MagicMock(spec=LLMResult)
        with loop_token_accumulation_scope(target):
            delta = accumulate_loop_tokens_from_llm_result(response)
        assert delta == 0
        assert target.total_tokens_used == 0

    def test_returns_zero_without_accumulation_scope(self) -> None:
        """No ``loop_token_accumulation_scope`` → returns 0."""
        response = MagicMock(spec=LLMResult)
        with direct_llm_token_call_scope():
            delta = accumulate_loop_tokens_from_llm_result(response)
        assert delta == 0

    def test_accumulates_when_both_scopes_active(self) -> None:
        target = DirectLLMTokenTarget()
        response = MagicMock(spec=LLMResult)
        with loop_token_accumulation_scope(target), direct_llm_token_call_scope():
            with patch(
                "soothe_nano.llm.observability.extract_token_counts_from_llm_result",
                return_value={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            ):
                delta = accumulate_loop_tokens_from_llm_result(response)
        assert delta == 15
        assert target.total_tokens_used == 15

    def test_uses_input_plus_output_when_total_missing(self) -> None:
        """When ``total_tokens`` is 0, falls back to input+output."""
        target = DirectLLMTokenTarget()
        response = MagicMock(spec=LLMResult)
        with loop_token_accumulation_scope(target), direct_llm_token_call_scope():
            with patch(
                "soothe_nano.llm.observability.extract_token_counts_from_llm_result",
                return_value={
                    "input_tokens": 8,
                    "output_tokens": 4,
                    "total_tokens": 0,
                },
            ):
                delta = accumulate_loop_tokens_from_llm_result(response)
        assert delta == 12
        assert target.total_tokens_used == 12

    def test_returns_zero_when_no_counts_extracted(self) -> None:
        target = DirectLLMTokenTarget()
        response = MagicMock(spec=LLMResult)
        with loop_token_accumulation_scope(target), direct_llm_token_call_scope():
            with patch(
                "soothe_nano.llm.observability.extract_token_counts_from_llm_result",
                return_value=None,
            ):
                delta = accumulate_loop_tokens_from_llm_result(response)
        assert delta == 0
        assert target.total_tokens_used == 0


class TestExtractTokenUsageFromMessages:
    """Cover ``extract_token_usage_from_messages`` directly (IG-761)."""

    def test_usage_metadata_path(self) -> None:
        messages = [
            AIMessage(
                content="a",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            ),
        ]
        usage = extract_token_usage_from_messages(messages)
        assert usage == {"prompt": 10, "completion": 2, "total": 12}

    def test_response_metadata_token_usage_path(self) -> None:
        """``response_metadata['token_usage']`` with ``prompt_tokens`` keys."""
        messages = [
            AIMessage(
                content="a",
                response_metadata={
                    "token_usage": {
                        "prompt_tokens": 30,
                        "completion_tokens": 5,
                        "total_tokens": 35,
                    }
                },
            ),
        ]
        usage = extract_token_usage_from_messages(messages)
        assert usage == {"prompt": 30, "completion": 5, "total": 35}

    def test_response_metadata_with_input_output_keys(self) -> None:
        """``response_metadata['token_usage']`` with ``input_tokens`` keys."""
        messages = [
            AIMessage(
                content="a",
                response_metadata={
                    "token_usage": {
                        "input_tokens": 40,
                        "output_tokens": 6,
                        "total_tokens": 46,
                    }
                },
            ),
        ]
        usage = extract_token_usage_from_messages(messages)
        assert usage == {"prompt": 40, "completion": 6, "total": 46}

    def test_aimessagechunk_with_usage(self) -> None:
        """Stream chunks carrying usage_metadata are summed on the chunk path."""
        messages = [
            AIMessageChunk(
                content="chunk",
                usage_metadata={
                    "input_tokens": 5,
                    "output_tokens": 1,
                    "total_tokens": 6,
                },
            ),
        ]
        usage = extract_token_usage_from_messages(messages)
        assert usage == {"prompt": 5, "completion": 1, "total": 6}

    def test_mixed_ai_and_human_messages(self) -> None:
        """Non-AI messages are skipped; AI messages are summed."""
        messages = [
            HumanMessage(content="q"),
            AIMessage(
                content="a1",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            ),
            ToolMessage(content="tool", tool_call_id="c1"),
            AIMessage(
                content="a2",
                usage_metadata={
                    "input_tokens": 20,
                    "output_tokens": 4,
                    "total_tokens": 24,
                },
            ),
        ]
        usage = extract_token_usage_from_messages(messages)
        assert usage == {"prompt": 30, "completion": 6, "total": 36}

    def test_empty_list_returns_empty_dict(self) -> None:
        assert extract_token_usage_from_messages([]) == {}

    def test_no_usage_returns_empty_dict(self) -> None:
        messages = [
            HumanMessage(content="q"),
            AIMessage(content="a"),
        ]
        assert extract_token_usage_from_messages(messages) == {}

    def test_total_missing_computed_from_prompt_plus_completion(self) -> None:
        """When ``total_tokens`` is 0, it's computed as prompt + completion."""
        messages = [
            AIMessage(
                content="a",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 3,
                    "total_tokens": 0,
                },
            ),
        ]
        usage = extract_token_usage_from_messages(messages)
        assert usage["total"] == 13

    def test_zero_usage_skipped(self) -> None:
        """Messages with all-zero usage are not counted (total must be > 0)."""
        messages = [
            AIMessage(
                content="a",
                usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            ),
        ]
        assert extract_token_usage_from_messages(messages) == {}

    def test_usage_metadata_takes_precedence_over_response_metadata(self) -> None:
        """``usage_metadata`` is checked before ``response_metadata``."""
        messages = [
            AIMessage(
                content="a",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
                response_metadata={
                    "token_usage": {
                        "prompt_tokens": 999,
                        "completion_tokens": 999,
                        "total_tokens": 999,
                    }
                },
            ),
        ]
        usage = extract_token_usage_from_messages(messages)
        assert usage == {"prompt": 10, "completion": 2, "total": 12}
