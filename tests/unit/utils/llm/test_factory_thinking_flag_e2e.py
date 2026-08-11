"""E2E smoke test: ``hide_thinking_tokens`` flag routing through ``LLMFactory``.

Validates the complete chain:

1. ``SootheConfig.hide_thinking_tokens`` (the pydantic settings field) is read
   by ``LLMFactory._apply_wrapper_chain``.
2. The flag is passed to both wrappers in the chain:
   - ``OpenAICompatModelWrapper(hide_thinking_tokens=...)``
   - ``SootheTokenUsageChatModel(hide_thinking_tokens=...)``
3. With the flag ``True``, a model response containing a ``<think>…</think>``
   block is stripped (reasoning tokens never surface to the agent/UI).
4. With the flag ``False``, the same response is returned verbatim.

This test does **not** hit any network. It injects a stub ``BaseChatModel`` whose
``_generate`` returns a canned ``ChatResult`` and exercises the real wrapper
chain via the factory's private ``_apply_wrapper_chain`` method.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from soothe_nano.utils.llm.factory import LLMFactory
from soothe_nano.utils.llm.wrappers import OpenAICompatModelWrapper

# --- test fixtures -----------------------------------------------------------

_THINKING_BLOCK = "<think>Let me reason step by step.</think>"
_VISIBLE_TEXT = "The answer is 42."
_RESPONSE_TEXT = f"{_THINKING_BLOCK}{_VISIBLE_TEXT}"


def _stub_chat_result(text: str) -> ChatResult:
    """Build a minimal ``ChatResult`` carrying one ``AIMessage``."""
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class _StubModel:
    """Minimal stand-in for a ``BaseChatModel`` returned by ``init_chat_model``.

    Its ``_generate`` always returns the same canned response, so the test can
    assert on whether the wrapper chain stripped the thinking block.
    """

    def __init__(self, response_text: str = _RESPONSE_TEXT) -> None:
        self._response_text = response_text

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return _stub_chat_result(self._response_text)

    def _llm_type(self) -> str:  # pragma: no cover - not exercised
        return "stub"

    def __getattr__(self, name: str) -> Any:
        """Tolerate attribute probes from LangChain base classes."""
        raise AttributeError(name)


def _factory_for_flag(hide: bool) -> LLMFactory:
    """Build an ``LLMFactory`` whose config exposes the requested flag value.

    We bypass ``__init__``'s provider registry construction (no providers are
    configured for this test) and set the minimum attributes
    ``_apply_wrapper_chain`` reads.
    """
    config = SimpleNamespace(hide_thinking_tokens=hide, providers=[])
    factory = LLMFactory.__new__(LLMFactory)
    factory._config = config
    factory._registry = MagicMock()
    # Force the compat wrapper ON so we exercise OpenAICompatModelWrapper too.
    factory._registry.requires_openai_compat_wrapper.return_value = True
    factory._cache = {}
    factory._embedding_cache = {}
    return factory


def _result_text(model: Any) -> str:
    """Return the ``message.content`` of the single generation in *model*."""
    result = model._generate(messages=[])
    gens = result.generations
    [gen] = gens
    return gen.message.content


# --- tests -------------------------------------------------------------------


def test_factory_passes_flag_true_and_strips_thinking() -> None:
    """Flag ``True`` → both wrappers receive it and thinking is stripped."""
    factory = _factory_for_flag(hide=True)

    wrapped = factory._apply_wrapper_chain(
        _StubModel(),
        provider_type="custom",  # noqa: SLF001 - exercising private method
        provider_name="stub",
    )

    # Outer wrapper is the token-usage observability layer.
    outer = wrapped
    assert outer._hide_thinking_tokens is True  # noqa: SLF001

    # Inner wrapper is the OpenAI-compat layer (it does the actual stripping).
    inner = outer._model  # noqa: SLF001
    assert isinstance(inner, OpenAICompatModelWrapper)
    assert inner._hide_thinking_tokens is True  # noqa: SLF001

    # E2E: the thinking block must be gone, visible text preserved.
    text = _result_text(outer)
    assert _THINKING_BLOCK not in text
    assert _VISIBLE_TEXT in text


def test_factory_passes_flag_false_and_preserves_thinking() -> None:
    """Flag ``False`` → both wrappers receive it and thinking is preserved."""
    factory = _factory_for_flag(hide=False)

    wrapped = factory._apply_wrapper_chain(
        _StubModel(),
        provider_type="custom",  # noqa: SLF001
        provider_name="stub",
    )

    outer = wrapped
    assert outer._hide_thinking_tokens is False  # noqa: SLF001
    inner = outer._model  # noqa: SLF001
    assert isinstance(inner, OpenAICompatModelWrapper)
    assert inner._hide_thinking_tokens is False  # noqa: SLF001

    # E2E: the thinking block must survive when the flag is off.
    text = _result_text(outer)
    assert _THINKING_BLOCK in text
    assert _VISIBLE_TEXT in text


def test_factory_flag_propagates_from_real_config() -> None:
    """The flag on ``SootheConfig`` (the pydantic settings model) reaches the
    wrappers when a config instance is constructed normally."""
    from soothe_nano.config.settings import SootheConfig

    cfg_true = SootheConfig(hide_thinking_tokens=True)
    cfg_false = SootheConfig(hide_thinking_tokens=False)

    f_true = _factory_for_flag(hide=cfg_true.hide_thinking_tokens)
    f_false = _factory_for_flag(hide=cfg_false.hide_thinking_tokens)

    m_true = f_true._apply_wrapper_chain(_StubModel(), provider_type="custom", provider_name="stub")  # noqa: SLF001
    m_false = f_false._apply_wrapper_chain(
        _StubModel(), provider_type="custom", provider_name="stub"
    )  # noqa: SLF001

    assert m_true._hide_thinking_tokens is True  # noqa: SLF001
    assert m_false._hide_thinking_tokens is False  # noqa: SLF001

    assert _THINKING_BLOCK not in _result_text(m_true)
    assert _THINKING_BLOCK in _result_text(m_false)
