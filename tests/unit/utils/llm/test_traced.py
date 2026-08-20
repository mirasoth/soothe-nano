"""Tests for the unified Langfuse-traced LLM invocation helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from soothe_deepagents.middleware.llm_rate_limit import LLMRateLimitRegistry

from soothe_nano.llm import (
    ainvoke_structured_traced,
    ainvoke_traced,
    build_traced_invoke_config,
)


@pytest.fixture(autouse=True)
def _reset_llm_rate_limit_registry() -> None:
    LLMRateLimitRegistry.reset_for_tests()


def test_build_config_metadata_only_when_no_config() -> None:
    """No soothe_config and no goal_trace → bare metadata dict."""
    cfg = build_traced_invoke_config(
        soothe_config=None,
        purpose="scenario_classify",
        component="synthesis.classifier",
        phase="post-loop",
        session_id=None,
        loop_id=None,
        run_name=None,
        extra_metadata=None,
        goal_trace=None,
        independent_trace=False,
    )
    assert cfg == {
        "metadata": {
            "soothe_call_purpose": "scenario_classify",
            "soothe_call_component": "synthesis.classifier",
            "soothe_call_phase": "post-loop",
        }
    }


def test_build_config_merges_extra_metadata() -> None:
    cfg = build_traced_invoke_config(
        soothe_config=None,
        purpose="p",
        component="c",
        phase="ph",
        session_id=None,
        loop_id=None,
        run_name=None,
        extra_metadata={"trace_id": "t-1"},
        goal_trace=None,
        independent_trace=False,
    )
    assert cfg["metadata"]["trace_id"] == "t-1"
    assert cfg["metadata"]["soothe_call_purpose"] == "p"


def test_build_config_goal_trace_pinned() -> None:
    """goal_trace with pinned_llm_invoke_config short-circuits other branches."""

    class _Trace:
        def pinned_llm_invoke_config(
            self,
            *,
            purpose: str,
            component: str,
            phase: str,
            run_name: str,
            extra_metadata: dict[str, Any] | None,
        ) -> dict[str, Any]:
            return {"configurable": {"pinned": True}, "run_name": run_name}

    cfg = build_traced_invoke_config(
        soothe_config=object(),  # would normally hit SootheLangfuse branch
        purpose="intake_classify",
        component="intake",
        phase="pre-stream",
        session_id="s",
        loop_id="l",
        run_name=None,
        extra_metadata=None,
        goal_trace=_Trace(),
        independent_trace=False,
    )
    assert cfg["configurable"]["pinned"] is True
    # run_name falls back to the purpose-derived default
    assert cfg["run_name"] == "soothe:intake-classify"


def test_build_config_soothe_langfuse_path() -> None:
    """soothe_config (no goal_trace) delegates to SootheLangfuse.traced_llm."""
    sentinel = {"callbacks": ["lf"], "metadata": {"soothe_call_purpose": "p"}}
    captured: dict[str, Any] = {}

    class _StubTracer:
        def traced_llm(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return sentinel

    with patch(
        "soothe_sdk.observability.langfuse.SootheLangfuse",
        lambda _cfg: _StubTracer(),
    ):
        cfg = build_traced_invoke_config(
            soothe_config=object(),
            purpose="p",
            component="c",
            phase="pre-stream",
            session_id="sid",
            loop_id="lid",
            run_name="rn",
            extra_metadata=None,
            goal_trace=None,
            independent_trace=True,
        )

    assert cfg is sentinel
    assert captured["independent_trace"] is True
    assert captured["session_id"] == "sid"
    assert captured["loop_id"] == "lid"
    assert captured["run_name"] == "rn"


@pytest.mark.asyncio
async def test_ainvoke_traced_forwards_config_to_model() -> None:
    """ainvoke_traced builds a config and passes it to model.ainvoke."""
    captured: dict[str, Any] = {}
    expected_response = object()

    class _Model:
        async def ainvoke(self, messages: Any, *, config: Any) -> Any:
            captured["messages"] = messages
            captured["config"] = config
            return expected_response

    result = await ainvoke_traced(
        _Model(),
        ["m1"],
        soothe_config=None,
        purpose="p",
        component="c",
        phase="ph",
    )

    assert result is expected_response
    assert captured["messages"] == ["m1"]
    assert captured["config"] == {
        "metadata": {
            "soothe_call_purpose": "p",
            "soothe_call_component": "c",
            "soothe_call_phase": "ph",
        }
    }


@pytest.mark.asyncio
async def test_ainvoke_traced_uses_goal_trace_config() -> None:
    """When goal_trace is set, its pinned config is forwarded to ainvoke."""
    pinned = {"configurable": {"pinned": True}, "run_name": "soothe:p"}

    class _Trace:
        def pinned_llm_invoke_config(self, **_kwargs: Any) -> dict[str, Any]:
            return pinned

    captured: dict[str, Any] = {}

    class _Model:
        async def ainvoke(self, _messages: Any, *, config: Any) -> Any:
            captured["config"] = config
            return object()

    await ainvoke_traced(
        _Model(),
        ["m"],
        soothe_config=object(),
        purpose="p",
        component="c",
        phase="ph",
        goal_trace=_Trace(),
    )
    assert captured["config"] is pinned


@pytest.mark.asyncio
async def test_ainvoke_traced_merges_extra_invoke_config() -> None:
    captured: dict[str, Any] = {}

    class _Model:
        async def ainvoke(self, _messages: Any, *, config: Any) -> Any:
            captured["config"] = config
            return object()

    await ainvoke_traced(
        _Model(),
        ["m"],
        soothe_config=None,
        purpose="p",
        component="c",
        phase="ph",
        extra_invoke_config={"tags": ["extra"]},
    )
    assert captured["config"]["tags"] == ["extra"]
    # metadata still present
    assert captured["config"]["metadata"]["soothe_call_purpose"] == "p"


@pytest.mark.asyncio
async def test_ainvoke_structured_traced_invokes_structured_chat() -> None:
    """ainvoke_structured_traced wraps invoke_structured_chat with tracing + policy."""
    captured: dict[str, Any] = {}
    payload = {"answer": "yes", "confidence": 0.9}

    async def _fake_structured(
        model: Any,
        messages: Any,
        *,
        json_schema: dict[str, Any],
        schema_name: str | None,
        strict: bool,
        config: Any,
        normalize: Any,
    ) -> dict[str, Any]:
        captured.update(
            model=model,
            messages=messages,
            json_schema=json_schema,
            schema_name=schema_name,
            strict=strict,
            config=config,
            normalize=normalize,
        )
        return payload

    with patch(
        "soothe_nano.llm.structured.invoke_structured_chat",
        _fake_structured,
    ):
        result = await ainvoke_structured_traced(
            object(),
            ["m"],
            json_schema={"type": "object"},
            schema_name="Ans",
            strict=False,
            soothe_config=None,
            purpose="intent_hint",
            component="daemon.intent",
            phase="pre-stream",
            normalize=lambda d: d,
        )

    assert result is payload
    assert captured["schema_name"] == "Ans"
    assert captured["strict"] is False
    assert captured["config"]["metadata"]["soothe_call_purpose"] == "intent_hint"


@pytest.mark.asyncio
async def test_ainvoke_structured_traced_uses_goal_trace_config() -> None:
    pinned = {"configurable": {"pinned": True}}

    class _Trace:
        def pinned_llm_invoke_config(self, **_kwargs: Any) -> dict[str, Any]:
            return pinned

    captured: dict[str, Any] = {}

    async def _fake_structured(
        _model: Any, _messages: Any, *, config: Any, **_kw: Any
    ) -> dict[str, Any]:
        captured["config"] = config
        return {}

    with patch(
        "soothe_nano.llm.structured.invoke_structured_chat",
        _fake_structured,
    ):
        await ainvoke_structured_traced(
            object(),
            ["m"],
            json_schema={"type": "object"},
            soothe_config=object(),
            purpose="p",
            component="c",
            phase="ph",
            goal_trace=_Trace(),
        )
    assert captured["config"] is pinned
