"""Tool error handling decorator."""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# HTTP status codes for warning-level errors
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429

_UNEXPECTED_KWARG_RE = re.compile(r"got an unexpected keyword argument ['\"](?P<name>[^'\"]+)['\"]")
_MISSING_REQUIRED_RE = re.compile(r"missing (?P<count>\d+) required positional argument")

_RETRY_FAILED = object()


def tool_error_handler(tool_name: str, return_type: str = "dict") -> Callable[[Callable], Callable]:
    """Decorator for standardized tool error handling.

    Args:
        tool_name: Name of the tool for logging
        return_type: "dict" returns {"error": msg}, "str" returns "Error: msg"

    Catches all exceptions and returns an error response instead of raising.

    Also filters unexpected keyword arguments (common when LLMs invent
    parameters such as ``limit``) before invoking the tool, logging a
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
    """Split kwargs into accepted vs dropped for ``func``'s signature.

    Returns:
        ``(kept, dropped)``. If ``func`` accepts ``**kwargs``, nothing is
        dropped.
    """
    accepted = _accepted_param_names(func)
    if accepted is None:
        return kwargs, {}
    kept = {key: value for key, value in kwargs.items() if key in accepted}
    dropped = {key: value for key, value in kwargs.items() if key not in accepted}
    return kept, dropped


def _accepted_param_names(func: Callable[..., Any]) -> set[str] | None:
    """Return accepted keyword parameter names, or None if ``**kwargs`` is ok."""
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
    """Return True for TypeError about an unexpected keyword argument."""
    return isinstance(exc, TypeError) and "unexpected keyword argument" in str(exc)


def _unexpected_kwarg_name(exc: Exception) -> str | None:
    """Extract the unexpected keyword name from a TypeError message."""
    match = _UNEXPECTED_KWARG_RE.search(str(exc))
    return match.group("name") if match else None


def _is_llm_argument_error(exc: Exception) -> bool:
    """Return True for recoverable LLM tool-argument TypeErrors."""
    if not isinstance(exc, TypeError):
        return False
    message = str(exc)
    return (
        "unexpected keyword argument" in message
        or "required positional argument" in message
        or "required keyword-only argument" in message
    )


def _is_warning_level_error(exc: Exception) -> bool:
    """Check if error should be logged as warning instead of error.

    Args:
        exc: Exception to check

    Returns:
        True if this should be logged as warning (non-critical/recoverable),
        False if it should be logged as error (unexpected/critical)
    """
    if _is_llm_argument_error(exc):
        return True

    # Check for HTTP 403 Forbidden (API key issues, access denied)
    status = getattr(exc, "status", None)
    if status == HTTP_FORBIDDEN:
        return True

    # Check for HTTP 429 Too Many Requests (rate limiting)
    if status == HTTP_TOO_MANY_REQUESTS:
        return True

    # Check response object for status
    response = getattr(exc, "response", None)
    if response is not None:
        resp_status = getattr(response, "status_code", getattr(response, "status", None))
        if resp_status in (HTTP_FORBIDDEN, HTTP_TOO_MANY_REQUESTS):
            return True

    # Default: log as error
    return False


def _simplify_error(exc: Exception) -> str:
    """Convert exception to user-friendly message."""
    error_type = type(exc).__name__
    error_msg = str(exc)

    if _is_unexpected_keyword_error(exc):
        bad_name = _unexpected_kwarg_name(exc)
        if bad_name:
            return (
                f"Unexpected argument '{bad_name}'. "
                "Omit unknown parameters and retry with only the documented tool inputs."
            )
        return (
            "Unexpected tool argument. "
            "Omit unknown parameters and retry with only the documented tool inputs."
        )

    if isinstance(exc, TypeError) and (
        "required positional argument" in error_msg or "required keyword-only argument" in error_msg
    ):
        count_match = _MISSING_REQUIRED_RE.search(error_msg)
        if count_match:
            return (
                f"Missing {count_match.group('count')} required argument(s). "
                "Check the tool schema and retry with the documented inputs."
            )
        return "Missing required argument(s). Check the tool schema and retry."

    # DNS/Network errors
    if "nodename nor servname" in error_msg:
        return "DNS resolution failed - invalid domain name"
    if "ConnectError" in error_type or "ConnectionError" in error_type:
        if "Connection refused" in error_msg:
            return "Connection refused - service may not be running"
        return "Connection failed - network unreachable or service down"
    if "Timeout" in error_type or "timeout" in error_msg.lower():
        return "Request timed out"

    # HTTP errors - check response object
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", "unknown")
        return f"HTTP error {status}"

    # Default: show type and message
    return f"{error_type}: {error_msg}"
