"""Tests for LLM token extraction and Langfuse-oriented ``llm_output`` enrichment."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from soothe_nano.llm.observability import (
    bind_llm_token_observability,
    ensure_openai_style_token_usage_on_llm_result,
    extract_token_counts_from_llm_result,
    get_llm_token_usage_callback_handler,
    merge_token_usage_callbacks,
)


def test_extract_from_usage_metadata_on_message() -> None:
    msg = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(generations=[[gen]], llm_output=None)
    counts = extract_token_counts_from_llm_result(result)
    assert counts == {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}


def test_ensure_llm_output_from_usage_metadata() -> None:
    msg = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(generations=[[gen]], llm_output=None)
    ensure_openai_style_token_usage_on_llm_result(result)
    assert result.llm_output is not None
    tu = result.llm_output["token_usage"]
    assert tu["prompt_tokens"] == 4
    assert tu["completion_tokens"] == 5
    assert tu["total_tokens"] == 9


def test_ensure_skips_when_token_usage_present() -> None:
    msg = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(
        generations=[[gen]],
        llm_output={
            "token_usage": {"prompt_tokens": 9, "completion_tokens": 9, "total_tokens": 18}
        },
    )
    ensure_openai_style_token_usage_on_llm_result(result)
    assert result.llm_output["token_usage"]["prompt_tokens"] == 9


def test_bind_llm_token_observability_invokes_callback() -> None:
    msg = AIMessage(
        content="done",
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    )
    inner = GenericFakeChatModel(messages=iter([msg]))
    wrapped = bind_llm_token_observability(inner)
    out = wrapped.invoke([HumanMessage(content="hi")])
    assert out.content == "done"


def test_merge_token_usage_callbacks_attaches_handler() -> None:
    handler = get_llm_token_usage_callback_handler()
    merged = merge_token_usage_callbacks({"metadata": {"purpose": "test"}})
    callbacks = merged.get("callbacks")
    assert callbacks is not None
    assert handler in callbacks
    assert merged.get("metadata") == {"purpose": "test"}


@pytest.mark.asyncio
async def test_merge_token_usage_callbacks_passthrough_when_none() -> None:
    """``merge_token_usage_callbacks(None)`` still attaches the shared handler."""
    merged = merge_token_usage_callbacks(None)
    callbacks = merged.get("callbacks")
    assert callbacks is not None
    assert get_llm_token_usage_callback_handler() in callbacks
