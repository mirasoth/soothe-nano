"""Bounded async LLM invocation with timeout and retry for planner / structured-output paths.

Shares the same RPM budget and retry runner as `LLMRateLimitMiddleware` so
direct `ainvoke` calls and the middleware-stack path stay rate-limited together.

Also provides :class:`PersistentRetryRunner`, a middleware wrapper that adds
resilience features on top of the upstream rate-limit policy:

- **Persistent retry with heartbeat**: Retries 429/529/transient-connection
  errors indefinitely (configurable) with exponential backoff capped at
  ``persistent_retry_max_backoff_seconds`` per attempt and a hard ceiling at
  ``persistent_retry_total_cap_seconds`` total. During backoff sleeps, heartbeat
  events are yielded so the daemon sees periodic activity.
- **Query-source discrimination**: Foreground sources (main_loop,
  clarification, subagent) retry persistently; background sources (compact,
  summary) bail immediately on 529 to avoid retry amplification.
- **Model fallback**: After ``fallback_model_threshold`` consecutive
  capacity (529/overloaded) errors, switches to a configured fallback model for
  the remainder of the step/goal and emits a ``model_fallback_triggered`` event.
- **Stale-connection detection**: On ECONNRESET/EPIPE/ConnectionResetError,
  disables HTTP keep-alive for the retry and obtains a fresh client/connection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from soothe_deepagents.middleware.llm_rate_limit import (
    EnhancedTimeoutError,
    _is_api_rate_limit_error,
    _is_transient_connection_error,
    resolve_llm_budget_key,
    run_llm_call_with_policy,
)

from soothe_nano.config.models import LLMRateLimitConfig, ModelRole, QuerySource
from soothe_nano.events.catalog import (
    LLMPersistentRetryEvent,
    ModelFallbackEvent,
    custom_event,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Sentinel object yielded during backoff sleeps so the daemon sees activity.
# Reuses the same pattern as the graph-stream heartbeat sentinel.
_STREAM_HEARTBEAT_SENTINEL: Any = object()

# Heartbeat interval during persistent-retry backoff (seconds).
_HEARTBEAT_INTERVAL_SECONDS: float = 15.0

# Error-type names that indicate provider capacity/overload (529-class).
_CAPACITY_ERROR_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "OverloadedError",
        "CapacityError",
        "ServiceUnavailableError",
    }
)

# Error-type names that indicate stale/reset connections.
_STALE_CONNECTION_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "ConnectionResetError",
        "ConnectionAbortedError",
        "ConnectionRefusedError",
        "BrokenPipeError",
    }
)

# Text fragments that indicate a 529/overloaded condition.
_CAPACITY_ERROR_TEXT_FRAGMENTS: tuple[str, ...] = (
    "overloaded",
    "capacity",
    "529",
    "service unavailable",
    "server overloaded",
)

# Text fragments that indicate a stale/reset connection.
_STALE_CONNECTION_TEXT_FRAGMENTS: tuple[str, ...] = (
    "econnreset",
    "epipe",
    "connection reset",
    "connection aborted",
    "broken pipe",
)

# Query sources that are "background" — they bail immediately on 529.
_BACKGROUND_QUERY_SOURCES: frozenset[QuerySource] = frozenset(
    {
        QuerySource.compact,
        QuerySource.summary,
    }
)


def _is_capacity_error(exc: Exception) -> bool:
    """True when *exc* indicates a provider capacity/overload (529-class) error.

    Detects by exception type name, HTTP status code 529, or message text.
    """
    for link in _iter_exception_chain(exc):
        type_name = type(link).__name__
        if type_name in _CAPACITY_ERROR_TYPE_NAMES:
            return True
        response = getattr(link, "response", None)
        if response is not None and getattr(response, "status_code", None) == 529:
            return True
        text = str(link).lower()
        if any(fragment in text for fragment in _CAPACITY_ERROR_TEXT_FRAGMENTS):
            return True
    return False


def _is_stale_connection_error(exc: Exception) -> bool:
    """True when *exc* indicates a stale/reset connection (ECONNRESET/EPIPE).

    Checks exception type name and message text for connection-reset indicators.
    """
    for link in _iter_exception_chain(exc):
        type_name = type(link).__name__
        if type_name in _STALE_CONNECTION_TYPE_NAMES:
            return True
        text = str(link).lower()
        if any(fragment in text for fragment in _STALE_CONNECTION_TEXT_FRAGMENTS):
            return True
    return False


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    """Walk the exception cause/context chain, returning unique links in order."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _is_persistent_retriable(exc: Exception) -> bool:
    """True when *exc* is retriable by the persistent retry layer.

    Covers HTTP 429 rate limits, 529/capacity errors, transient connection
    errors (including ECONNRESET/EPIPE), and stale-connection errors
    (ConnectionResetError, BrokenPipeError) that the upstream transient
    check may miss when the message text is empty.
    """
    if _is_api_rate_limit_error(exc):
        return True
    if _is_capacity_error(exc):
        return True
    if _is_transient_connection_error(exc):
        return True
    if _is_stale_connection_error(exc):
        return True
    return False


def _calc_persistent_backoff(
    attempt: int,
    *,
    base: float,
    max_backoff: float,
) -> float:
    """Compute exponential backoff for persistent retry, capped at *max_backoff*.

    Args:
        attempt: Zero-based attempt index.
        base: Base delay in seconds.
        max_backoff: Maximum per-attempt backoff in seconds.

    Returns:
        Backoff delay in seconds, capped at *max_backoff*.
    """
    return min(base * (2**attempt), max_backoff)


def _emit_model_fallback_event(
    *,
    from_model: str | None,
    to_model: str,
    to_role: ModelRole | None,
    consecutive_capacity_errors: int,
    thread_id: str | None,
    request: ModelRequest[Any] | None = None,
) -> None:
    """Emit a ``model_fallback_triggered`` event via stream_writer and log.

    When the request carries a ``runtime.stream_writer``, a structured
    :class:`ModelFallbackEvent` is dispatched as a custom stream chunk so
    the daemon and TUI can surface the degradation. The event is always
    logged regardless of stream_writer availability.

    Args:
        from_model: Original model name/spec (best-effort).
        to_model: Fallback model name/spec or role label.
        to_role: Model router role when the fallback was resolved via role.
        consecutive_capacity_errors: Capacity errors that triggered fallback.
        thread_id: Thread id for telemetry.
        request: The in-flight ModelRequest (for stream_writer access).
    """
    logger.info(
        "model_fallback_triggered: from=%s to=%s to_role=%s "
        "consecutive_capacity_errors=%d thread_id=%s",
        from_model or "unknown",
        to_model,
        to_role or "n/a",
        consecutive_capacity_errors,
        thread_id or "unknown",
    )
    if request is None:
        return
    stream_writer = getattr(getattr(request, "runtime", None), "stream_writer", None)
    if not callable(stream_writer):
        return
    try:
        event = ModelFallbackEvent(
            from_model=from_model or "",
            to_model=to_model,
            to_role=to_role,
            consecutive_capacity_errors=consecutive_capacity_errors,
            thread_id=thread_id,
        )
        stream_writer(custom_event(event.model_dump()))
    except Exception:
        logger.debug("model_fallback_event stream emission failed", exc_info=True)


def _emit_persistent_retry_event(
    *,
    attempt: int,
    error_type: str,
    backoff_seconds: float,
    elapsed_seconds: float,
    total_cap_seconds: float,
    thread_id: str | None,
    query_source: str,
    request: ModelRequest[Any] | None = None,
) -> None:
    """Emit a persistent-retry attempt event via stream_writer and log.

    Args:
        attempt: Zero-based retry attempt index.
        error_type: Exception type name that triggered the retry.
        backoff_seconds: Backoff delay before the next attempt.
        elapsed_seconds: Wall-clock elapsed since the retry sequence started.
        total_cap_seconds: Hard ceiling for the retry sequence.
        thread_id: Thread id for telemetry.
        query_source: Query source label for the in-flight request.
        request: The in-flight ModelRequest (for stream_writer access).
    """
    logger.debug(
        "persistent_retry: attempt=%d error=%s backoff=%.1fs elapsed=%.1fs/%.0fs "
        "thread_id=%s query_source=%s",
        attempt + 1,
        error_type,
        backoff_seconds,
        elapsed_seconds,
        total_cap_seconds,
        thread_id or "unknown",
        query_source,
    )
    if request is None:
        return
    stream_writer = getattr(getattr(request, "runtime", None), "stream_writer", None)
    if not callable(stream_writer):
        return
    try:
        event = LLMPersistentRetryEvent(
            attempt=attempt + 1,
            error_type=error_type,
            backoff_seconds=backoff_seconds,
            elapsed_seconds=elapsed_seconds,
            total_cap_seconds=total_cap_seconds,
            thread_id=thread_id,
            query_source=query_source,
        )
        stream_writer(custom_event(event.model_dump()))
    except Exception:
        logger.debug("persistent_retry_event stream emission failed", exc_info=True)


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


async def _sleep_with_heartbeat(
    delay: float,
    *,
    heartbeat_callback: Callable[[], None] | None = None,
    heartbeat_interval: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Sleep for *delay* seconds, yielding heartbeats at *heartbeat_interval*.

    If *heartbeat_callback* is provided, it is called every *heartbeat_interval*
    seconds during the sleep so the daemon sees periodic activity. The callback
    is synchronous and should be fast (e.g., emit a sentinel or log).

    Args:
        delay: Total sleep duration in seconds.
        heartbeat_callback: Optional callback invoked during sleep.
        heartbeat_interval: Interval between heartbeat callbacks.
    """
    if delay <= 0:
        return
    elapsed: float = 0.0
    while elapsed < delay:
        chunk = min(heartbeat_interval, delay - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk
        if heartbeat_callback is not None and elapsed < delay:
            heartbeat_callback()


class PersistentRetryRunner(AgentMiddleware):
    """Middleware wrapper adding persistent retry and resilience features.

    Wraps the upstream ``LLMRateLimitMiddleware`` by intercepting
    ``awrap_model_call``. When the inner middleware (or handler) raises a
    retriable error (429, 529/capacity, transient connection), this wrapper
    retries indefinitely (up to the total cap) with exponential backoff and
    heartbeat emission.

    Features:

    - **Persistent retry**: Exponential backoff (capped at
      ``persistent_retry_max_backoff_seconds`` per attempt, hard ceiling at
      ``persistent_retry_total_cap_seconds`` total). Heartbeats are emitted
      during backoff sleeps via the ``heartbeat_callback``.
    - **Query-source discrimination**: Background sources (compact,
      summary) bail immediately on 529/capacity errors — no retry amplification.
      Foreground sources retry persistently.
    - **Model fallback**: After ``fallback_model_threshold`` consecutive
      capacity errors, switches to the configured fallback model and emits
      a ``model_fallback_triggered`` event.
    - **Stale-connection detection**: On ECONNRESET/EPIPE, disables HTTP
      keep-alive for the retry and obtains a fresh connection.

    Attributes:
        name: Middleware name for the agent framework.
    """

    name = "PersistentRetryRunner"

    def __init__(
        self,
        *,
        config: LLMRateLimitConfig,
        fallback_model: str | None = None,
        fallback_model_role: ModelRole | None = None,
        fallback_model_threshold: int = 3,
        query_source_discrimination: bool = False,
        stale_connection_recovery: bool = True,
        heartbeat_callback: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the persistent retry runner.

        Args:
            config: Rate-limit configuration providing backoff/cap settings.
            fallback_model: Model spec to switch to after threshold capacity errors.
            fallback_model_role: Model router role (e.g. 'fast') to resolve
                the fallback model from the configured ModelRouter. Takes
                precedence over ``fallback_model`` when both are set.
            fallback_model_threshold: Consecutive capacity errors before fallback.
            query_source_discrimination: Enable background-source bail-on-529.
            stale_connection_recovery: Enable stale-connection recovery.
            heartbeat_callback: Optional callback invoked during backoff sleeps.
        """
        super().__init__()
        self._config = config
        self._fallback_model = fallback_model
        self._fallback_model_role = fallback_model_role
        self._fallback_model_threshold = max(1, fallback_model_threshold)
        self._query_source_discrimination = query_source_discrimination
        self._stale_connection_recovery = stale_connection_recovery
        self._heartbeat_callback = heartbeat_callback
        self._consecutive_capacity_errors: int = 0
        self._fallback_active: bool = False

    @staticmethod
    def _thread_id_from_request(request: ModelRequest[Any]) -> str:
        """Extract thread_id from a ModelRequest's runtime config.

        Falls back to ``"default"`` when no thread_id is present.
        """
        runtime = getattr(request, "runtime", None)
        config = getattr(runtime, "config", None) if runtime is not None else None
        if isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                thread_id = configurable.get("thread_id")
                if isinstance(thread_id, str) and thread_id:
                    return thread_id
        return "default"

    @staticmethod
    def _resolve_query_source(request: ModelRequest[Any]) -> QuerySource:
        """Determine the query source from request metadata.

        Looks for ``request.model_settings["query_source"]``; defaults to
        :attr:`QuerySource.MAIN_LOOP` when absent.
        """
        model_settings = getattr(request, "model_settings", None)
        if isinstance(model_settings, dict):
            raw = model_settings.get("query_source")
            if isinstance(raw, QuerySource):
                return raw
            if isinstance(raw, str):
                try:
                    return QuerySource(raw)
                except ValueError:
                    pass
        return QuerySource.main_loop

    def _maybe_get_fallback_model(self, request: ModelRequest[Any]) -> Any | None:
        """Return a fallback chat model instance if configured and not yet active.

        Resolution order:

        1. **Role-based** (preferred): When ``fallback_model_role`` is set,
           resolve via ``SootheConfig.create_chat_model(role)`` which uses
           the configured ``ModelRouter`` role→spec mapping. This reuses
           provider/model caching and the router's fallback chain.
        2. **Spec-based**: When only ``fallback_model`` is set, create via
           ``SootheConfig.create_chat_model_for_spec``.

        Returns ``None`` when no fallback is configured, the fallback is
        already active, or model creation fails.
        """
        if self._fallback_active:
            return None
        has_role = self._fallback_model_role is not None
        has_spec = self._fallback_model is not None
        if not has_role and not has_spec:
            return None

        runtime = getattr(request, "runtime", None)
        config_obj = getattr(runtime, "config", None) if runtime is not None else None
        configurable = config_obj.get("configurable", {}) if isinstance(config_obj, dict) else {}
        soothe_config = configurable.get("soothe_config") or configurable.get("config")

        try:
            if has_role:
                create_role = getattr(soothe_config, "create_chat_model", None)
                if callable(create_role):
                    model = create_role(self._fallback_model_role)
                    self._fallback_active = True
                    return model
            if has_spec:
                create_spec = getattr(soothe_config, "create_chat_model_for_spec", None)
                if callable(create_spec):
                    model = create_spec(self._fallback_model)
                    self._fallback_active = True
                    return model
        except Exception:
            label = (
                f"role={self._fallback_model_role}" if has_role else f"spec={self._fallback_model}"
            )
            logger.warning(
                "PersistentRetryRunner: failed to create fallback model (%s)",
                label,
                exc_info=True,
            )
        return None

    def _disable_keepalive_for_retry(self, request: ModelRequest[Any]) -> None:
        """Disable HTTP keep-alive on the model for the next retry attempt.

        Sets ``model.model_kwargs["extra_body"]["keep_alive"] = False`` or
        equivalent provider-specific flag when available. This forces a fresh
        connection on the next request.
        """
        model = getattr(request, "model", None)
        if model is None:
            return
        model_kwargs = getattr(model, "model_kwargs", None)
        if not isinstance(model_kwargs, dict):
            model_kwargs = {}
            try:
                setattr(model, "model_kwargs", model_kwargs)
            except (AttributeError, TypeError):
                return
        extra_body = model_kwargs.get("extra_body")
        if not isinstance(extra_body, dict):
            extra_body = {}
            model_kwargs["extra_body"] = extra_body
        extra_body["keep_alive"] = False

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Wrap a model call with persistent retry and resilience features.

        Args:
            request: The model request.
            handler: The next handler in the middleware chain.

        Returns:
            The model response.

        Raises:
            Exception: When all retries are exhausted or a non-retriable error occurs.
        """
        thread_id = self._thread_id_from_request(request)
        query_source = self._resolve_query_source(request)
        budget_key = resolve_llm_budget_key(thread_id)

        is_background = query_source in _BACKGROUND_QUERY_SOURCES
        max_backoff = self._config.persistent_retry_max_backoff_seconds
        total_cap = self._config.persistent_retry_total_cap_seconds
        base_backoff = self._config.rate_limit_backoff_base

        start_time = time.monotonic()
        attempt: int = 0

        # Use the current request (possibly with fallback model applied).
        current_request = request

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= total_cap:
                logger.warning(
                    "PersistentRetryRunner: total cap %.0fs reached (thread_id=%s, "
                    "query_source=%s, attempts=%d)",
                    total_cap,
                    thread_id,
                    query_source.value,
                    attempt,
                )
                msg = (
                    f"Persistent retry total cap {total_cap:.0f}s reached "
                    f"(query_source={query_source.value}, attempts={attempt})"
                )
                raise TimeoutError(msg)

            async def _invoke() -> ModelResponse[Any]:
                return await handler(current_request)

            try:
                result = await run_llm_call_with_policy(
                    _invoke,
                    config=self._config,
                    budget_key=budget_key,
                    thread_id=thread_id,
                    prompt_chars=_estimate_prompt_chars(current_request),
                    log_prefix="PersistentRetry",
                    log=logger,
                )
                self._consecutive_capacity_errors = 0
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not _is_persistent_retriable(exc):
                    raise

                # Background sources bail immediately on 529/capacity errors.
                if self._query_source_discrimination and is_background and _is_capacity_error(exc):
                    logger.info(
                        "PersistentRetryRunner: background query_source=%s bailing "
                        "on capacity error (thread_id=%s)",
                        query_source.value,
                        thread_id,
                    )
                    raise

                # Track consecutive capacity errors for model fallback.
                if _is_capacity_error(exc):
                    self._consecutive_capacity_errors += 1
                    has_role = self._fallback_model_role is not None
                    has_spec = self._fallback_model is not None
                    if (
                        (has_role or has_spec)
                        and not self._fallback_active
                        and self._consecutive_capacity_errors >= self._fallback_model_threshold
                    ):
                        fallback = self._maybe_get_fallback_model(current_request)
                        if fallback is not None:
                            to_model_label = (
                                f"role:{self._fallback_model_role}"
                                if has_role
                                else self._fallback_model or "unknown"
                            )
                            raw_from = getattr(
                                getattr(current_request, "model", None),
                                "model",
                                None,
                            )
                            from_label = str(raw_from) if raw_from is not None else ""
                            _emit_model_fallback_event(
                                from_model=from_label,
                                to_model=to_model_label,
                                to_role=self._fallback_model_role if has_role else None,
                                consecutive_capacity_errors=self._consecutive_capacity_errors,
                                thread_id=thread_id,
                                request=current_request,
                            )
                            current_request = _replace_model_in_request(current_request, fallback)
                            self._consecutive_capacity_errors = 0
                            continue
                else:
                    # Non-capacity retriable error resets the capacity counter.
                    self._consecutive_capacity_errors = 0

                # Stale-connection recovery — disable keep-alive for retry.
                if self._stale_connection_recovery and _is_stale_connection_error(exc):
                    logger.info(
                        "PersistentRetryRunner: stale connection detected "
                        "(thread_id=%s, error=%s), disabling keep-alive for retry",
                        thread_id,
                        type(exc).__name__,
                    )
                    self._disable_keepalive_for_retry(current_request)

                # Compute backoff and sleep with heartbeat.
                backoff = _calc_persistent_backoff(
                    attempt,
                    base=base_backoff,
                    max_backoff=max_backoff,
                )
                remaining = total_cap - (time.monotonic() - start_time)
                if backoff > remaining:
                    backoff = remaining
                if backoff <= 0:
                    raise

                elapsed_now = time.monotonic() - start_time
                logger.warning(
                    "PersistentRetryRunner: retrying after %s (attempt %d, "
                    "backoff=%.1fs, elapsed=%.1fs/%.0fs, thread_id=%s, "
                    "query_source=%s)",
                    type(exc).__name__,
                    attempt + 1,
                    backoff,
                    elapsed_now,
                    total_cap,
                    thread_id,
                    query_source.value,
                )

                _emit_persistent_retry_event(
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    backoff_seconds=backoff,
                    elapsed_seconds=elapsed_now,
                    total_cap_seconds=total_cap,
                    thread_id=thread_id,
                    query_source=query_source.value,
                    request=current_request,
                )

                await _sleep_with_heartbeat(
                    backoff,
                    heartbeat_callback=self._heartbeat_callback,
                )
                attempt += 1


def _estimate_prompt_chars(request: ModelRequest[Any]) -> int:
    """Estimate total prompt character count from a ModelRequest.

    Args:
        request: The model request.

    Returns:
        Approximate character count of system prompt + messages.
    """
    total = 0
    system_prompt = getattr(request, "system_prompt", None)
    if isinstance(system_prompt, str):
        total += len(system_prompt)
    elif system_prompt:
        total += len(str(system_prompt))
    for msg in getattr(request, "messages", []):
        total += len(str(getattr(msg, "content", "") or ""))
    return total


def _replace_model_in_request(
    request: ModelRequest[Any],
    new_model: Any,
) -> ModelRequest[Any]:
    """Return a copy of *request* with the model replaced by *new_model*.

    ModelRequest is a frozen-ish dataclass; we use object.__new__ and copy
    fields to avoid mutating the original.
    """
    import dataclasses

    if dataclasses.is_dataclass(request):
        new_request = dataclasses.replace(request, model=new_model)
        return new_request
    # Fallback: shallow copy with model override.
    new_request = object.__new__(type(request))
    new_request.__dict__.update(request.__dict__)
    setattr(new_request, "model", new_model)
    return new_request


__all__ = [
    "EnhancedTimeoutError",
    "PersistentRetryRunner",
    "await_with_llm_call_policy",
    "llm_rate_limit_config_from",
    "run_with_llm_call_policy_sync",
]
