"""E2E smoke test: ``hide_thinking_tokens`` flag routing through the litellm adapter.

Validates the complete chain:

1. ``ProviderCapabilities.hide_thinking_tokens`` (resolved from the provider
   config by :class:`ProviderRegistry`) is read by ``ChatLitellmModel``.
2. The flag controls whether ``_generate`` strips inline thinking blocks from
   the response (reasoning tokens never surface to the agent/UI).
3. With the flag ``True``, a model response containing a thinking block is
   stripped; with ``False`` the same response is returned verbatim.

This test does **not** hit any network. It patches ``litellm.completion`` to
return a canned response carrying a thinking block and exercises the real
``ChatLitellmModel._generate`` path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage

from soothe_nano.llm.provider import ChatLitellmModel
from soothe_nano.llm.registry import ProviderCapabilities

# --- test fixtures -----------------------------------------------------------

_THINKING_BLOCK = "<thinking>Let me reason step by step.</thinking>"
_VISIBLE_TEXT = "The answer is 42."
_RESPONSE_TEXT = f"{_THINKING_BLOCK}{_VISIBLE_TEXT}"


def _canned_completion_response(text: str) -> Any:
    """Build a minimal litellm response object carrying one choice."""
    msg = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice], usage=None)


def _make_model(hide: bool) -> ChatLitellmModel:
    """Build a ``ChatLitellmModel`` whose capabilities expose the flag value."""
    return ChatLitellmModel(
        model="openai/test-model",
        capabilities=ProviderCapabilities(hide_thinking_tokens=hide),
        streaming=False,
    )


@pytest.fixture
def _patch_litellm_completion():
    """Patch ``litellm.completion`` to return the canned thinking-block response."""
    with patch("soothe_nano.llm.provider.litellm.completion") as mock_completion:
        mock_completion.return_value = _canned_completion_response(_RESPONSE_TEXT)
        yield mock_completion


# --- tests -------------------------------------------------------------------


def test_factory_passes_flag_true_and_strips_thinking(_patch_litellm_completion) -> None:
    """Flag ``True`` -> thinking block is stripped from the generated message."""
    model = _make_model(hide=True)
    result = model._generate(messages=[HumanMessage(content="hi")])
    text = result.generations[0].message.content
    assert _THINKING_BLOCK not in text
    assert _VISIBLE_TEXT in text


def test_factory_passes_flag_false_and_preserves_thinking(_patch_litellm_completion) -> None:
    """Flag ``False`` -> the thinking block survives in the generated message."""
    model = _make_model(hide=False)
    result = model._generate(messages=[HumanMessage(content="hi")])
    text = result.generations[0].message.content
    assert _THINKING_BLOCK in text
    assert _VISIBLE_TEXT in text


def test_factory_flag_propagates_from_real_config() -> None:
    """The flag on ``SootheConfig`` reaches the model via the registry."""
    from soothe_nano.config.models import ModelProviderConfig
    from soothe_nano.config.settings import SootheConfig
    from soothe_nano.llm.registry import ProviderRegistry

    cfg = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="local",
                provider_type="openai",
                api_base_url="http://localhost:1234/v1",
                api_key="test",
            )
        ]
    )
    registry = ProviderRegistry(cfg.providers)
    caps = registry.provider_capabilities("local")
    assert caps.hide_thinking_tokens is True
