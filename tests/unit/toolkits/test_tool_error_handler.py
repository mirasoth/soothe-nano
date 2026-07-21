"""Tests for tool error handler decorator."""

from __future__ import annotations

import asyncio
import logging

from soothe_nano.utils.tool_error_handler import (
    _filter_kwargs,
    _simplify_error,
    tool_error_handler,
)


class TestToolErrorHandler:
    """Test the tool error handler decorator."""

    def test_sync_function_success(self):
        """Successful sync function should return result unchanged."""

        @tool_error_handler("test_tool", return_type="dict")
        def sync_func():
            return {"data": "success"}

        result = sync_func()
        assert result == {"data": "success"}

    def test_sync_function_exception_dict_return(self):
        """Sync function exception should return error dict."""

        @tool_error_handler("test_tool", return_type="dict")
        def sync_func():
            raise ValueError("Test error")

        result = sync_func()
        assert "error" in result
        assert "ValueError" in result["error"]
        assert "Test error" in result["error"]

    def test_sync_function_exception_str_return(self):
        """Sync function exception should return error string."""

        @tool_error_handler("test_tool", return_type="str")
        def sync_func():
            raise ValueError("Test error")

        result = sync_func()
        assert result.startswith("Error:")
        assert "ValueError" in result

    def test_async_function_success(self):
        """Successful async function should return result unchanged."""

        @tool_error_handler("test_tool", return_type="dict")
        async def async_func():
            return {"data": "success"}

        result = asyncio.run(async_func())
        assert result == {"data": "success"}

    def test_async_function_exception_dict_return(self):
        """Async function exception should return error dict."""

        @tool_error_handler("test_tool", return_type="dict")
        async def async_func():
            raise ValueError("Test async error")

        result = asyncio.run(async_func())
        assert "error" in result
        assert "ValueError" in result["error"]
        assert "Test async error" in result["error"]

    def test_async_function_exception_str_return(self):
        """Async function exception should return error string."""

        @tool_error_handler("test_tool", return_type="str")
        async def async_func():
            raise ValueError("Test async error")

        result = asyncio.run(async_func())
        assert result.startswith("Error:")
        assert "ValueError" in result

    def test_preserves_function_metadata(self):
        """Decorator should preserve function name and docstring."""

        @tool_error_handler("test_tool", return_type="dict")
        def my_function():
            """My docstring."""
            return {"data": "test"}

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_ignores_unexpected_kwargs_and_succeeds(self, caplog):
        """LLM-invented kwargs are dropped; tool still runs."""

        @tool_error_handler("wizsearch_search", return_type="str")
        def search(query: str, max_results_per_engine: int = 10) -> str:
            return f"{query}:{max_results_per_engine}"

        with caplog.at_level(logging.WARNING):
            result = search(query="python", limit=5, max_results_per_engine=3)

        assert result == "python:3"
        assert any("ignoring unexpected arguments: limit" in r.message for r in caplog.records)

    def test_async_ignores_unexpected_kwargs_and_succeeds(self, caplog):
        """Async path also drops invented kwargs without TypeError."""

        @tool_error_handler("wizsearch_search", return_type="str")
        async def search(query: str) -> str:
            return f"ok:{query}"

        with caplog.at_level(logging.WARNING):
            result = asyncio.run(search(query="asyncio", limit=5))

        assert result == "ok:asyncio"
        assert any("ignoring unexpected arguments: limit" in r.message for r in caplog.records)

    def test_missing_required_arg_friendly_message(self, caplog):
        """Missing required args return a schema hint, not a raw TypeError."""

        @tool_error_handler("test_tool", return_type="str")
        def search(query: str) -> str:
            return query

        with caplog.at_level(logging.WARNING):
            result = search()

        assert result.startswith("Error:")
        assert "Missing" in result
        assert "TypeError" not in result
        assert not any(r.exc_info for r in caplog.records if r.levelno >= logging.ERROR)

    def test_var_kwargs_not_filtered(self):
        """Functions that accept **kwargs keep all arguments."""

        @tool_error_handler("test_tool", return_type="dict")
        def flexible(**kwargs):
            return kwargs

        assert flexible(query="q", limit=1) == {"query": "q", "limit": 1}


class TestFilterKwargs:
    """Unit tests for kwargs filtering helpers."""

    def test_filter_drops_unknown(self):
        def search(query: str, limit: int = 10) -> str:
            return query

        kept, dropped = _filter_kwargs(search, {"query": "q", "foo": 1, "limit": 2})
        assert kept == {"query": "q", "limit": 2}
        assert dropped == {"foo": 1}

    def test_filter_keeps_all_with_var_keyword(self):
        def search(**kwargs):
            return kwargs

        kept, dropped = _filter_kwargs(search, {"a": 1, "b": 2})
        assert kept == {"a": 1, "b": 2}
        assert dropped == {}


class TestSimplifyError:
    """Test error message simplification."""

    def test_dns_resolution_error(self):
        """DNS errors should be simplified."""
        exc = Exception("nodename nor servname provided, or not known")
        msg = _simplify_error(exc)
        assert "DNS resolution failed" in msg
        assert "invalid domain" in msg.lower()

    def test_connection_refused_error(self):
        """Connection refused should be identified."""
        exc = ConnectionError("Connection refused")
        msg = _simplify_error(exc)
        assert "Connection refused" in msg
        assert "service may not be running" in msg

    def test_connection_error(self):
        """Generic connection errors should be simplified."""
        exc = ConnectionError("Network is unreachable")
        msg = _simplify_error(exc)
        assert "Connection failed" in msg

    def test_timeout_error(self):
        """Timeout errors should be identified."""
        exc = TimeoutError("Operation timed out")
        msg = _simplify_error(exc)
        assert "timed out" in msg.lower()

    def test_generic_exception(self):
        """Generic exceptions should show type and message."""
        exc = ValueError("Something went wrong")
        msg = _simplify_error(exc)
        assert "ValueError" in msg
        assert "Something went wrong" in msg

    def test_unexpected_keyword_argument(self):
        """Unexpected kwargs become actionable guidance without TypeError noise."""
        exc = TypeError("WizsearchSearchTool._arun() got an unexpected keyword argument 'limit'")
        msg = _simplify_error(exc)
        assert "Unexpected argument 'limit'" in msg
        assert "Omit unknown parameters" in msg
        assert "TypeError" not in msg

    def test_missing_required_argument(self):
        """Missing required args become a schema hint."""
        exc = TypeError("search() missing 1 required positional argument: 'query'")
        msg = _simplify_error(exc)
        assert "Missing 1 required argument" in msg
        assert "TypeError" not in msg
