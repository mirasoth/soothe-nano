"""Tests for streaming/non-streaming token usage passthrough in ChatLitellmModel.

OpenAI-compatible streams omit usage unless ``stream_options={"include_usage":
True}`` is requested, which used to force every consumer (loop token totals,
TUI counters) onto content-based estimates. The adapter must:

- request streaming usage for ``openai/``-prefixed models (and retry without
  it when a server rejects the parameter),
- capture per-chunk usage and emit a terminal usage-only ``AIMessageChunk``,
- attach ``usage_metadata`` to the AIMessage on non-streaming calls.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from soothe_nano.llm.provider import (
    ChatLitellmModel,
    _usage_metadata_from_litellm,
)
from soothe_nano.llm.registry import ProviderCapabilities


def _make_model(spec: str) -> ChatLitellmModel:
    """Create a real ChatLitellmModel for testing (no network calls)."""
    return ChatLitellmModel(
        model=spec,
        api_base=None,
        api_key=None,
        capabilities=ProviderCapabilities(hide_thinking_tokens=False),
        temperature=0.7,
        streaming=True,
        model_kwargs={},
    )


def _litellm_usage(
    prompt: int, completion: int, total: int, *, cache_read: int = 0
) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=0,
    )


def _text_stream_chunk(content: str) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _usage_stream_chunk(usage: Any) -> SimpleNamespace:
    """Usage-only chunks arrive with empty ``choices`` (OpenAI stream_options)."""
    return SimpleNamespace(choices=[], usage=usage)


# ---------------------------------------------------------------------------
# _usage_metadata_from_litellm
# ---------------------------------------------------------------------------


class TestUsageMetadataFromLitellm:
    """Direct tests for the litellm Usage → usage_metadata normalizer."""

    def test_none_usage_returns_none(self) -> None:
        assert _usage_metadata_from_litellm(None) is None

    def test_zero_usage_returns_none(self) -> None:
        usage = _litellm_usage(0, 0, 0)
        assert _usage_metadata_from_litellm(usage) is None

    def test_positive_usage_normalized(self) -> None:
        usage = _litellm_usage(10, 5, 15)
        assert _usage_metadata_from_litellm(usage) == {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }

    def test_total_missing_computed_from_parts(self) -> None:
        usage = _litellm_usage(7, 3, 0)
        metadata = _usage_metadata_from_litellm(usage)
        assert metadata is not None
        assert metadata["total_tokens"] == 10

    def test_cache_counts_surface_in_details(self) -> None:
        usage = _litellm_usage(100, 5, 105, cache_read=64)
        metadata = _usage_metadata_from_litellm(usage)
        assert metadata is not None
        assert metadata["input_token_details"] == {"cache_read": 64, "cache_creation": 0}


# ---------------------------------------------------------------------------
# Sync streaming
# ---------------------------------------------------------------------------


class TestStreamUsagePassthrough:
    """``_stream`` emits a terminal usage-only chunk with real counts."""

    def test_stream_emits_usage_only_chunk(self) -> None:
        model = _make_model("openai/qwen3.6-flash")
        chunks = [
            _text_stream_chunk("hello "),
            _text_stream_chunk("world"),
            _usage_stream_chunk(_litellm_usage(120, 30, 150)),
        ]
        with patch("litellm.completion", return_value=iter(chunks)):
            out = list(model._stream([HumanMessage(content="hi")]))

        usage_chunks = [c for c in out if c.message.usage_metadata]
        assert len(usage_chunks) == 1
        assert usage_chunks[0].message.usage_metadata == {
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
        }
        # Text content chunks are still yielded normally.
        text = "".join(c.message.content for c in out if isinstance(c.message, AIMessageChunk))
        assert "hello world" in text

    def test_stream_options_requested_for_openai_prefix(self) -> None:
        model = _make_model("openai/qwen3.6-flash")
        captured: dict[str, Any] = {}

        def fake_completion(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return iter([_text_stream_chunk("hi")])

        with patch("litellm.completion", side_effect=fake_completion):
            list(model._stream([HumanMessage(content="hi")]))

        assert captured["stream_options"] == {"include_usage": True}

    def test_no_stream_options_for_non_openai_prefix(self) -> None:
        model = _make_model("anthropic/claude-sonnet-4-5")
        captured: dict[str, Any] = {}

        def fake_completion(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return iter([_text_stream_chunk("hi")])

        with patch("litellm.completion", side_effect=fake_completion):
            list(model._stream([HumanMessage(content="hi")]))

        assert "stream_options" not in captured

    def test_stream_options_error_retries_without_usage(self) -> None:
        model = _make_model("openai/qwen3.6-flash")
        captured_calls: list[dict[str, Any]] = []

        def fake_completion(**kwargs: Any) -> Any:
            captured_calls.append(kwargs)
            if len(captured_calls) == 1:
                msg = "BadRequestError: stream_options is not supported by this server"
                raise Exception(msg)  # noqa: TRY002
            return iter([_text_stream_chunk("recovered")])

        with patch("litellm.completion", side_effect=fake_completion):
            out = list(model._stream([HumanMessage(content="hi")]))

        assert len(captured_calls) == 2
        assert "stream_options" in captured_calls[0]
        assert "stream_options" not in captured_calls[1]
        text = "".join(c.message.content for c in out)
        assert text == "recovered"

    def test_empty_choices_chunk_does_not_crash(self) -> None:
        model = _make_model("openai/gpt-4o-mini")
        chunks = [
            _usage_stream_chunk(_litellm_usage(5, 1, 6)),
            _text_stream_chunk("text after usage chunk"),
        ]
        with patch("litellm.completion", return_value=iter(chunks)):
            out = list(model._stream([HumanMessage(content="hi")]))

        text = "".join(c.message.content for c in out)
        assert "text after usage chunk" in text


# ---------------------------------------------------------------------------
# Async streaming
# ---------------------------------------------------------------------------


class TestAstreamUsagePassthrough:
    """``_astream`` emits a terminal usage-only chunk with real counts."""

    @staticmethod
    async def _collect(agen: Any) -> list[Any]:
        out = []
        async for chunk in agen:
            out.append(chunk)
        return out

    def test_astream_emits_usage_only_chunk(self) -> None:
        model = _make_model("openai/qwen3.6-flash")

        async def fake_stream(**kwargs: Any) -> Any:
            for chunk in [
                _text_stream_chunk("hi there"),
                _usage_stream_chunk(_litellm_usage(80, 12, 92)),
            ]:
                yield chunk

        with patch("litellm.acompletion", side_effect=fake_stream):
            out = asyncio.run(self._collect(model._astream([HumanMessage(content="hi")])))

        usage_chunks = [c for c in out if c.message.usage_metadata]
        assert len(usage_chunks) == 1
        assert usage_chunks[0].message.usage_metadata["total_tokens"] == 92

    def test_astream_stream_options_error_retries(self) -> None:
        model = _make_model("openai/qwen3.6-flash")
        calls: list[dict[str, Any]] = []

        async def fake_stream(**kwargs: Any) -> Any:
            calls.append(kwargs)
            if len(calls) == 1:
                msg = "400: unsupported parameter stream_options"
                raise Exception(msg)  # noqa: TRY002
            yield _text_stream_chunk("async recovered")

        with patch("litellm.acompletion", side_effect=fake_stream):
            out = asyncio.run(self._collect(model._astream([HumanMessage(content="hi")])))

        assert len(calls) == 2
        assert "stream_options" not in calls[1]
        text = "".join(c.message.content for c in out)
        assert text == "async recovered"


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------


class TestGenerateUsageAttach:
    """``_generate``/``_agenerate`` attach usage_metadata to the AIMessage."""

    def test_generate_attaches_usage_metadata(self) -> None:
        model = _make_model("openai/gpt-4o-mini")
        message = SimpleNamespace(content="answer", tool_calls=None, reasoning_content=None)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=_litellm_usage(50, 8, 58),
        )
        with patch("litellm.completion", return_value=response):
            result = model._generate([HumanMessage(content="q")])

        ai_msg = result.generations[0].message
        assert isinstance(ai_msg, AIMessage)
        assert ai_msg.usage_metadata == {
            "input_tokens": 50,
            "output_tokens": 8,
            "total_tokens": 58,
        }

    def test_agenerate_attaches_usage_metadata(self) -> None:
        model = _make_model("openai/gpt-4o-mini")
        message = SimpleNamespace(content="answer", tool_calls=None, reasoning_content=None)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=_litellm_usage(30, 4, 34),
        )

        async def fake_acompletion(**kwargs: Any) -> Any:
            return response

        with patch("litellm.acompletion", side_effect=fake_acompletion):
            result = asyncio.run(model._agenerate([HumanMessage(content="q")]))

        ai_msg = result.generations[0].message
        assert ai_msg.usage_metadata is not None
        assert ai_msg.usage_metadata["total_tokens"] == 34

    def test_generate_without_usage_leaves_message_intact(self) -> None:
        model = _make_model("openai/gpt-4o-mini")
        message = SimpleNamespace(content="answer", tool_calls=None, reasoning_content=None)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=None,
        )
        with patch("litellm.completion", return_value=response):
            result = model._generate([HumanMessage(content="q")])

        ai_msg = result.generations[0].message
        assert ai_msg.usage_metadata is None


# ---------------------------------------------------------------------------
# AIMessageChunk usage extraction (dedup contract)
# ---------------------------------------------------------------------------


class TestChunkUsageExtraction:
    """Terminal usage-only chunk feeds message-based extraction."""

    def test_usage_only_chunk_is_extractable(self) -> None:
        from soothe_nano.utils.token_usage import extract_token_usage_from_messages

        chunk = AIMessageChunk(
            content="",
            usage_metadata={"input_tokens": 9, "output_tokens": 2, "total_tokens": 11},
        )
        usage = extract_token_usage_from_messages([chunk])
        assert usage == {"prompt": 9, "completion": 2, "total": 11}

    def test_same_id_chunks_last_wins(self) -> None:
        """Cumulative-usage providers: the last chunk of a generation wins."""
        from soothe_nano.utils.token_usage import extract_token_usage_from_messages

        first = AIMessageChunk(
            content="a",
            id="g1",
            usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
        )
        last = AIMessageChunk(
            content="b",
            id="g1",
            usage_metadata={"input_tokens": 10, "output_tokens": 25, "total_tokens": 35},
        )
        usage = extract_token_usage_from_messages([first, last])
        assert usage == {"prompt": 10, "completion": 25, "total": 35}

    def test_distinct_ids_sum(self) -> None:
        from soothe_nano.utils.token_usage import extract_token_usage_from_messages

        one = AIMessageChunk(
            content="a",
            id="g1",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
        two = AIMessageChunk(
            content="b",
            id="g2",
            usage_metadata={"input_tokens": 20, "output_tokens": 4, "total_tokens": 24},
        )
        usage = extract_token_usage_from_messages([one, two])
        assert usage == {"prompt": 30, "completion": 6, "total": 36}

    @pytest.mark.parametrize("missing", [None, 0])
    def test_absent_usage_returns_empty(self, missing: Any) -> None:
        assert _usage_metadata_from_litellm(missing) is None
