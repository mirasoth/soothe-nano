"""Tool error handling decorator."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from soothe_nano._rust_compat import (
    is_llm_argument_error_rust as _is_llm_argument_error_rust,
)
from soothe_nano._rust_compat import (
    is_unexpected_keyword_error_rust as _is_unexpected_keyword_error_rust,
)
from soothe_nano._rust_compat import (
    is_warning_level_error_rust as _is_warning_level_error_rust,
)
from soothe_nano._rust_compat import (
    simplify_error_rust as _simplify_error_rust,
)
from soothe_nano._rust_compat import (
    unexpected_kwarg_name_rust as _unexpected_kwarg_name_rust,
)

logger = logging.getLogger(__name__)

# HTTP status codes for warning-level errors
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429

_RETRY_FAILED = object()


def tool_error_handler(tool_name: str, return_type: str = "dict") -> Callable[[Callable], Callable]:
    """Decorator for standardized tool error handling.

    Args:
        tool_name: Name of the tool for logging
        return_type: "dict" returns {"error": msg}, "str" returns "Error: msg"

    Catches all exceptions and returns an error response instead of raising.

    Also filters unexpected keyword arguments (common when LLMs invent
    parameters such as `limit`) before invoking the tool, logging a
    warning and continuing with accepted args instead of failing hard.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            call_kwargs = _prepare_kwargs(tool_name, func, kwargs)
            try:
                return func(*args, **call_kwargs)
            except Exception as exc:
                if _is_unexpected_keyword_error(exc):
                    retried = _retry_without_unexpected_kwarg(func, args, call_kwargs, exc)
                    if retried is not _RETRY_FAILED:
                        logger.warning(
                            "%s recovered from unexpected argument: %s",
                            tool_name,
                            _unexpected_kwarg_name(exc) or "unknown",
                        )
                        return retried
                return _format_error_response(tool_name, return_type, exc)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            call_kwargs = _prepare_kwargs(tool_name, func, kwargs)
            try:
                return await func(*args, **call_kwargs)
            except Exception as exc:
                if _is_unexpected_keyword_error(exc):
                    retried = await _retry_without_unexpected_kwarg_async(
                        func, args, call_kwargs, exc
                    )
                    if retried is not _RETRY_FAILED:
                        logger.warning(
                            "%s recovered from unexpected argument: %s",
                            tool_name,
                            _unexpected_kwarg_name(exc) or "unknown",
                        )
                        return retried
                return _format_error_response(tool_name, return_type, exc)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def _prepare_kwargs(
    tool_name: str,
    func: Callable[..., Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Drop kwargs the tool function does not accept; log ignored names."""
    kept, dropped = _filter_kwargs(func, kwargs)
    if dropped:
        logger.warning(
            "%s ignoring unexpected arguments: %s",
            tool_name,
            ", ".join(sorted(dropped)),
        )
    return kept


def _filter_kwargs(
    func: Callable[..., Any],
    kwargs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split kwargs into accepted vs dropped for `func`'s signature.

    Returns:
        `(kept, dropped)`. If `func` accepts `**kwargs`, nothing is
        dropped.
    """
    accepted = _accepted_param_names(func)
    if accepted is None:
        return kwargs, {}
    kept = {key: value for key, value in kwargs.items() if key in accepted}
    dropped = {key: value for key, value in kwargs.items() if key not in accepted}
    return kept, dropped


def _accepted_param_names(func: Callable[..., Any]) -> set[str] | None:
    """Return accepted keyword parameter names, or None if `**kwargs` is ok."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return None

    names: set[str] = set()
    for name, param in signature.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return None
        if param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            names.add(name)
    return names


def _retry_without_unexpected_kwarg(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exc: Exception,
) -> Any:
    """Strip the named unexpected kwarg and retry once (sync)."""
    bad_name = _unexpected_kwarg_name(exc)
    if not bad_name or bad_name not in kwargs:
        return _RETRY_FAILED
    cleaned = {key: value for key, value in kwargs.items() if key != bad_name}
    try:
        return func(*args, **cleaned)
    except Exception:
        return _RETRY_FAILED


async def _retry_without_unexpected_kwarg_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exc: Exception,
) -> Any:
    """Strip the named unexpected kwarg and retry once (async)."""
    bad_name = _unexpected_kwarg_name(exc)
    if not bad_name or bad_name not in kwargs:
        return _RETRY_FAILED
    cleaned = {key: value for key, value in kwargs.items() if key != bad_name}
    try:
        return await func(*args, **cleaned)
    except Exception:
        return _RETRY_FAILED


def _format_error_response(tool_name: str, return_type: str, exc: Exception) -> Any:
    """Log the failure and build the tool-facing error payload."""
    error_msg = _simplify_error(exc)
    if _is_warning_level_error(exc):
        logger.warning("%s failed: %s", tool_name, error_msg)
    else:
        logger.exception("%s failed: %s", tool_name, error_msg)
    if return_type == "dict":
        return {"error": error_msg}
    return f"Error: {error_msg}"


def _is_unexpected_keyword_error(exc: Exception) -> bool:
    """Return True for TypeError about an unexpected keyword argument (delegates to Rust)."""
    if not isinstance(exc, TypeError):
        return False
    return _is_unexpected_keyword_error_rust(str(exc))


def _unexpected_kwarg_name(exc: Exception) -> str | None:
    """Extract the unexpected keyword name from a TypeError message (delegates to Rust)."""
    return _unexpected_kwarg_name_rust(str(exc))


def _is_llm_argument_error(exc: Exception) -> bool:
    """Return True for recoverable LLM tool-argument TypeErrors (delegates to Rust)."""
    if not isinstance(exc, TypeError):
        return False
    return _is_llm_argument_error_rust(type(exc).__name__, str(exc))


def _is_warning_level_error(exc: Exception) -> bool:
    """Check if error should be logged as warning instead of error (delegates to Rust).

    Args:
        exc: Exception to check

    Returns:
        True if this should be logged as warning (non-critical/recoverable),
        False if it should be logged as error (unexpected/critical)
    """
    error_type = type(exc).__name__
    error_msg = str(exc)

    # Extract HTTP status from the exception or its response object.
    status: int | None = getattr(exc, "status", None)
    if status is None:
        response = getattr(exc, "response", None)
        if response is not None:
            status = getattr(response, "status_code", getattr(response, "status", None))

    return _is_warning_level_error_rust(error_type, error_msg, status)


def _simplify_error(exc: Exception) -> str:
    """Convert exception to user-friendly message (delegates to Rust).

    The Rust implementation handles all string-pattern matching: unexpected
    keyword arguments, missing required arguments, DNS/network errors, timeout
    detection, and HTTP status formatting. Python extracts the status code from
    the exception's ``.response`` attribute when the exception itself has no
    ``.status``.
    """
    error_type = type(exc).__name__
    error_msg = str(exc)

    # Extract HTTP status from the exception or its response object.
    status: int | None = getattr(exc, "status", None)
    if status is None:
        response = getattr(exc, "response", None)
        if response is not None:
            status = getattr(response, "status_code", getattr(response, "status", None))

    return _simplify_error_rust(error_type, error_msg, status)
