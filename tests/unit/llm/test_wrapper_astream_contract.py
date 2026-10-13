"""Regression test for ``ChatLitellmModel._astream`` contract.

``BaseChatModel._astream`` is an async generator (it ``yield``s chunks); the
public ``astream`` iterates it with ``async for chunk in self._astream(...)``.
An earlier wrapper implementation ``return await self._model._astream(...)``
made ``_astream`` a value-returning coroutine, so ``async for chunk in
<coroutine>`` raised ``'async for' requires an object with __aiter__`` (direct
LLM turns timed out).

The unified ``ChatLitellmModel._astream`` is defined as ``async def ... yield``,
so it is an async generator by construction. These tests assert that contract
without exercising the litellm network call.
"""

from __future__ import annotations

import asyncio
import inspect

from langchain_core.messages import HumanMessage

from soothe_nano.llm.provider import ChatLitellmModel


def _make_model() -> ChatLitellmModel:
    """A minimal model whose ``_astream`` is the real (un-mocked) method."""
    return ChatLitellmModel(model="openai/test-model", streaming=False)


def test_astream_is_async_generator_function() -> None:
    """``_astream`` must be an async generator function (``yield`` inside ``async def``)."""
    assert inspect.isasyncgenfunction(ChatLitellmModel._astream), (
        "_astream must be an async generator function (use yield, not return await)"
    )


def test_astream_call_returns_async_iterator() -> None:
    """Calling ``_astream`` must return an async iterator, not a value coroutine."""
    model = _make_model()
    result = model._astream(messages=[HumanMessage(content="hi")])  # noqa: SLF001
    # Async generators implement __aiter__; coroutines do not.
    assert hasattr(result, "__aiter__"), "_astream must return an async iterator"
    assert not hasattr(result, "__await__"), "_astream must not be a value coroutine"


def test_astream_iterable_with_async_for() -> None:
    """``async for chunk in model._astream(...)`` must not raise before the first chunk.

    The model is configured non-streaming, so ``_astream`` delegates to
    ``_agenerate`` (litellm.acompletion). We don't drive the network here; we
    only assert the ``async for`` setup is valid (the generator can be created
    and closed without a ``TypeError: 'async for' requires an object with
    __aiter__``).
    """

    async def _probe() -> None:
        model = _make_model()
        gen = model._astream(messages=[HumanMessage(content="hi")])  # noqa: SLF001
        # Closing the generator before iterating is a valid no-op on an async gen.
        await gen.aclose()

    asyncio.new_event_loop().run_until_complete(_probe())
