"""Unified LLM invocation with Langfuse tracing and rate-limit policy.

Every direct LLM `ainvoke` should go through `ainvoke_traced` so Langfuse
callbacks are attached, `await_with_llm_call_policy` wraps the call for
rate-limiting/timeout/retry, and structured-output calls are traced the same
way as plain `ainvoke`. Safe to call without a config (unit tests, headless
runs): the call works without Langfuse tracing.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _default_run_name(purpose: str) -> str:
    """Fallback Langfuse run display name from the call purpose."""
    return f"soothe:{purpose.replace('_', '-')}"


def build_traced_invoke_config(
    *,
    soothe_config: Any | None,
    purpose: str,
    component: str,
    phase: str,
    session_id: str | None,
    loop_id: str | None,
    run_name: str | None,
    extra_metadata: dict[str, Any] | None,
    goal_trace: Any | None,
    independent_trace: bool,
) -> dict[str, Any]:
    """Build a Langfuse-traced RunnableConfig for an LLM call.

    Priority:

    1. `goal_trace` pinned config (shares the goal-loop trace). The host
       `GoalLoopTrace` exposes `pinned_llm_invoke_config`; any object with
       that method is supported (duck-typed, no host import here).
    2. `SootheLangfuse(soothe_config).traced_llm(...)` (standalone trace).
    3. Bare metadata dict (no Langfuse — e.g. unit tests without config).
    """
    # ── 1. Goal-loop trace pinning ────────────────────────────────────────────
    if goal_trace is not None and hasattr(goal_trace, "pinned_llm_invoke_config"):
        return goal_trace.pinned_llm_invoke_config(
            purpose=purpose,
            component=component,
            phase=phase,
            run_name=run_name or _default_run_name(purpose),
            extra_metadata=extra_metadata,
        )

    # ── 2. Standalone Langfuse tracing ────────────────────────────────────────
    if soothe_config is not None:
        from soothe_sdk.observability.langfuse import SootheLangfuse

        return SootheLangfuse(soothe_config).traced_llm(
            purpose=purpose,
            component=component,
            phase=phase,
            session_id=session_id,
            loop_id=loop_id,
            run_name=run_name,
            extra_metadata=extra_metadata,
            independent_trace=independent_trace,
        )

    # ── 3. No config — metadata only ──────────────────────────────────────────
    from soothe_nano.llm.observability import create_llm_call_metadata

    metadata = create_llm_call_metadata(purpose=purpose, component=component, phase=phase)
    if extra_metadata:
        metadata.update(extra_metadata)
    return {"metadata": metadata}


def _resolve_rate_limit_config(
    soothe_config: Any | None,
    rate_limit_overrides: dict[str, Any] | None,
) -> Any:
    """Build an `LLMRateLimitConfig` from the soothe config, applying overrides."""
    from soothe_nano.llm.invoke_policy import llm_rate_limit_config_from

    if soothe_config is None:
        return None
    cfg = llm_rate_limit_config_from(soothe_config)
    if rate_limit_overrides:
        cfg = cfg.model_copy(update=rate_limit_overrides)
    return cfg


async def ainvoke_traced(
    model: BaseChatModel,
    messages: list[Any],
    *,
    soothe_config: Any | None = None,
    purpose: str,
    component: str,
    phase: str = "unknown",
    session_id: str | None = None,
    loop_id: str | None = None,
    run_name: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    goal_trace: Any | None = None,
    independent_trace: bool = False,
    rate_limit_overrides: dict[str, Any] | None = None,
    extra_invoke_config: dict[str, Any] | None = None,
) -> Any:
    """Invoke a chat model with Langfuse tracing and rate-limit policy.

    This is the **unified entry point** for all plain LLM `ainvoke` calls.
    It builds a Langfuse-traced RunnableConfig, wraps the call in
    :func:`await_with_llm_call_policy` (rate-limit, timeout, retry), and returns
    the raw model response.

    Args:
        model: The LangChain chat model to invoke.
        messages: Message list to send to the model.
        soothe_config: Soothe config for Langfuse/rate-limit resolution.
            When `None`, the call still works but without tracing.
        purpose: Short label for the call purpose (e.g. `"scenario_classify"`).
        component: Owning component path (e.g. `"synthesis.scenario_classifier"`).
        phase: Pipeline phase (e.g. `"post-loop"`, `"pre-stream"`).
        session_id: Thread /var/lib/soothe/workspaces/Workspace/soothe session ID for Langfuse session grouping.
        loop_id: Goal-loop ID for trace correlation.
        run_name: Langfuse observation display name. Falls back to a
            purpose-derived name.
        extra_metadata: Additional metadata merged into the RunnableConfig.
        goal_trace: When provided, pin the call to this goal-loop trace
            (shares the root trace with intake + graph). Duck-typed: any object
            with `pinned_llm_invoke_config` is supported.
        independent_trace: When `True`, use a fresh Langfuse handler
            instead of the cached one (separate root trace).
        rate_limit_overrides: Override fields on the `LLMRateLimitConfig`
            (e.g. `{"call_timeout_seconds": 30}`).
        extra_invoke_config: Additional RunnableConfig fields merged on top
            of the Langfuse config (rarely needed).

    Returns:
        The raw model response (e.g. `AIMessage`).
    """
    from soothe_nano.llm.invoke_policy import await_with_llm_call_policy

    invoke_config = build_traced_invoke_config(
        soothe_config=soothe_config,
        purpose=purpose,
        component=component,
        phase=phase,
        session_id=session_id,
        loop_id=loop_id,
        run_name=run_name,
        extra_metadata=extra_metadata,
        goal_trace=goal_trace,
        independent_trace=independent_trace,
    )
    if extra_invoke_config:
        invoke_config = {**invoke_config, **extra_invoke_config}

    rate_limit_config = _resolve_rate_limit_config(soothe_config, rate_limit_overrides)

    async def _invoke() -> Any:
        return await model.ainvoke(messages, config=invoke_config)

    return await await_with_llm_call_policy(
        _invoke,
        config=rate_limit_config,
        thread_id=session_id,
    )


async def ainvoke_structured_traced(
    model: BaseChatModel,
    messages: list[Any],
    *,
    json_schema: dict[str, Any],
    schema_name: str | None = None,
    strict: bool = True,
    soothe_config: Any | None = None,
    purpose: str,
    component: str,
    phase: str = "unknown",
    session_id: str | None = None,
    loop_id: str | None = None,
    run_name: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    goal_trace: Any | None = None,
    independent_trace: bool = False,
    rate_limit_overrides: dict[str, Any] | None = None,
    normalize: Any | None = None,
    methods: tuple[str | None, ...] | None = None,
) -> dict[str, Any]:
    """Invoke a chat model with structured output, Langfuse tracing, and rate-limit.

    This is the **unified entry point** for all structured-output LLM calls.
    It wraps :func:`soothe_nano.llm.structured.invoke_structured_chat` with the
    same Langfuse + rate-limit infrastructure as :func:`ainvoke_traced`.

    Args:
        model: The LangChain chat model to invoke.
        messages: Message list to send to the model.
        json_schema: JSON schema for structured output.
        schema_name: Optional schema name for the model's structured-output mode.
        strict: Whether to enforce strict schema compliance.
        soothe_config: Soothe config for Langfuse/rate-limit resolution.
        purpose: Short label for the call purpose.
        component: Owning component path.
        phase: Pipeline phase.
        session_id: Thread /var/lib/soothe/workspaces/Workspace/soothe session ID for Langfuse session grouping.
        loop_id: Goal-loop ID for trace correlation.
        run_name: Langfuse observation display name.
        extra_metadata: Additional metadata merged into the RunnableConfig.
        goal_trace: Pin the call to this goal-loop trace (duck-typed).
        independent_trace: Use a fresh Langfuse handler (separate root trace).
        rate_limit_overrides: Override fields on `LLMRateLimitConfig`.
        normalize: Optional normalisation callable applied to the structured
            result dict.
        methods: Optional ordered structured-output methods to try (forwarded
            to :func:`invoke_structured_chat`).  When `None`, the default
            order (`function_calling → None → json_schema → json_mode`)
            is used.

    Returns:
        Parsed structured-output dictionary.
    """
    from soothe_nano.llm.invoke_policy import await_with_llm_call_policy
    from soothe_nano.llm.structured import invoke_structured_chat

    invoke_config = build_traced_invoke_config(
        soothe_config=soothe_config,
        purpose=purpose,
        component=component,
        phase=phase,
        session_id=session_id,
        loop_id=loop_id,
        run_name=run_name,
        extra_metadata=extra_metadata,
        goal_trace=goal_trace,
        independent_trace=independent_trace,
    )

    rate_limit_config = _resolve_rate_limit_config(soothe_config, rate_limit_overrides)

    async def _invoke() -> dict[str, Any]:
        return await invoke_structured_chat(
            model,
            messages,
            json_schema=json_schema,
            schema_name=schema_name,
            strict=strict,
            config=invoke_config,
            normalize=normalize,
            methods=methods,
        )

    return await await_with_llm_call_policy(
        _invoke,
        config=rate_limit_config,
        thread_id=session_id,
    )


__all__ = [
    "ainvoke_structured_traced",
    "ainvoke_traced",
    "build_traced_invoke_config",
]
