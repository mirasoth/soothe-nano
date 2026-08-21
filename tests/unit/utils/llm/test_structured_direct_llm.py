"""Unit tests for client JSON Schema structured output helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import jsonschema
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from soothe_nano.llm.schema_wire import validate_response_schema
from soothe_nano.llm.structured import (
    StructuredOutputError,
    ensure_json_keyword_in_messages,
    invoke_structured_chat,
    messages_contain_json_keyword,
    normalize_structured_result,
    wrap_json_keyword_safe,
)

_WORD_SCHEMA = {
    "type": "object",
    "properties": {"word": {"type": "string"}},
    "required": ["word"],
    "additionalProperties": False,
}


def test_validate_response_schema_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        validate_response_schema([])


def test_validate_response_schema_requires_type() -> None:
    with pytest.raises(ValueError, match='"type"'):
        validate_response_schema({"properties": {}})


def test_normalize_structured_result_pydantic() -> None:
    class _M(BaseModel):
        word: str

    assert normalize_structured_result(_M(word="ok")) == {"word": "ok"}


def test_messages_contain_json_keyword() -> None:
    assert messages_contain_json_keyword([HumanMessage(content="Return JSON output")])
    assert not messages_contain_json_keyword([HumanMessage(content="hello")])


def test_ensure_json_keyword_in_messages_appends_hint() -> None:
    original = [SystemMessage(content="plan"), HumanMessage(content="Assess status")]
    updated = ensure_json_keyword_in_messages(original)
    assert len(updated) == len(original) + 1
    assert "json" in updated[-1].content.lower()


def test_ensure_json_keyword_in_messages_noop_when_present() -> None:
    messages = [HumanMessage(content="Respond in JSON format")]
    assert ensure_json_keyword_in_messages(messages) is messages


@pytest.mark.asyncio
async def test_wrap_json_keyword_safe_injects_on_invoke() -> None:
    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value={"word": "OK"})
    wrapped = wrap_json_keyword_safe(inner)

    await wrapped.ainvoke([HumanMessage(content="hi")])

    sent_messages = inner.ainvoke.await_args.args[0]
    assert any("json" in str(getattr(m, "content", "")).lower() for m in sent_messages)


@pytest.mark.asyncio
async def test_invoke_structured_chat_none_falls_back_without_same_method_retry() -> None:
    """function_calling returning None should skip to the next method, not retry FC."""
    chat = MagicMock()
    invoke_counts: dict[str | None, int] = {}

    def _with_structured_output(
        _schema: object, method: str | None = None, **kwargs: object
    ) -> MagicMock:
        runnable = MagicMock()

        async def _ainvoke(*_a: object, **_k: object) -> object:
            invoke_counts[method] = invoke_counts.get(method, 0) + 1
            if method == "json_schema":
                return {"word": "OK"}
            return None

        runnable.ainvoke = _ainvoke
        return runnable

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="Return JSON")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert invoke_counts.get("function_calling") == 1
    assert invoke_counts.get("json_schema") == 1


@pytest.mark.asyncio
async def test_invoke_structured_chat_honors_methods_override() -> None:
    """Caller-preferred method order is tried first."""
    chat = MagicMock()
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(return_value={"word": "FC"})

    def _with_structured_output(
        _schema: object, method: str | None = None, **kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        return fc_runnable

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="Return JSON")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
        methods=("json_schema", "function_calling"),
    )
    assert out == {"word": "OK"}
    assert json_schema_runnable.ainvoke.await_count == 1
    assert fc_runnable.ainvoke.await_count == 0
    first_call_kwargs = chat.with_structured_output.call_args_list[0].kwargs
    assert first_call_kwargs.get("method") == "json_schema"


@pytest.mark.asyncio
async def test_invoke_structured_chat_injects_json_keyword() -> None:
    chat = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value={"word": "OK"})
    chat.with_structured_output = MagicMock(return_value=structured)

    await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )

    sent_messages = structured.ainvoke.await_args.args[0]
    assert any("json" in str(getattr(m, "content", "")).lower() for m in sent_messages)


@pytest.mark.asyncio
async def test_invoke_structured_chat_success() -> None:
    chat = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value={"word": "OK"})
    chat.with_structured_output = MagicMock(return_value=structured)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    chat.with_structured_output.assert_called()


@pytest.mark.asyncio
async def test_invoke_structured_chat_repairs_after_schema_validation_failure() -> None:
    """Post-validate failure retries once with a repair hint (provider may ignore bounds)."""
    chat = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=[{"count": 1}, {"count": 1000}])
    chat.with_structured_output = MagicMock(return_value=structured)

    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer", "minimum": 1000}},
        "required": ["count"],
        "additionalProperties": False,
    }
    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content='Return JSON {"count": 1} only.')],
        json_schema=schema,
        schema_name="StrictCount",
        strict=True,
    )
    assert out == {"count": 1000}
    assert structured.ainvoke.await_count == 2
    repair_messages = structured.ainvoke.await_args_list[1].args[0]
    assert any(
        "schema validation" in str(getattr(m, "content", "")).lower() for m in repair_messages
    )


@pytest.mark.asyncio
async def test_invoke_structured_chat_repairs_after_bind_time_validation_failure() -> None:
    """Bind-time strict validation must retry with a repair hint, not fail the call."""
    chat = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        side_effect=[
            jsonschema.ValidationError("'word' is a required property"),
            {"word": "OK"},
        ]
    )
    chat.with_structured_output = MagicMock(return_value=structured)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="Return JSON")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
        strict=True,
    )
    assert out == {"word": "OK"}
    assert structured.ainvoke.await_count == 2
    repair_messages = structured.ainvoke.await_args_list[1].args[0]
    assert any(
        "schema validation" in str(getattr(m, "content", "")).lower() for m in repair_messages
    )


@pytest.mark.asyncio
async def test_invoke_structured_chat_recovers_from_empty_object_payload() -> None:
    """A reasoning model emitting bare ``{}`` recovers instead of failing the caller.

    Mirrors thinking models that spend the completion budget on reasoning tokens
    and return an empty object. ``invoke_structured_chat`` retries the same
    method once before falling through; the second attempt yields valid JSON.
    """
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(side_effect=[{"word": ""}, {"word": "OK"}])

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    chat = MagicMock()
    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    # minLength:1 makes the empty-string first payload fail post-validation,
    # triggering the validation-retry path (the new-arch equivalent of the old
    # wrapper's empty-object recovery).
    schema = {
        "type": "object",
        "properties": {"word": {"type": "string", "minLength": 1}},
        "required": ["word"],
        "additionalProperties": False,
    }
    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="Return JSON")],
        json_schema=schema,
        schema_name="WordReply",
        strict=True,
        methods=("json_schema",),
    )
    assert out == {"word": "OK"}
    assert json_schema_runnable.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_invoke_structured_chat_retries_json_schema_after_thinking_tool_choice_error() -> (
    None
):
    """Thinking-mode models reject tool_choice; fall back to json_schema at invoke time."""
    chat = MagicMock()
    fc_runnable = MagicMock()
    thinking_err = RuntimeError(
        "tool_choice parameter does not support being set to required in thinking mode"
    )
    fc_runnable.ainvoke = AsyncMock(side_effect=thinking_err)
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})

    def _with_structured_output(
        _schema: object, method: str | None = None, **kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        return fc_runnable

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert json_schema_runnable.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_invoke_structured_chat_caches_working_method_per_chat() -> None:
    """Second invoke on the same chat skips the previously-failing method."""
    chat = MagicMock()
    method_calls: list[str | None] = []
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(
        side_effect=RuntimeError(
            "tool_choice parameter does not support being set to required in thinking mode"
        )
    )
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        method_calls.append(method)
        if method == "json_schema":
            return json_schema_runnable
        return fc_runnable

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out1 = await invoke_structured_chat(
        chat, [HumanMessage(content="hi")], json_schema=_WORD_SCHEMA, schema_name="WordReply"
    )
    assert out1 == {"word": "OK"}
    # First call: function_calling tried (and failed) before json_schema succeeded.
    assert "function_calling" in method_calls
    assert "json_schema" in method_calls

    method_calls.clear()
    fc_awaits_after_first = fc_runnable.ainvoke.await_count
    out2 = await invoke_structured_chat(
        chat, [HumanMessage(content="hi")], json_schema=_WORD_SCHEMA, schema_name="WordReply"
    )
    assert out2 == {"word": "OK"}
    # Second call: json_schema is tried first and succeeds; no failing-method round-trip.
    assert method_calls[0] == "json_schema"
    assert "function_calling" not in method_calls
    assert fc_runnable.ainvoke.await_count == fc_awaits_after_first


@pytest.mark.asyncio
async def test_invoke_structured_chat_json_mode_omits_strict_at_bind() -> None:
    """json_mode bind must not pass strict= (LangChain ValueError); strict applies post-parse."""
    chat = MagicMock()
    json_runnable = MagicMock()
    json_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})

    def _with_structured_output(
        _schema: object, method: str | None = None, **kwargs: object
    ) -> MagicMock:
        if method == "json_mode":
            assert "strict" not in kwargs
            return json_runnable
        raise RuntimeError("unexpected method")

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
        strict=True,
    )
    assert out == {"word": "OK"}


@pytest.mark.asyncio
async def test_invoke_structured_chat_raises_when_all_methods_fail() -> None:
    chat = MagicMock()
    chat.with_structured_output = MagicMock(side_effect=RuntimeError("nope"))

    with pytest.raises(StructuredOutputError, match="all structured output methods failed"):
        await invoke_structured_chat(
            chat,
            [HumanMessage(content="hi")],
            json_schema=_WORD_SCHEMA,
        )


@pytest.mark.asyncio
async def test_structured_output_runnable_parses_plain_json() -> None:
    """``_StructuredOutputRunnable._parse`` returns the dict from a plain JSON response."""
    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    runnable = _StructuredOutputRunnable(model, response_format=None, schema=_WORD_SCHEMA)
    assert runnable._parse(AIMessage(content='{"word": "OK"}')) == {"word": "OK"}


@pytest.mark.asyncio
async def test_structured_output_runnable_strips_config_from_litellm_kwargs() -> None:
    """The LangChain ``config`` RunnableConfig must not leak into litellm kwargs.

    Regression for the JSON-serialization failure
    (``Object of type SootheLLMTokenUsageCallbackHandler is not JSON serializable``)
    that routed every intake query through the heuristic fallback: the shared
    token-usage callback handler traveled via ``config['callbacks']`` into
    ``litellm.completion``, whose body serializer rejected it. ``config`` is a
    RunnableConfig, not a litellm kwarg — the runnable must pull it out.
    """
    from langchain_core.callbacks import BaseCallbackHandler

    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    runnable = _StructuredOutputRunnable(model, response_format=None, schema=_WORD_SCHEMA)

    class _NotJsonSerializable(BaseCallbackHandler):
        """Stand-in for a live callback handler instance."""

    captured: dict[str, object] = {}

    async def _fake_agenerate(messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content='{"word": "OK"}'))],
            llm_output={
                "token_usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}
            },
        )

    model._agenerate = _fake_agenerate  # type: ignore[assignment]

    config: dict[str, object] = {
        "callbacks": [_NotJsonSerializable()],
        "metadata": {"soothe_call_purpose": "classify_pass1"},
        "tags": ["intake"],
    }
    out = await runnable.ainvoke([HumanMessage(content="hi")], config=config)
    assert out == {"word": "OK"}
    # The RunnableConfig (callbacks/metadata/tags) must not reach litellm.
    assert "config" not in captured
    assert "callbacks" not in captured
    assert "metadata" not in captured
    assert "tags" not in captured


@pytest.mark.asyncio
async def test_structured_output_runnable_fires_token_usage_callback() -> None:
    """Structured-output calls fold token usage via LangChain ``on_llm_end``.

    The runnable uses public ``ChatLitellmModel.ainvoke`` so the shared
    ``SootheLLMTokenUsageCallbackHandler`` runs through the callback manager
    (same path as CoreAgent generations).
    """
    from soothe_nano.llm.observability import get_llm_token_usage_callback_handler
    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    runnable = _StructuredOutputRunnable(model, response_format=None, schema=_WORD_SCHEMA)

    async def _fake_agenerate(messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content='{"word": "OK"}'))],
            llm_output={
                "token_usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}
            },
        )

    model._agenerate = _fake_agenerate  # type: ignore[assignment]

    handler = get_llm_token_usage_callback_handler()
    with patch.object(handler, "on_llm_end") as mock_on_llm_end:
        out = await runnable.ainvoke([HumanMessage(content="hi")], config={"callbacks": [handler]})

    assert out == {"word": "OK"}
    mock_on_llm_end.assert_called()
    passed = mock_on_llm_end.call_args.args[0]
    assert getattr(passed, "llm_output", {}).get("token_usage", {}).get("total_tokens") == 4


@pytest.mark.asyncio
async def test_structured_output_runnable_fires_langchain_model_callbacks() -> None:
    """Langfuse-style handlers must see chat-model start/end on structured calls.

    Regression: invoking ``_agenerate`` directly skipped ``on_chat_model_start``,
    so Pass 1 / intent showed as an empty parent span with no GENERATION.
    """
    from langchain_core.callbacks import BaseCallbackHandler

    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    class _TraceHandler(BaseCallbackHandler):
        def __init__(self) -> None:
            self.chat_starts = 0
            self.llm_ends = 0

        def on_chat_model_start(self, serialized, messages, **kwargs):  # type: ignore[no-untyped-def]
            self.chat_starts += 1

        def on_llm_end(self, response, **kwargs):  # type: ignore[no-untyped-def]
            self.llm_ends += 1

    model = ChatLitellmModel(model="openai/test")
    runnable = _StructuredOutputRunnable(model, response_format=None, schema=_WORD_SCHEMA)

    async def _fake_agenerate(messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='{"word": "OK"}'))])

    model._agenerate = _fake_agenerate  # type: ignore[assignment]

    handler = _TraceHandler()
    out = await runnable.ainvoke(
        [HumanMessage(content="hi")],
        config={"callbacks": [handler], "run_name": "soothe:classify-pass1"},
    )
    assert out == {"word": "OK"}
    assert handler.chat_starts >= 1
    assert handler.llm_ends >= 1


@pytest.mark.asyncio
async def test_structured_output_runnable_tolerates_callback_manager() -> None:
    """A leaked LangGraph ``AsyncCallbackManager`` in ``config['callbacks']`` must not crash.

    Regression for the intake misroute (loop 5361): when Langfuse is off, a
    LangGraph node's ``AsyncCallbackManager`` can leak into the structured-output
    ``RunnableConfig``. ``_config_for_model`` did ``list(config.get("callbacks"))``
    to check for the token-usage handler, but a ``CallbackManager`` is not
    iterable → ``TypeError: 'AsyncCallbackManager' object is not iterable`` →
    ``StructuredOutputError`` → intake fail-safe routed every query (including
    chitchat like "how are u") as a complex task. Flatten instead of list()-ifying.
    """
    from langchain_core.callbacks import AsyncCallbackManager

    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    runnable = _StructuredOutputRunnable(model, response_format=None, schema=_WORD_SCHEMA)

    async def _fake_agenerate(messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content='{"word": "OK"}'))],
            llm_output={
                "token_usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}
            },
        )

    model._agenerate = _fake_agenerate  # type: ignore[assignment]

    # Mirrors a LangGraph node config whose AsyncCallbackManager leaked through.
    config: dict[str, object] = {
        "callbacks": AsyncCallbackManager(handlers=[]),
        "metadata": {"soothe_call_purpose": "classify_intake"},
    }
    out = await runnable.ainvoke([HumanMessage(content="hi")], config=config)
    assert out == {"word": "OK"}


def test_flatten_callback_handlers_unpacks_callback_manager() -> None:
    """``_flatten_callback_handlers`` reads ``.handlers``/``.inheritable_handlers``."""
    from langchain_core.callbacks import AsyncCallbackManager, BaseCallbackHandler

    from soothe_nano.llm.provider import _StructuredOutputRunnable

    class _H(BaseCallbackHandler):
        pass

    h1, h2 = _H(), _H()
    # AsyncCallbackManager stores handlers under .handlers
    mgr = AsyncCallbackManager(handlers=[h1, h2])
    flat = _StructuredOutputRunnable._flatten_callback_handlers(mgr)
    assert h1 in flat and h2 in flat

    # lists/tuples recurse; None yields []; bare objects pass through
    assert _StructuredOutputRunnable._flatten_callback_handlers(None) == []
    assert _StructuredOutputRunnable._flatten_callback_handlers([h1, [h2]]) == [h1, h2]
    bare = "not-a-handler"
    assert _StructuredOutputRunnable._flatten_callback_handlers(bare) == [bare]


def test_limited_provider_wrapper_dict_schema() -> None:
    """``with_structured_output`` returns a runnable for a dict schema (not a wrapper class)."""
    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    out = model.with_structured_output(_WORD_SCHEMA, schema_name="WordReply", strict=True)
    assert isinstance(out, _StructuredOutputRunnable)


def test_limited_provider_wrapper_delegates_function_calling() -> None:
    """``with_structured_output`` with method= passes through (no strict-strip per method)."""
    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    out = model.with_structured_output(
        _WORD_SCHEMA,
        method="function_calling",
        strict=True,
        tool_choice="auto",
    )
    assert isinstance(out, _StructuredOutputRunnable)


def test_limited_provider_wrapper_delegates_json_mode_without_strict() -> None:
    """``with_structured_output`` does not forward ``strict`` to litellm (it applies post-parse)."""
    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    out = model.with_structured_output(_WORD_SCHEMA, method="json_mode", strict=True)
    assert isinstance(out, _StructuredOutputRunnable)
    # strict is popped at bind time; response_format carries strictness, not the model.
    assert "strict" not in model.model_kwargs


@pytest.mark.asyncio
async def test_invoke_structured_chat_binds_json_mode_through_compat_wrapper() -> None:
    """method=None/json_mode path succeeds when json_mode is the working method."""
    chat = MagicMock()
    json_mode_runnable = MagicMock()
    json_mode_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(side_effect=[None, None])

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_mode" or method is None:
            return json_mode_runnable
        if method == "function_calling":
            return fc_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert json_mode_runnable.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_invoke_structured_chat_retries_function_calling_after_none() -> None:
    """Thinking models may skip the tool call once; retry before method fallback."""
    chat = MagicMock()
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(side_effect=[None, {"word": "OK"}])
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(
        side_effect=ValueError(
            "Provider returned empty response for json_schema format. Response object: AIMessage"
        )
    )

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        return fc_runnable

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert fc_runnable.ainvoke.await_count == 2
    json_schema_runnable.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_invoke_structured_chat_retries_empty_json_schema_once() -> None:
    """Empty json_schema output may succeed on immediate retry (thinking models)."""
    chat = MagicMock()
    json_schema_runnable = MagicMock()
    empty_err = ValueError(
        "Provider returned empty response for json_schema format. Response object: AIMessage"
    )
    json_schema_runnable.ainvoke = AsyncMock(side_effect=[empty_err, {"word": "OK"}])

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert json_schema_runnable.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_invoke_structured_chat_retries_after_empty_json_schema_response() -> None:
    """Empty json_schema output is retriable so thinking models can fall back."""
    chat = MagicMock()
    json_schema_runnable = MagicMock()
    fc_runnable = MagicMock()
    thinking_err = RuntimeError(
        "tool_choice parameter does not support being set to required in thinking mode"
    )

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        if method == "function_calling":
            return fc_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    # Prime cache: function_calling fails, json_schema succeeds.
    fc_runnable.ainvoke = AsyncMock(side_effect=thinking_err)
    json_schema_runnable.ainvoke = AsyncMock(return_value={"word": "cached"})
    await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )

    empty_err = ValueError(
        "Provider returned empty response for json_schema format. Response object: AIMessage"
    )
    json_schema_runnable.ainvoke = AsyncMock(side_effect=empty_err)
    fc_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})
    fc_calls_before = fc_runnable.ainvoke.await_count

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert fc_runnable.ainvoke.await_count == fc_calls_before + 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_structured_output_runnable_recovers_fenced_json() -> None:
    """``_StructuredOutputRunnable._parse`` strips markdown fences/prose to recover JSON.

    Port of the old ``JsonSchemaModelWrapper._parse_response`` fenced-JSON
    recovery: providers wrap json_schema output in ````` ```json ... ``` `````
    or prefix prose. The new runnable's ``_parse`` does the same recovery via
    a ``{.*}`` regex fallback when ``json.loads`` fails on the raw content.
    """
    from soothe_nano.llm.provider import ChatLitellmModel, _StructuredOutputRunnable

    model = ChatLitellmModel(model="openai/test")
    runnable = _StructuredOutputRunnable(model, response_format=None, schema=_WORD_SCHEMA)
    fenced = AIMessage(content='```json\n{\n  "word": "GOJSON"\n}\n```')
    assert runnable._parse(fenced) == {"word": "GOJSON"}

    prose = AIMessage(content='Here is the JSON: {"word": "OK"}')
    assert runnable._parse(prose) == {"word": "OK"}


@pytest.mark.asyncio
async def test_invoke_structured_chat_applies_normalize_before_validation() -> None:
    """Partial provider payloads reach normalize before jsonschema validation."""
    # Inline schema (host Veritas must not be imported from nano tests).
    schema = {
        "type": "object",
        "properties": {
            "defer": {"type": "boolean"},
            "answers": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "confidence": {"type": "number"},
        },
        "required": ["defer", "answers", "confidence"],
        "additionalProperties": False,
    }

    def _normalize(data: object) -> dict:
        if not isinstance(data, dict):
            return {"defer": False, "answers": [""], "confidence": 0.0}
        answers = data.get("answers")
        if not isinstance(answers, list) or not answers:
            answers = [""]
        conf = data.get("confidence")
        if not isinstance(conf, (int, float)):
            conf = 0.7
        return {
            "defer": bool(data.get("defer", False)),
            "answers": [str(a) for a in answers],
            "confidence": float(conf),
        }

    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(return_value={"answers": ["pushed commit to origin"]})

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    chat = MagicMock()
    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="Respond in JSON format")],
        json_schema=schema,
        schema_name="NormalizedAnswer",
        strict=True,
        methods=("json_schema",),
        normalize=_normalize,
    )
    assert out["defer"] is False
    assert out["answers"] == ["pushed commit to origin"]
    assert out["confidence"] == pytest.approx(0.7)
