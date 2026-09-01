"""`ChatLitellmModel` — a langchain `BaseChatModel` backed by litellm.

litellm routes to OpenAI, Anthropic, DashScope, oMLX, vLLM, Ollama, and
OpenRouter via the model-string prefix. `bind_tools` stores tool schemas on
the instance so `_generate`/`_agenerate` pass them directly to
`litellm.completion(tools=...)`, producing native structured `tool_calls`.
Provider quirks (thinking-token stripping, streaming self-heal, structured
output fallback) are folded in via `ProviderCapabilities`.
"""

from __future__ import annotations

import logging
import os
import random
from collections.abc import AsyncIterator, Iterator
from typing import Any

# litellm fetches a remote model-cost-map JSON from raw.githubusercontent.com
# on every import, timing out and logging a warning when offline. Pin to the
# local backup shipped with the wheel so no network fetch happens (and the
# warning is silenced). Must be set before ``import litellm``.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm

# Silence litellm's bare-print() "Give Feedback / Get Help" and "LiteLLM.Info"
# messages emitted on every exception-mapping call. With MultiModelChatModel
# failover across N instances, each failed model prints these two lines to
# stdout (bypassing the logging system), producing 2*N lines of noise.
# Mirrors litellm.router's own `litellm.suppress_debug_info = True` guard.
litellm.suppress_debug_info = True

from langchain_core.callbacks import (  # noqa: E402
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402
from pydantic import ConfigDict  # noqa: E402

from soothe_nano.llm.message import lc_to_litellm_messages  # noqa: E402
from soothe_nano.llm.registry import ProviderCapabilities  # noqa: E402
from soothe_nano.llm.thinking import ThinkingStreamFilter, strip_thinking  # noqa: E402
from soothe_nano.llm.tools import bind_tools_litellm, extract_tool_calls_from_litellm  # noqa: E402

logger = logging.getLogger(__name__)


class ChatLitellmModel(BaseChatModel):
    """langchain `BaseChatModel` adapter over litellm.

    Construct via `LLMFactory` (which resolves provider config and credentials).
    `bind_tools` returns a new instance with bound tools stored on it, so
    `_generate`/`_agenerate`/`_astream` pass them directly to litellm — no
    `RunnableBinding` indirection that could drop the `tools=` kwarg.

    Example:
        factory = LLMFactory(config)
        model = factory.create_chat_model("default")
        bound = model.bind_tools([get_weather])
    """

    model: str = "openai/gpt-4o-mini"
    api_base: str | None = None
    api_key: str | None = None
    capabilities: ProviderCapabilities = ProviderCapabilities()
    temperature: float = 0.7
    streaming: bool = True
    bound_tools: list[dict[str, Any]] = []
    bound_tool_choice: Any = None
    model_kwargs: dict[str, Any] = {}

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # ------------------------------------------------------------------
    # langchain identity
    # ------------------------------------------------------------------

    @property
    def _llm_type(self) -> str:
        return "litellm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "api_base": self.api_base,
            "temperature": self.temperature,
        }

    # ------------------------------------------------------------------
    # Tool binding — the regression fix
    # ------------------------------------------------------------------

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> ChatLitellmModel:
        """Bind tools so subsequent calls pass them to litellm directly.

        Returns a NEW `ChatLitellmModel` (not a `RunnableBinding`) with
        `bound_tools` set. This is the fix: the bound tools live on the
        adapter instance and are merged into the litellm `tools=` argument
        inside `_generate`/`_agenerate`/`_astream` — there is no
        `RunnableBinding._agenerate` dispatch that could bypass the merge.
        """
        tool_choice = kwargs.pop("tool_choice", None)
        # Sanitize tool_choice for provider compatibility (port of the old
        # ``_sanitize_tool_choice_for_compat``). Thinking-mode providers reject
        # object-form, ``"required"``, and ``True``; coerce them to ``"auto"``.
        if isinstance(tool_choice, dict):
            tool_choice = "auto"
        elif tool_choice is True:
            tool_choice = "auto"
        elif isinstance(tool_choice, str) and tool_choice in {"required", "any"}:
            tool_choice = "auto"
        wire_tools = bind_tools_litellm(tools)
        return self.model_copy(
            update={
                "bound_tools": wire_tools,
                "bound_tool_choice": tool_choice,
                "model_kwargs": {**self.model_kwargs, **kwargs},
            }
        )

    # ------------------------------------------------------------------
    # litellm invocation helpers
    # ------------------------------------------------------------------

    def _litellm_kwargs(self, **call_kwargs: Any) -> dict[str, Any]:
        """Build the kwargs dict passed to `litellm.completion`."""
        kw: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
        }
        if self.api_base:
            kw["api_base"] = self.api_base
        if self.api_key:
            kw["api_key"] = self.api_key
        if self.capabilities.max_tokens is not None:
            kw["max_tokens"] = self.capabilities.max_tokens
        # Bound tools — passed directly so litellm emits native tool_calls.
        if self.bound_tools:
            kw["tools"] = self.bound_tools
            if self.bound_tool_choice is not None:
                kw["tool_choice"] = self.bound_tool_choice
        kw.update(self.model_kwargs)
        kw.update(call_kwargs)
        return kw

    def _strip_thinking_from_message(self, message: AIMessage) -> AIMessage:
        """Strip inline thinking blocks from an AIMessage's text content."""
        if not self.capabilities.hide_thinking_tokens:
            return message
        content = message.content
        if isinstance(content, str) and content:
            stripped = strip_thinking(content, logger=logger)
            if stripped != content:
                return AIMessage(
                    content=stripped,
                    tool_calls=message.tool_calls,
                    additional_kwargs=message.additional_kwargs,
                    id=getattr(message, "id", None),
                )
        return message

    @staticmethod
    def _is_no_generations_error(exc: BaseException) -> bool:
        """Detect the generic 'No generations found in stream' error."""
        return "No generations found in stream" in str(exc)

    # ------------------------------------------------------------------
    # Non-streaming generation
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Non-streaming generation via `litellm.completion`."""
        llm_messages = lc_to_litellm_messages(messages)
        call_kwargs = self._litellm_kwargs(**kwargs)
        if stop:
            call_kwargs["stop"] = stop
        try:
            response = litellm.completion(messages=llm_messages, **call_kwargs)
        except Exception as exc:
            logger.error("litellm.completion failed: %s", exc)
            raise
        choice = response.choices[0].message
        ai_msg = self._strip_thinking_from_message(extract_tool_calls_from_litellm(choice))
        # Token usage — surfaced via ChatResult.llm_output for Langfuse callbacks.
        llm_output: dict[str, Any] = {}
        usage = getattr(response, "usage", None)
        if usage is not None:
            llm_output["token_usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        return ChatResult(generations=[ChatGeneration(message=ai_msg)], llm_output=llm_output)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async non-streaming generation via `litellm.acompletion`."""
        llm_messages = lc_to_litellm_messages(messages)
        call_kwargs = self._litellm_kwargs(**kwargs)
        if stop:
            call_kwargs["stop"] = stop
        try:
            response = await litellm.acompletion(messages=llm_messages, **call_kwargs)
        except Exception as exc:
            logger.error("litellm.acompletion failed: %s", exc)
            raise
        choice = response.choices[0].message
        ai_msg = self._strip_thinking_from_message(extract_tool_calls_from_litellm(choice))
        llm_output: dict[str, Any] = {}
        usage = getattr(response, "usage", None)
        if usage is not None:
            llm_output["token_usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        return ChatResult(generations=[ChatGeneration(message=ai_msg)], llm_output=llm_output)

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Streaming generation via `litellm.completion(stream=True)`.

        With a runtime auto-fallback: if the streaming path raises "No
        generations found in stream" (a server that ignores `stream: true`
        and returns non-SSE JSON), retry non-streaming and emit the result as
        a single chunk. This self-heals providers like vLLM-Metal without
        requiring `streaming: false` in config.
        """
        if not self.streaming or not self.capabilities.streaming:
            result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            for gen in result.generations:
                yield ChatGenerationChunk(message=gen.message)
            return
        llm_messages = lc_to_litellm_messages(messages)
        call_kwargs = self._litellm_kwargs(stream=True, **kwargs)
        if stop:
            call_kwargs["stop"] = stop
        filt = (
            ThinkingStreamFilter(logger=logger) if self.capabilities.hide_thinking_tokens else None
        )
        try:
            stream = litellm.completion(messages=llm_messages, **call_kwargs)
            for chunk in stream:
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                tool_call_deltas = getattr(delta, "tool_calls", None)
                if text and filt is not None:
                    text = filt.feed(text)
                if text or tool_call_deltas:
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(
                            content=text,
                            tool_call_chunks=_normalize_tool_call_chunks(tool_call_deltas),
                        )
                    )
            if filt is not None:
                tail = filt.finalize()
                if tail:
                    yield ChatGenerationChunk(message=AIMessageChunk(content=tail))
        except Exception as exc:
            if self._is_no_generations_error(exc):
                logger.warning(
                    "litellm streaming returned no generations; auto-falling back to _generate"
                )
                result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                for gen in result.generations:
                    yield ChatGenerationChunk(message=gen.message)
                return
            raise

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Async streaming via `litellm.acompletion(stream=True)`."""
        if not self.streaming or not self.capabilities.streaming:
            result = await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
            for gen in result.generations:
                yield ChatGenerationChunk(message=gen.message)
            return
        llm_messages = lc_to_litellm_messages(messages)
        call_kwargs = self._litellm_kwargs(stream=True, **kwargs)
        if stop:
            call_kwargs["stop"] = stop
        filt = (
            ThinkingStreamFilter(logger=logger) if self.capabilities.hide_thinking_tokens else None
        )
        try:
            stream = await litellm.acompletion(messages=llm_messages, **call_kwargs)
            async for chunk in stream:
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                tool_call_deltas = getattr(delta, "tool_calls", None)
                if text and filt is not None:
                    text = filt.feed(text)
                if text or tool_call_deltas:
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(
                            content=text,
                            tool_call_chunks=_normalize_tool_call_chunks(tool_call_deltas),
                        )
                    )
            if filt is not None:
                tail = filt.finalize()
                if tail:
                    yield ChatGenerationChunk(message=AIMessageChunk(content=tail))
        except Exception as exc:
            if self._is_no_generations_error(exc):
                logger.warning(
                    "litellm async streaming returned no generations; auto-falling back to _agenerate"
                )
                result = await self._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
                for gen in result.generations:
                    yield ChatGenerationChunk(message=gen.message)
                return
            raise

    # ------------------------------------------------------------------
    # Structured output
    # ------------------------------------------------------------------

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Structured output via litellm `response_format` or instructor.

        For providers that honor `json_schema` natively, build the
        `response_format` payload. For providers that reject it (DashScope
        GLM/Kimi — `capabilities.supports_json_schema=False`), fall back to
        the instructor pattern (litellm + instructor function-calling).
        """
        from soothe_nano.llm.schema_wire import (
            build_json_schema_response_format,
            resolve_schema_name,
            validate_response_schema,
        )

        if isinstance(schema, dict):
            wire_schema = validate_response_schema(schema)
            name = resolve_schema_name(wire_schema, kwargs.pop("schema_name", None))
        else:
            wire_schema = schema.model_json_schema()
            name = kwargs.pop("schema_name", None) or getattr(schema, "__name__", "output")

        strict = kwargs.pop("strict", True)

        if self.capabilities.supports_json_schema:
            response_format = build_json_schema_response_format(
                wire_schema, name=name, strict=strict
            )
            return _StructuredOutputRunnable(self, response_format=response_format, schema=schema)
        # Fallback: instructor over the litellm adapter.
        return _StructuredOutputRunnable(self, response_format=None, schema=schema)


class MultiModelChatModel(BaseChatModel):
    """A ``BaseChatModel`` wrapping a pool of ``ChatLitellmModel`` instances.

    Each call picks a random model; on failure, retries the next untried
    model. Failover is per-call (no persistent circuit breaker). For
    streaming, failover applies only before the first chunk — mid-stream
    errors propagate.
    """

    models: list[ChatLitellmModel] = []
    temperature: float = 0.7
    model_kwargs: dict[str, Any] = {}

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "litellm-multi"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        params: dict[str, Any] = dict(self.models[0]._identifying_params) if self.models else {}
        params["pool_size"] = len(self.models)
        return params

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Capabilities of the first (primary) model in the pool."""
        return self.models[0].capabilities if self.models else ProviderCapabilities()

    # ------------------------------------------------------------------
    # Failover helpers
    # ------------------------------------------------------------------

    def _shuffled_models(self) -> list[ChatLitellmModel]:
        """Return a shuffled copy of the model pool."""
        pool = list(self.models)
        random.shuffle(pool)
        return pool

    @staticmethod
    def _model_spec(model: ChatLitellmModel) -> str:
        """Extract the ``provider:model`` spec from a model's identifying params."""
        return str(model._identifying_params.get("model", "unknown"))

    # ------------------------------------------------------------------
    # Non-streaming generation with failover
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Non-streaming generation with random selection and failover."""
        last_exc: Exception | None = None
        for model in self._shuffled_models():
            spec = self._model_spec(model)
            try:
                return model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                last_exc = exc
                logger.warning("MultiModelChatModel: model '%s' failed in _generate: %s", spec, exc)
        msg = "MultiModelChatModel: all models in pool failed"
        raise RuntimeError(msg) from last_exc

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async non-streaming generation with random selection and failover."""
        last_exc: Exception | None = None
        for model in self._shuffled_models():
            spec = self._model_spec(model)
            try:
                return await model._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "MultiModelChatModel: model '%s' failed in _agenerate: %s", spec, exc
                )
        msg = "MultiModelChatModel: all models in pool failed"
        raise RuntimeError(msg) from last_exc

    # ------------------------------------------------------------------
    # Streaming generation with pre-stream failover
    # ------------------------------------------------------------------

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Streaming with pre-first-chunk failover."""
        last_exc: Exception | None = None
        for model in self._shuffled_models():
            spec = self._model_spec(model)
            try:
                started = False
                for chunk in model._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                    started = True
                    yield chunk
                return  # Success — stop trying other models.
            except Exception as exc:
                if started:
                    raise  # Mid-stream error: cannot retry.
                last_exc = exc
                logger.warning(
                    "MultiModelChatModel: model '%s' failed before streaming: %s",
                    spec,
                    exc,
                )
        msg = "MultiModelChatModel: all models in pool failed"
        raise RuntimeError(msg) from last_exc

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Async streaming with failover before the first chunk."""
        last_exc: Exception | None = None
        for model in self._shuffled_models():
            spec = self._model_spec(model)
            try:
                started = False
                async for chunk in model._astream(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                ):
                    started = True
                    yield chunk
                return  # Success.
            except Exception as exc:
                if started:
                    raise
                last_exc = exc
                logger.warning(
                    "MultiModelChatModel: model '%s' failed before async streaming: %s",
                    spec,
                    exc,
                )
        msg = "MultiModelChatModel: all models in pool failed"
        raise RuntimeError(msg) from last_exc

    # ------------------------------------------------------------------
    # Tool binding and structured output
    # ------------------------------------------------------------------

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> MultiModelChatModel:
        """Bind tools to every model in the pool, returning a new wrapper."""
        bound_models = [m.bind_tools(tools, **kwargs) for m in self.models]
        return self.model_copy(update={"models": bound_models})

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Structured output via the pool's first-model capabilities.

        The ``_StructuredOutputRunnable`` wraps this model so
        ``invoke``/``ainvoke`` route through failover.
        """
        from soothe_nano.llm.schema_wire import (
            build_json_schema_response_format,
            resolve_schema_name,
            validate_response_schema,
        )

        if isinstance(schema, dict):
            wire_schema = validate_response_schema(schema)
            name = resolve_schema_name(wire_schema, kwargs.pop("schema_name", None))
        else:
            wire_schema = schema.model_json_schema()
            name = kwargs.pop("schema_name", None) or getattr(schema, "__name__", "output")

        strict = kwargs.pop("strict", True)

        if self.capabilities.supports_json_schema:
            response_format = build_json_schema_response_format(
                wire_schema, name=name, strict=strict
            )
            return _StructuredOutputRunnable(self, response_format=response_format, schema=schema)
        return _StructuredOutputRunnable(self, response_format=None, schema=schema)


class _StructuredOutputRunnable:
    """Runnable that enforces structured output on top of a `ChatLitellmModel`.

    For `json_schema`-capable providers, attaches `response_format` to
    the litellm call. For others, parses the JSON text response into the
    pydantic schema (instructor-style fallback).

    Invokes the public `ChatLitellmModel.invoke` / `ainvoke` path so
    LangChain callbacks (Langfuse generations, token usage) fire. `config`
    is never forwarded into `_generate`/`litellm.completion` — those
    kwargs are JSON-serialized and cannot hold live callback handlers.
    """

    _LC_CALL_KEYS = frozenset({"config", "callbacks", "tags", "metadata", "run_name", "run_id"})

    def __init__(
        self,
        model: ChatLitellmModel,
        response_format: dict[str, Any] | None,
        schema: Any,
    ) -> None:
        self._model = model
        self._response_format = response_format
        self._schema = schema

    @classmethod
    def _split_call_kwargs(
        cls, config: Any | None, kwargs: dict[str, Any]
    ) -> tuple[Any | None, dict[str, Any]]:
        """Keep LangChain `config` off the litellm HTTP kwargs.

        `invoke_structured_chat` / `ainvoke_structured_traced` pass a
        RunnableConfig (callbacks, tags, metadata). `_generate` forwards
        every remaining kwarg into `litellm.completion`, which JSON-serializes
        the body — live callback handlers are not serializable.
        """
        call_kwargs = dict(kwargs)
        if config is None:
            config = call_kwargs.pop("config", None)
        else:
            call_kwargs.pop("config", None)
        for key in cls._LC_CALL_KEYS:
            call_kwargs.pop(key, None)
        return config, call_kwargs

    def _enrich_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        out = dict(kwargs)
        if self._response_format is not None:
            out["response_format"] = self._response_format
        return out

    @staticmethod
    def _flatten_callback_handlers(callbacks: Any) -> list[Any]:
        """Flatten LangChain `callbacks` (list or `CallbackManager`) to handlers.

        `callbacks` in a RunnableConfig may be a list of handlers, `None`,
        or a LangChain `CallbackManager` object (e.g. an
        `AsyncCallbackManager` injected by a LangGraph node). A `CallbackManager`
        is not iterable, so `list(callbacks)` raises `TypeError`; its handlers
        live under `.handlers` and `.inheritable_handlers`. Flatten every shape
        to a plain handler list for membership checks.
        """
        if callbacks is None:
            return []
        if isinstance(callbacks, (list, tuple)):
            out: list[Any] = []
            for item in callbacks:
                out.extend(_StructuredOutputRunnable._flatten_callback_handlers(item))
            return out
        nested = getattr(callbacks, "handlers", None)
        if isinstance(nested, (list, tuple)):
            out = []
            for h in nested:
                out.extend(_StructuredOutputRunnable._flatten_callback_handlers(h))
            inheritable = getattr(callbacks, "inheritable_handlers", None)
            if isinstance(inheritable, (list, tuple)):
                for h in inheritable:
                    for item in _StructuredOutputRunnable._flatten_callback_handlers(h):
                        if item not in out:
                            out.append(item)
            return out
        return [callbacks]

    @staticmethod
    def _config_for_model(config: Any) -> Any:
        """Attach the shared token-usage handler when the caller omitted it.

        `invoke_structured_chat` already merges the handler; re-merging
        would double-count tokens. Bare `with_structured_output().ainvoke`
        still needs the handler so loop accumulation works.
        """
        from soothe_nano.llm.observability import (
            get_llm_token_usage_callback_handler,
            merge_token_usage_callbacks,
        )

        handler = get_llm_token_usage_callback_handler()
        if isinstance(config, dict):
            callbacks = _StructuredOutputRunnable._flatten_callback_handlers(
                config.get("callbacks")
            )
            if handler in callbacks:
                return config
            return merge_token_usage_callbacks(config)
        if config is None:
            return merge_token_usage_callbacks(None)
        return config

    def invoke(self, messages: list[BaseMessage], config: Any | None = None, **kwargs: Any) -> Any:
        config, call_kwargs = self._split_call_kwargs(config, kwargs)
        msg = self._model.invoke(
            messages,
            config=self._config_for_model(config),
            **self._enrich_kwargs(call_kwargs),
        )
        return self._parse(msg)

    async def ainvoke(
        self, messages: list[BaseMessage], config: Any | None = None, **kwargs: Any
    ) -> Any:
        config, call_kwargs = self._split_call_kwargs(config, kwargs)
        msg = await self._model.ainvoke(
            messages,
            config=self._config_for_model(config),
            **self._enrich_kwargs(call_kwargs),
        )
        return self._parse(msg)

    def _parse(self, msg: AIMessage) -> Any:
        """Parse the AI message content into the pydantic schema."""
        import json

        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Best-effort: strip markdown fences and retry.
            import re

            m = re.search(r"\{.*\}", content, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        if isinstance(self._schema, dict):
            return data
        return self._schema.model_validate(data)


def _normalize_tool_call_chunks(deltas: Any) -> list[dict[str, Any]]:
    """Normalize litellm streaming `tool_calls` deltas to langchain format.

    Streaming tool-call deltas arrive as `[{index, id, function: {name,
    arguments}, type}]` fragments. langchain's `AIMessageChunk.tool_call_chunks`
    expects `[{index, id, name, args, type}]` (args is the partial JSON
    string). This flattens the nested `function` dict.
    """
    if not deltas:
        return []
    out: list[dict[str, Any]] = []
    for d in deltas:
        if isinstance(d, dict):
            fn = d.get("function", {})
            out.append(
                {
                    "index": d.get("index", 0),
                    "id": d.get("id", ""),
                    "name": fn.get("name", ""),
                    "args": fn.get("arguments", ""),
                    "type": d.get("type", "tool_call"),
                }
            )
        else:
            fn = getattr(d, "function", None)
            out.append(
                {
                    "index": getattr(d, "index", 0),
                    "id": getattr(d, "id", ""),
                    "name": getattr(fn, "name", "") if fn else "",
                    "args": getattr(fn, "arguments", "") if fn else "",
                    "type": "tool_call",
                }
            )
    return out


__all__ = ["ChatLitellmModel", "MultiModelChatModel"]
