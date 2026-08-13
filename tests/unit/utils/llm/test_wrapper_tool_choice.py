"""Regression tests for compat wrapper tool_choice sanitization."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_nano.utils.llm.wrappers import OpenAICompatModelWrapper


def test_bind_tools_sanitizes_required_tool_choice_to_auto() -> None:
    wrapped = MagicMock()
    wrapped.bind_tools.return_value = "ok"
    model = OpenAICompatModelWrapper(wrapped, provider_name="dashscope")

    out = model.bind_tools([{"name": "tool_a"}], tool_choice="required")

    # bind_tools re-wraps the bound inner model so the model-agnostic protocol
    # adapter still applies on every tool-bound invocation.
    assert isinstance(out, OpenAICompatModelWrapper)
    assert out._model == "ok"  # noqa: SLF001
    wrapped.bind_tools.assert_called_once_with([{"name": "tool_a"}], tool_choice="auto")


def test_bind_tools_sanitizes_any_tool_choice_to_auto() -> None:
    wrapped = MagicMock()
    wrapped.bind_tools.return_value = "ok"
    model = OpenAICompatModelWrapper(wrapped, provider_name="dashscope")

    out = model.bind_tools([{"name": "tool_a"}], tool_choice="any")

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out._model == "ok"  # noqa: SLF001
    wrapped.bind_tools.assert_called_once_with([{"name": "tool_a"}], tool_choice="auto")


def test_bind_tools_sanitizes_true_tool_choice_to_auto() -> None:
    wrapped = MagicMock()
    wrapped.bind_tools.return_value = "ok"
    model = OpenAICompatModelWrapper(wrapped, provider_name="dashscope")

    out = model.bind_tools([{"name": "tool_a"}], tool_choice=True)

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out._model == "ok"  # noqa: SLF001
    wrapped.bind_tools.assert_called_once_with([{"name": "tool_a"}], tool_choice="auto")


def test_bind_tools_sanitizes_object_tool_choice_to_auto() -> None:
    wrapped = MagicMock()
    wrapped.bind_tools.return_value = "ok"
    model = OpenAICompatModelWrapper(wrapped, provider_name="dashscope")

    out = model.bind_tools(
        [{"name": "tool_a"}],
        tool_choice={"type": "function", "function": {"name": "tool_a"}},
    )

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out._model == "ok"  # noqa: SLF001
    wrapped.bind_tools.assert_called_once_with([{"name": "tool_a"}], tool_choice="auto")
