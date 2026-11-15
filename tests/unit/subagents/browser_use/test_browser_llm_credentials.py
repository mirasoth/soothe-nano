"""Tests for browser_use provider-aware LLM credential resolution."""

from __future__ import annotations

from soothe_nano.config.models import ModelProviderConfig, SubagentConfig
from soothe_nano.config.settings import SootheConfig
from soothe_nano.subagents.browser_use.implementation import (
    _apply_browser_use_synthesis_decision,
    _browser_result_had_no_progress,
    _BrowserUseSynthesisDecision,
    _format_browser_no_progress_error,
    _history_digest_for_synthesis,
    _resolve_browser_llm_credentials,
    browser_use_model_role,
)


class _Part:
    def __init__(self, *, content: str | None = None, tool_name: str | None = None) -> None:
        if content is not None:
            self.content = content
        if tool_name is not None:
            self.tool_name = tool_name
            self.args = {"url": "https://example.test"}


class _Message:
    def __init__(self, name: str, parts: list[_Part]) -> None:
        self._name = name
        self.parts = parts


class _RunResult:
    def __init__(
        self,
        *,
        steps: int = 1,
        messages: list[object] | None = None,
        text: str = "",
        status: str = "completed",
    ) -> None:
        self.steps = steps
        self.messages = messages or []
        self.text = text
        self.status = status
        self.error = None

    def final_result(self) -> str | None:
        return self.text if self.status == "completed" else None


def test_resolve_browser_llm_credentials_uses_default_model_role() -> None:
    config = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="dashscope",
                provider_type="openai",
                api_base_url="https://example.test/v1",
                api_key="test-key",
                models=["glm-5.2"],
            )
        ],
        router_profiles=[
            {
                "name": "production",
                "router": {"default": "dashscope:glm-5.2"},
            }
        ],
        active_router_profile="production",
    )
    model_name, base_url, api_key = _resolve_browser_llm_credentials(soothe_config=config)
    assert model_name == "glm-5.2"
    assert base_url == "https://example.test/v1"
    assert api_key == "test-key"


def test_browser_use_model_role_defaults_to_default() -> None:
    config = SootheConfig()
    assert browser_use_model_role(config) == "default"


def test_resolve_browser_llm_credentials_uses_configured_model_role() -> None:
    config = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="dashscope",
                provider_type="openai",
                api_base_url="https://example.test/v1",
                api_key="test-key",
                models=["glm-5.2", "kimi-k2.5"],
            )
        ],
        router_profiles=[
            {
                "name": "production",
                "router": {
                    "default": "dashscope:glm-5.2",
                    "fast": "dashscope:kimi-k2.5",
                },
            }
        ],
        active_router_profile="production",
        subagents={
            "browser_use": SubagentConfig(enabled=True, model_role="fast"),
        },
    )
    model_name, base_url, api_key = _resolve_browser_llm_credentials(soothe_config=config)
    assert model_name == "kimi-k2.5"
    assert base_url == "https://example.test/v1"
    assert api_key == "test-key"


def test_browser_result_had_no_progress_detects_zero_step_run() -> None:
    run_result = _RunResult(steps=0)
    assert _browser_result_had_no_progress(run_result) is True


def test_browser_result_had_no_progress_false_after_work() -> None:
    run_result = _RunResult(steps=2)
    assert _browser_result_had_no_progress(run_result) is False


def test_format_browser_no_progress_error_includes_model_and_steps() -> None:
    message = _format_browser_no_progress_error(model_name="kimi-k2.5", steps=10)
    assert "BrowserUse failed" in message
    assert "kimi-k2.5" in message
    assert "10 step(s)" in message


def test_history_digest_for_synthesis_summarizes_messages() -> None:
    messages = [
        _Message("ModelRequest", [_Part(content="Open example.test and read the title.")]),
        _Message("ModelResponse", [_Part(tool_name="run_python")]),
    ]
    run_result = _RunResult(steps=1, messages=messages)
    digest = _history_digest_for_synthesis(run_result)
    assert "Open example.test" in digest
    assert "run_python" in digest
    assert len(digest.splitlines()) == 2


def test_history_digest_for_synthesis_empty_history() -> None:
    run_result = _RunResult(steps=0, messages=[])
    assert _history_digest_for_synthesis(run_result) == "(no browser message history)"


def test_apply_browser_use_synthesis_decision_prefers_synthesized_answer() -> None:
    decision = _BrowserUseSynthesisDecision(
        use_raw_result=False,
        answer_quality="sufficient",
        final_answer="Los Angeles weather: clear, 26C.",
        summary="Los Angeles weather summary",
        rationale="Raw output only described scrolling.",
    )
    final_answer, summary, used_synthesized, quality_sufficient = (
        _apply_browser_use_synthesis_decision(
            raw_result="Scrolled down 3 pages",
            decision=decision,
        )
    )
    assert final_answer == "Los Angeles weather: clear, 26C."
    assert summary == "Los Angeles weather summary"
    assert used_synthesized is True
    assert quality_sufficient is True


def test_apply_browser_use_synthesis_decision_falls_back_to_raw_result() -> None:
    decision = _BrowserUseSynthesisDecision(
        use_raw_result=True,
        answer_quality="insufficient",
        final_answer="",
        summary="",
        rationale="Raw output is partial.",
    )
    final_answer, summary, used_synthesized, quality_sufficient = (
        _apply_browser_use_synthesis_decision(
            raw_result="Weather page opened but no forecast extracted.",
            decision=decision,
        )
    )
    assert final_answer == "Weather page opened but no forecast extracted."
    assert "Weather page opened" in summary
    assert used_synthesized is False
    assert quality_sufficient is False
