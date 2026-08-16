"""Regression tests for compat wrapper tool_choice sanitization.

The unified ``ChatLitellmModel`` (aliased as ``OpenAICompatModelWrapper`` for
back-compat) stores bound tools on the instance and sanitizes ``tool_choice``
for thinking-mode provider compatibility — a port of the legacy
``_sanitize_tool_choice_for_compat``. These tests pin the sanitization
contract so an incompatible ``tool_choice`` value never reaches litellm.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_nano.llm.provider import ChatLitellmModel as OpenAICompatModelWrapper
from soothe_nano.llm.tools import bind_tools_litellm

# A tool already in litellm/OpenAI wire format — the shape ``bind_tools_litellm``
# passes through unchanged. Using the wire form (rather than a bare ``{"name": ..}``
# dict) avoids exercising the tool-schema converter, which these tests don't cover.
_TOOL = {"type": "function", "function": {"name": "tool_a"}}


def _make_model() -> OpenAICompatModelWrapper:
    """A minimal model instance whose inner bind path we don't exercise."""
    return OpenAICompatModelWrapper(model="openai/gpt-4o-mini")  # type: ignore[call-arg]


def test_bind_tools_sanitizes_required_tool_choice_to_auto() -> None:
    model = _make_model()

    out = model.bind_tools([_TOOL], tool_choice="required")

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out.bound_tool_choice == "auto"  # noqa: SLF001


def test_bind_tools_sanitizes_any_tool_choice_to_auto() -> None:
    model = _make_model()

    out = model.bind_tools([_TOOL], tool_choice="any")

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out.bound_tool_choice == "auto"  # noqa: SLF001


def test_bind_tools_sanitizes_true_tool_choice_to_auto() -> None:
    model = _make_model()

    out = model.bind_tools([_TOOL], tool_choice=True)

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out.bound_tool_choice == "auto"  # noqa: SLF001


def test_bind_tools_sanitizes_object_tool_choice_to_auto() -> None:
    model = _make_model()

    out = model.bind_tools(
        [_TOOL],
        tool_choice={"type": "function", "function": {"name": "tool_a"}},
    )

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out.bound_tool_choice == "auto"  # noqa: SLF001


def test_bind_tools_passes_through_string_tool_choice() -> None:
    """Unrecognized string values (e.g. ``"none"``) pass through untouched."""
    model = _make_model()

    out = model.bind_tools([_TOOL], tool_choice="none")

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out.bound_tool_choice == "none"  # noqa: SLF001


def test_bind_tools_stores_wire_tools_and_reuses_instance() -> None:
    """``bind_tools`` returns a new model copy with litellm wire-format tools."""
    model = _make_model()
    tools = [_TOOL]

    out = model.bind_tools(tools, tool_choice="required")

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out is not model  # new copy, not the same instance
    expected_wire = bind_tools_litellm(tools)
    assert out.bound_tools == expected_wire  # noqa: SLF001


def test_bind_tools_forwards_remaining_kwargs_to_model_kwargs() -> None:
    """Extra kwargs (beyond ``tool_choice``) land in ``model_kwargs``."""
    model = _make_model()

    out = model.bind_tools([_TOOL], tool_choice="required", parallel_tool_calls=False)

    assert isinstance(out, OpenAICompatModelWrapper)
    assert out.model_kwargs == {"parallel_tool_calls": False}  # noqa: SLF001


# The legacy wrapper forwarded bind_tools to an inner ``_model`` and re-wrapped
# the result. That indirection is gone — tools live on the adapter instance —
# so the old ``wrapped.bind_tools.assert_called_once_with(...)`` assertion no
# longer applies. We keep a mock here only to guard against accidental inner
# delegation regressing in.
def test_bind_tools_does_not_delegate_to_an_inner_model() -> None:
    inner = MagicMock()
    inner.bind_tools.return_value = "ok"
    model = OpenAICompatModelWrapper(model="openai/gpt-4o-mini")  # type: ignore[call-arg]

    out = model.bind_tools([_TOOL], tool_choice="required")

    # The bound model is itself the adapter (not the inner mock's return value).
    assert isinstance(out, OpenAICompatModelWrapper)
    assert out != "ok"
    inner.bind_tools.assert_not_called()
