"""Generic model wrappers for limited OpenAI-compatible providers.

These wrappers adapt non-standard OpenAI-compatible endpoints (DashScope, oMLX,
LMStudio, vLLM) that may:
- Only accept string ``tool_choice`` values, not object format
- Return structured JSON in ``reasoning_content`` or content block lists
- Return empty ``content`` when ``json_schema`` is used with thinking models
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import jsonschema
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from soothe_nano.utils.llm.response_text import text_from_message_content
from soothe_nano.utils.llm.schema_wire import (
    build_json_schema_response_format,
    validate_response_schema,
)
from soothe_nano.utils.llm.thinking_filter import ThinkingStreamFilter, strip_thinking
from soothe_nano.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def _sanitize_tool_choice_for_compat(tool_choice: Any) -> Any:
    """Normalize tool_choice for limited OpenAI-compatible providers.

    Some "thinking mode" providers reject both object-form and ``"required"``
    tool choice. For compatibility, coerce those variants to ``"auto"``.
    """
    if isinstance(tool_choice, dict):
        return "auto"
    if isinstance(tool_choice, str) and tool_choice in {"required", "any"}:
        return "auto"
    # LangChain may pass bool and later coerce True -> "required".
    if tool_choice is True:
        return "auto"
    return tool_choice


def _strip_json_text(raw: str) -> str:
    """Normalize model output to a JSON-parseable string.

    Local OpenAI-compatible providers (oMLX/GLM/gemma) sometimes wrap
    ``json_schema`` output in a markdown fence (````` ```json ... ``` `````)
    or prefix it with prose even though ``response_format`` requested strict
    JSON. Strip the fence and, if prose remains, slice to the outermost JSON
    object so ``json.loads`` succeeds.
    """
    text = (raw or "").strip()
    if not text:
        return text
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start > 0:
        # Leading prose before the first object — slice it off.
        text = text[start:]
    return text


# --- thinking-token chunk/result helpers -------------------------------------
#
# ``OpenAICompatModelWrapper`` sits between a local OpenAI-compatible provider
# and the rest of the system, so it is the natural place to strip inline
# ``<think>...`` blocks emitted by reasoning models (DeepSeek-R1, QwQ, GLM).
# The stateless :func:`strip_thinking` is used for fully-assembled non-streaming
# responses (complete blocks only); the stateful
# :class:`ThinkingStreamFilter` buffers partial ``<think`` / ``</think``
# fragments split across streaming chunk boundaries so no tag fragments leak.


def _chunk_text(chunk: Any) -> str | None:
    """Return the text delta carried by a streamed *chunk*, or ``None``.

    LangChain streaming yields :class:`ChatGenerationChunk` objects whose
    ``.message`` is an :class:`AIMessageChunk` with a string ``content`` (the
    delta text). Chunks that carry no textual delta (tool-call deltas, empty
    tail chunks, or the plain strings used by the contract test) return
    ``None`` so callers pass them through unchanged.
    """
    msg = getattr(chunk, "message", None)
    if msg is None:
        return None
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    return None


def _set_chunk_text(chunk: Any, text: str) -> Any:
    """Replace the textual delta on *chunk* in place and return it.

    Falls back to returning *text* directly when *chunk* does not expose a
    ``message.content`` slot (e.g. plain strings in the contract test), so the
    filtered text still reaches the consumer.
    """
    msg = getattr(chunk, "message", None)
    if msg is not None and hasattr(msg, "content"):
        msg.content = text
        return chunk
    return text


def _make_text_tail_chunk(text: str) -> Any:
    """Build a minimal text-only tail chunk flushing leftover filtered text."""
    try:
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        return ChatGenerationChunk(message=AIMessageChunk(content=text))
    except Exception:
        # Never let a langchain import failure break the stream's tail.
        logger.debug("thinking tail-chunk construction failed", exc_info=True)
        return text


def _strip_thinking_from_chat_result(result: Any) -> Any:
    """Strip complete thinking blocks from every message in a non-streaming result.

    Handles both result shapes LangChain uses:

    - :class:`~langchain_core.outputs.ChatResult` (``generations`` is a flat
      ``list[ChatGeneration]``), returned by ``_generate``.
    - :class:`~langchain_core.outputs.LLMResult` (``generations`` is a nested
      ``list[list[ChatGeneration]]``), surfaced via callbacks.

    Each generation's ``message.content`` is stripped in place when it is text.
    The "record before strip" rule is honoured by :func:`strip_thinking` itself
    (it logs each block at ``DEBUG`` before removal).
    """
    generations = getattr(result, "generations", None)
    if not generations:
        return result
    for entry in generations:
        # LLMResult rows are lists of ChatGeneration; ChatResult entries are
        # a single ChatGeneration. Normalize so both shapes share one path.
        gens = entry if isinstance(entry, list) else [entry]
        for gen in gens:
            msg = getattr(gen, "message", None)
            if msg is None:
                continue
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content:
                filtered = strip_thinking(content)
                if filtered != content:
                    msg.content = filtered
    return result


def _build_json_schema_model_wrapper(
    model: BaseChatModel,
    schema: Any,
    *,
    schema_name: str | None,
    strict: bool,
) -> JsonSchemaModelWrapper:
    """Build ``JsonSchemaModelWrapper`` for wire dict or Pydantic schema."""
    if isinstance(schema, dict):
        wire_schema = validate_response_schema(schema)
        from soothe_nano.utils.llm.schema_wire import resolve_schema_name

        name = resolve_schema_name(wire_schema, schema_name)
        response_format = build_json_schema_response_format(
            wire_schema,
            name=name,
            strict=bool(strict),
        )
        return JsonSchemaModelWrapper(
            model,
            response_format,
            wire_schema,
            strict=bool(strict),
        )

    json_schema = schema.model_json_schema()
    name = (
        schema_name.strip()
        if isinstance(schema_name, str) and schema_name.strip()
        else schema.__name__
    )
    response_format = build_json_schema_response_format(
        json_schema,
        name=name,
        strict=bool(strict),
    )
    return JsonSchemaModelWrapper(
        model,
        response_format,
        schema,
        strict=bool(strict),
    )


def _extract_json_str_from_response(response: Any) -> str:
    """Extract JSON text from an AIMessage-like provider response."""
    # Check content field first (primary for AIMessage-like objects)
    if hasattr(response, "content"):
        if response.content:
            return _strip_json_text(text_from_message_content(response.content))
        # content exists but is empty — check reasoning_content before giving up
        if hasattr(response, "additional_kwargs"):
            rc = response.additional_kwargs.get("reasoning_content")
            if rc:
                logger.debug("JSON found in reasoning_content field (additional_kwargs)")
                return _strip_json_text(str(rc))
        # AIMessage-like object with empty content and no reasoning_content → empty
        return ""
    # Fallback for non-AIMessage response types (e.g., raw string)
    return _strip_json_text(str(response))


def _coerce_structured_json(
    json_dict: dict[str, Any],
    schema: Any,
    *,
    json_schema: dict[str, Any] | None = None,
    strict: bool = True,
) -> Any:
    """Validate parsed JSON against Pydantic or wire JSON Schema."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_validate(json_dict)
    if isinstance(schema, dict):
        wire_schema = json_schema if json_schema is not None else schema
        if strict:
            jsonschema.validate(instance=json_dict, schema=wire_schema)
        return json_dict
    msg = f"unsupported structured output schema type: {type(schema).__name__}"
    raise TypeError(msg)


class JsonSchemaModelWrapper(Runnable):
    """Wrapper that injects json_schema response_format and parses JSON output.

    Limited OpenAI providers require response_format={"type": "json_schema"} not {"type": "json_object"}.
    Unlike langchain's built-in structured output, we manually parse the JSON response
    into a Pydantic object, checking both content and reasoning_content fields.

    Handles providers that return structured JSON in reasoning_content field:
    - LMStudio, MLXServer, GLM deployments with thinking tokens

    Args:
        model: The base model to wrap.
        response_format: The json_schema format dict to inject.
        schema: Pydantic model class or client JSON Schema dict for parsing.
    """

    def __init__(
        self,
        model: BaseChatModel,
        response_format: dict[str, Any],
        schema: Any,
        *,
        strict: bool = True,
    ) -> None:
        """Initialize the wrapper.

        Args:
            model: The base model to wrap.
            response_format: The json_schema format dict to inject on invoke.
            schema: Pydantic model or JSON Schema dict for validation.
            strict: When True, validate dict outputs with jsonschema.
        """
        self._model = model
        self._response_format = response_format
        self._schema = schema
        self._strict = strict
        self._wire_json_schema = schema if isinstance(schema, dict) else None

    def _parse_response(self, response: Any) -> Any:
        json_str = _extract_json_str_from_response(response)
        if not json_str or json_str.strip() == "":
            raise ValueError(
                f"Provider returned empty response for json_schema format. "
                f"Response object: {type(response).__name__}"
            )
        logger.debug(
            "Provider response for json_schema: content='%s', reasoning_content='%s'",
            preview_first(str(response.content) if hasattr(response, "content") else "", 100),
            preview_first(
                str(response.additional_kwargs.get("reasoning_content", ""))
                if hasattr(response, "additional_kwargs")
                else "",
                100,
            ),
        )
        from soothe_nano.utils.json_parsing import _load_llm_json_dict

        json_dict = _load_llm_json_dict(json_str)
        return _coerce_structured_json(
            json_dict,
            self._schema,
            json_schema=self._wire_json_schema,
            strict=self._strict,
        )

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        """Inject response_format, invoke model, and parse JSON response.

        Args:
            input: Messages or prompt to send.
            config: Runnable config (callbacks, metadata, Langfuse, etc.).
            **kwargs: Additional invoke parameters.

        Returns:
            Parsed Pydantic object from the JSON response.
        """
        kwargs["response_format"] = self._response_format
        response = self._model.invoke(input, config=config, **kwargs)

        try:
            return self._parse_response(response)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse JSON response: %s\n"
                "Response content: '%s'\n"
                "Response reasoning_content: '%s'\n"
                "Full response: %s",
                e,
                preview_first(
                    str(response.content) if hasattr(response, "content") else "N/A", 200
                ),
                preview_first(
                    str(response.additional_kwargs.get("reasoning_content", "N/A"))
                    if hasattr(response, "additional_kwargs")
                    else "N/A",
                    200,
                ),
                response,
            )
            raise
        except Exception as e:
            logger.error(
                "Failed to process provider response: %s\nResponse: %s",
                e,
                response,
            )
            raise

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        """Async version of invoke with response_format injection and JSON parsing.

        Args:
            input: Messages or prompt to send.
            config: Runnable config (callbacks, metadata, Langfuse, etc.).
            **kwargs: Additional invoke parameters.

        Returns:
            Parsed Pydantic object from the JSON response.
        """
        kwargs["response_format"] = self._response_format
        response = await self._model.ainvoke(input, config=config, **kwargs)

        try:
            return self._parse_response(response)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse JSON response: %s\n"
                "Response content: '%s'\n"
                "Response reasoning_content: '%s'\n"
                "Full response: %s",
                e,
                preview_first(
                    str(response.content) if hasattr(response, "content") else "N/A", 200
                ),
                preview_first(
                    str(response.additional_kwargs.get("reasoning_content", "N/A"))
                    if hasattr(response, "additional_kwargs")
                    else "N/A",
                    200,
                ),
                response,
            )
            raise
        except Exception as e:
            logger.error(
                "Failed to process provider response: %s\nResponse: %s",
                e,
                response,
            )
            raise

    def __getattr__(self, name: str) -> Any:
        """Delegate any other attributes to the wrapped model."""
        return getattr(self._model, name)


class OpenAICompatModelWrapper(BaseChatModel):
    """Route structured-output methods for limited OpenAI-compatible providers.

    - ``function_calling`` / ``json_mode``: delegate to the inner LangChain model.
    - ``json_schema``: ``JsonSchemaModelWrapper`` for ``reasoning_content`` parsing.
    - ``bind_tools``: sanitize object-form ``tool_choice`` to string values.
    """

    def __init__(
        self,
        model: BaseChatModel,
        provider_name: str = "unknown",
        *,
        hide_thinking_tokens: bool = True,
        streaming: bool = True,
    ) -> None:
        """Initialize the wrapper.

        Args:
            model: The original BaseChatModel to wrap.
            provider_name: Provider name for logging purposes.
            hide_thinking_tokens: When True (default), strip inline
                ``</think>...<thinking>`` reasoning blocks from this provider's text output
                so chain-of-thought never surfaces to the agent/UI. Passed
                through from ``SootheConfig.hide_thinking_tokens`` by the
                ``LLMFactory``; the actual stripping lives in
                ``soothe_nano.utils.llm.thinking_filter``.
            streaming: When True (default), ``_stream``/``_astream`` delegate to
                the wrapped model's streaming path. When False, they fall back
                to the non-streaming ``_generate``/``_agenerate`` path and emit
                the result as a single ``ChatGenerationChunk``. Required for
                OpenAI-compatible servers whose streaming endpoint is broken
                (e.g. vLLM-Metal prototype, which ignores ``stream: true``).
        """
        self._model = model
        self._provider_name = provider_name
        self._hide_thinking_tokens = hide_thinking_tokens
        self._streaming = streaming

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Structured output with provider-specific method routing.

        Limited OpenAI providers differ by method:
        - ``function_calling`` / ``json_mode``: delegate to the inner model so
          thinking models (Kimi, MiniMax) can return tool args or json_object
          output instead of empty ``content`` with reasoning tokens only.
        - ``json_schema``: use ``JsonSchemaModelWrapper`` which injects
          ``response_format`` and parses ``reasoning_content`` (oMLX, GLM).

        Args:
            schema: Pydantic model class or client JSON Schema dict.
            **kwargs: ``schema_name``, ``strict``, and method (intercepted).

        Returns:
            JsonSchemaModelWrapper for ``json_schema``; inner runnable otherwise.
        """
        method = kwargs.pop("method", "json_mode")
        schema_name = kwargs.pop("schema_name", None)
        strict = kwargs.pop("strict", True)

        if method in ("function_calling", "json_mode"):
            delegate_kwargs: dict[str, Any] = {"method": method, **kwargs}
            if schema_name is not None:
                delegate_kwargs["schema_name"] = schema_name
            if method == "function_calling":
                delegate_kwargs["strict"] = strict
                sanitized_tool_choice = _sanitize_tool_choice_for_compat(kwargs.get("tool_choice"))
                if sanitized_tool_choice != kwargs.get("tool_choice"):
                    logger.debug(
                        "OpenAICompatModelWrapper sanitizing incompatible tool_choice=%r for structured output (provider=%s)",
                        kwargs.get("tool_choice"),
                        self._provider_name,
                    )
                    delegate_kwargs["tool_choice"] = sanitized_tool_choice
            # json_mode: omit strict — LangChain rejects it; invoke_structured_chat post-validates.
            return self._model.with_structured_output(schema, **delegate_kwargs)

        # json_schema (explicit) — JsonSchemaModelWrapper for reasoning_content
        try:
            return _build_json_schema_model_wrapper(
                self._model,
                schema,
                schema_name=schema_name,
                strict=strict,
            )
        except Exception:
            logger.debug(
                "Failed to convert schema to json_schema format, falling back",
                exc_info=True,
            )
            return self._model.with_structured_output(
                schema,
                method=method,
                schema_name=schema_name,
                strict=strict,
                **kwargs,
            )

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
        """Intercept tool_choice parameter for limited providers.

        Coerces incompatible values (object-form and ``"required"``) to
        ``"auto"`` for provider compatibility.

        Args:
            tools: List of tool definitions.
            **kwargs: Additional parameters (tool_choice intercepted).

        Returns:
            Model with sanitized tool_choice.
        """
        # Intercept tool_choice parameter
        if "tool_choice" in kwargs:
            sanitized_tool_choice = _sanitize_tool_choice_for_compat(kwargs["tool_choice"])
            if sanitized_tool_choice != kwargs["tool_choice"]:
                logger.debug(
                    "OpenAICompatModelWrapper sanitizing incompatible tool_choice=%r (provider=%s)",
                    kwargs["tool_choice"],
                    self._provider_name,
                )
                kwargs["tool_choice"] = sanitized_tool_choice

        return self._model.bind_tools(tools, **kwargs)

    # Delegate all BaseChatModel methods to the wrapped model

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate generation to wrapped model.

        When ``hide_thinking_tokens`` is set, complete inline ``<think>``/
        ``<thinking>``/``<reasoning>`` blocks are stripped from each returned
        message's text content (reasoning is logged at ``DEBUG`` first via
        :func:`strip_thinking`).
        """
        result = self._model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        if self._hide_thinking_tokens:
            _strip_thinking_from_chat_result(result)
        return result

    async def _agenerate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate async generation to wrapped model with thinking stripping."""
        result = await self._model._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )
        if self._hide_thinking_tokens:
            _strip_thinking_from_chat_result(result)
        return result

    def _stream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate streaming to wrapped model with thinking-token filtering.

        When ``hide_thinking_tokens`` is set, each chunk's text delta is fed
        through a :class:`ThinkingStreamFilter` so partial ``<think`` /
        ``</think`` fragments split across chunk boundaries are buffered and
        never leak; any final leftover text is flushed as a tail chunk.
        Chunks with no textual delta (tool calls, empty chunks, plain strings)
        pass through unchanged.
        """
        gen = self._model._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
        if not self._hide_thinking_tokens:
            yield from gen
            return
        filt = ThinkingStreamFilter()
        for chunk in gen:
            text = _chunk_text(chunk)
            if text is None:
                yield chunk
                continue
            safe = filt.feed(text)
            if safe:
                yield _set_chunk_text(chunk, safe)
            else:
                # Filter swallowed this chunk's text; drop it so the partial
                # tag fragment it carried does not surface.
                continue
        tail = filt.finalize()
        if tail:
            yield _make_text_tail_chunk(tail)

    async def _astream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate async streaming to wrapped model with thinking filtering.

        ``BaseChatModel._astream`` is an async generator (it ``yield``s
        chunks). We must mirror that contract — ``yield`` each chunk from the
        wrapped model rather than ``return``-ing the generator, or langchain's
        ``astream`` will hit ``async for chunk in <coroutine>`` and fail with
        ``'async for' requires an object with __aiter__``.

        When ``hide_thinking_tokens`` is set, each chunk's text delta is fed
        through a :class:`ThinkingStreamFilter` (one per stream) so partial
        ``<think`` / ``</think`` fragments split across chunk boundaries are
        buffered and never leak; leftover text is flushed as a tail chunk at
        end-of-stream. Chunks with no textual delta pass through unchanged.
        """
        agen = self._model._astream(messages, stop=stop, run_manager=run_manager, **kwargs)
        if not self._hide_thinking_tokens:
            async for chunk in agen:
                yield chunk
            return
        filt = ThinkingStreamFilter()
        async for chunk in agen:
            text = _chunk_text(chunk)
            if text is None:
                yield chunk
                continue
            safe = filt.feed(text)
            if safe:
                yield _set_chunk_text(chunk, safe)
            else:
                continue
        tail = filt.finalize()
        if tail:
            yield _make_text_tail_chunk(tail)

    @property
    def _llm_type(self) -> str:
        """Return LLM type from wrapped model."""
        return getattr(self._model, "_llm_type", "unknown")

    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Return identifying params from wrapped model."""
        return getattr(self._model, "_identifying_params", {})

    @property
    def _model_name(self) -> str:
        """Return model name from wrapped model."""
        return getattr(self._model, "_model_name", "unknown")

    def __getattr__(self, name: str) -> Any:
        """Delegate any other attributes to the wrapped model."""
        return getattr(self._model, name)
