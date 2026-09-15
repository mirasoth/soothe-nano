"""Tests for thinking-only stream failover in MultiModelChatModel.

When a thinking model (e.g. glm-5.2 with hide_thinking_tokens=True) emits
its entire output inside ``<think>`` blocks, ThinkingStreamFilter strips
them, leaving chunks with only whitespace. The streaming failover in
``_stream`` and ``_astream`` must detect this post-strip emptiness and
fail over to the next model — not silently surface empty content.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk

from soothe_nano.llm.provider import ChatLitellmModel, MultiModelChatModel
from soothe_nano.llm.registry import ProviderCapabilities


def _make_chat_litellm_model(spec: str) -> ChatLitellmModel:
    """Create a real ChatLitellmModel for testing (no network calls)."""
    return ChatLitellmModel(
        model=spec,
        api_base=None,
        api_key=None,
        capabilities=ProviderCapabilities(),
        temperature=0.7,
        streaming=True,
        model_kwargs={},
    )


def _text_chunk(text: str) -> ChatGenerationChunk:
    """Create a chunk with the given text content."""
    return ChatGenerationChunk(message=AIMessageChunk(content=text))


def _tool_call_chunk() -> ChatGenerationChunk:
    """Create a chunk carrying a tool-call fragment."""
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "get_weather",
                    "args": '{"city": "NYC"}',
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        )
    )


# ---------------------------------------------------------------------------
# Sync _stream
# ---------------------------------------------------------------------------


class TestStreamThinkingOnlyFailover:
    """Tests for ``_stream`` thinking-only detection and failover."""

    def test_thinking_only_stream_fails_over_to_second_model(self) -> None:
        """A thinking-only first model should trigger failover to the second."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        # Simulate thinking-only: whitespace chunks (post-strip)
        m1._stream = MagicMock(return_value=iter([_text_chunk("   "), _text_chunk("\n  ")]))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._stream = MagicMock(return_value=iter([_text_chunk("real content")]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            chunks = list(wrapper._stream([HumanMessage(content="hi")]))

        text = "".join(c.message.content for c in chunks)
        # Whitespace from m1 is yielded before failover is detected; m2's
        # real content follows after failover.
        assert "real content" in text
        assert text.strip() == "real content"
        m1._stream.assert_called_once()
        m2._stream.assert_called_once()

    def test_real_content_first_model_no_failover(self) -> None:
        """Non-empty content on first model should not trigger failover."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._stream = MagicMock(return_value=iter([_text_chunk("hello world")]))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._stream = MagicMock(return_value=iter([]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            chunks = list(wrapper._stream([HumanMessage(content="hi")]))

        text = "".join(c.message.content for c in chunks)
        assert text == "hello world"
        m1._stream.assert_called_once()
        m2._stream.assert_not_called()

    def test_zero_chunks_first_model_fails_over(self) -> None:
        """Zero-chunk stream (contentless 200-OK) should still fail over."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._stream = MagicMock(return_value=iter([]))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._stream = MagicMock(return_value=iter([_text_chunk("from-m2")]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            chunks = list(wrapper._stream([HumanMessage(content="hi")]))

        text = "".join(c.message.content for c in chunks)
        assert text == "from-m2"

    def test_tool_call_chunks_count_as_content(self) -> None:
        """Tool-call fragments should count as real content (no failover)."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._stream = MagicMock(return_value=iter([_tool_call_chunk()]))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._stream = MagicMock(return_value=iter([]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            chunks = list(wrapper._stream([HumanMessage(content="hi")]))

        assert len(chunks) == 1
        assert chunks[0].message.tool_call_chunks
        m2._stream.assert_not_called()

    def test_all_models_thinking_only_raises(self) -> None:
        """All models thinking-only → RuntimeError after exhausting the pool."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._stream = MagicMock(return_value=iter([_text_chunk("  ")]))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._stream = MagicMock(return_value=iter([_text_chunk("\n")]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            with pytest.raises(RuntimeError, match="all models in pool failed"):
                list(wrapper._stream([HumanMessage(content="hi")]))

    def test_mixed_thinking_and_real_content_no_failover(self) -> None:
        """Whitespace chunk followed by real content should not fail over."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._stream = MagicMock(
            return_value=iter([_text_chunk("  "), _text_chunk("real"), _text_chunk("  ")])
        )

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._stream = MagicMock(return_value=iter([]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            chunks = list(wrapper._stream([HumanMessage(content="hi")]))

        text = "".join(c.message.content for c in chunks)
        assert "real" in text
        m2._stream.assert_not_called()


# ---------------------------------------------------------------------------
# Async _astream
# ---------------------------------------------------------------------------


class TestAstreamThinkingOnlyFailover:
    """Tests for ``_astream`` thinking-only detection and failover."""

    @staticmethod
    def _async_iter(chunks: list[ChatGenerationChunk]) -> AsyncIterator[ChatGenerationChunk]:
        async def _gen() -> AsyncIterator[ChatGenerationChunk]:
            for c in chunks:
                yield c

        return _gen()

    def test_thinking_only_astream_fails_over(self) -> None:
        """Thinking-only first model should trigger async failover."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._astream = MagicMock(
            return_value=self._async_iter([_text_chunk("   "), _text_chunk("  ")])
        )

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._astream = MagicMock(return_value=self._async_iter([_text_chunk("real content")]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            chunks = asyncio.run(
                self._collect_async(wrapper._astream([HumanMessage(content="hi")]))
            )

        text = "".join(c.message.content for c in chunks)
        assert "real content" in text
        assert text.strip() == "real content"
        m1._astream.assert_called_once()
        m2._astream.assert_called_once()

    def test_real_content_astream_no_failover(self) -> None:
        """Non-empty content on first model should not trigger failover."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._astream = MagicMock(return_value=self._async_iter([_text_chunk("hello")]))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._astream = MagicMock(return_value=self._async_iter([]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            chunks = asyncio.run(
                self._collect_async(wrapper._astream([HumanMessage(content="hi")]))
            )

        text = "".join(c.message.content for c in chunks)
        assert text == "hello"
        m2._astream.assert_not_called()

    def test_all_models_thinking_only_astream_raises(self) -> None:
        """All models thinking-only → RuntimeError after exhausting the pool."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._astream = MagicMock(return_value=self._async_iter([_text_chunk("  ")]))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._astream = MagicMock(return_value=self._async_iter([_text_chunk("\n")]))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            with pytest.raises(RuntimeError, match="all models in pool failed"):
                asyncio.run(self._collect_async(wrapper._astream([HumanMessage(content="hi")])))

    @staticmethod
    async def _collect_async(agen: AsyncIterator[ChatGenerationChunk]) -> list[ChatGenerationChunk]:
        result: list[ChatGenerationChunk] = []
        async for chunk in agen:
            result.append(chunk)
        return result


# ---------------------------------------------------------------------------
# _chunk_has_content helper
# ---------------------------------------------------------------------------


class TestChunkHasContent:
    """Direct tests for the ``_chunk_has_content`` static helper."""

    def test_text_chunk_with_content(self) -> None:
        chunk = _text_chunk("hello")
        assert MultiModelChatModel._chunk_has_content(chunk) is True

    def test_whitespace_only_chunk(self) -> None:
        chunk = _text_chunk("   \n  ")
        assert MultiModelChatModel._chunk_has_content(chunk) is False

    def test_empty_string_chunk(self) -> None:
        chunk = _text_chunk("")
        assert MultiModelChatModel._chunk_has_content(chunk) is False

    def test_tool_call_chunk_counts_as_content(self) -> None:
        chunk = _tool_call_chunk()
        assert MultiModelChatModel._chunk_has_content(chunk) is True
