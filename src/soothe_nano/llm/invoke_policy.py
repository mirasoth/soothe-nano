"""Bounded async LLM invocation with timeout and retry for planner / structured-output paths.

Shares the same RPM budget and retry runner as `LLMRateLimitMiddleware` so
direct `ainvoke` calls and the middleware-stack path stay rate-limited together.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from soothe_deepagents.middleware.llm_rate_limit import (
    EnhancedTimeoutError,
    resolve_llm_budget_key,
    run_llm_call_with_policy,
)

from soothe_nano.config.models import LLMRateLimitConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


def llm_rate_limit_config_from(soothe_config: Any | None) -> LLMRateLimitConfig:
    """Resolve direct-call timeout/retry policy from `SootheConfig`.

    Reads `agent.middleware.llm_rate_limit` (nano). Legacy `agent.loop`
    rate-limit keys are rejected by host config validation and are not used.
    """
    if soothe_config is not None:
        agent = getattr(soothe_config, "agent", None)
        middleware = getattr(agent, "middleware", None) if agent is not None else None
        llm_rate_limit = (
            getattr(middleware, "llm_rate_limit", None) if middleware is not None else None
        )
        if isinstance(llm_rate_limit, LLMRateLimitConfig):
            return llm_rate_limit
    return LLMRateLimitConfig()


def run_with_llm_call_policy_sync(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    config: LLMRateLimitConfig,
    thread_id: str | None = None,
) -> T:
    """Run `await_with_llm_call_policy` from a sync caller without a running loop."""

    async def _run() -> T:
        return await await_with_llm_call_policy(
            coro_factory,
            config=config,
            thread_id=thread_id,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    msg = "run_with_llm_call_policy_sync cannot be called from a running event loop"
    raise RuntimeError(msg)


async def await_with_llm_call_policy(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    config: LLMRateLimitConfig,
    thread_id: str | None = None,
) -> T:
    """Run `coro_factory` with shared RPM limits, timeouts, and retry policy.

    Args:
        coro_factory: Zero-arg callable returning the awaitable LLM operation.
        config: Rate-limit / timeout configuration.
        thread_id: Optional thread id for retry telemetry and budget allocation.

    Returns:
        Result of `coro_factory`.

    Raises:
        EnhancedTimeoutError: When timeout retries are exhausted.
        Exception: Propagates non-retriable provider errors.
    """
    budget_key = resolve_llm_budget_key(thread_id)
    telemetry_id = thread_id or budget_key
    from soothe_nano.utils.token_usage import direct_llm_token_call_scope

    with direct_llm_token_call_scope():
        return await run_llm_call_with_policy(
            coro_factory,
            config=config,
            budget_key=budget_key,
            thread_id=telemetry_id,
            log_prefix="Direct LLM",
            log=logger,
        )


__all__ = [
    "EnhancedTimeoutError",
    "await_with_llm_call_policy",
    "llm_rate_limit_config_from",
    "run_with_llm_call_policy_sync",
]
