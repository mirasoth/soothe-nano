"""Catch-all tool error guard for the CoreAgent middleware stack.

A tool that raises an exception the inner handlers do not classify as a
recoverable invocation error is normally re-raised up the graph stream,
aborting the *entire* execute step. A single failing tool call then loses
all accumulated work in that step.

This middleware is the last-chance outer wrapper around tool execution: any
exception that escapes the inner tool-call chain is converted into an
``error`` ``ToolMessage`` so the agent can observe the failure and
self-correct (retry, adjust arguments, or report the error) instead of the
whole step dying. It sits outside the network-error recovery middleware so
that path keeps its tailored wording; only the exceptions it re-raises land
here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)

# Truncate the captured exception text so a verbose traceback does not blow
# out the model context when the failure message is returned as a ToolMessage.
_MAX_TOOL_ERROR_CHARS = 2000


class ToolErrorGuardMiddleware(AgentMiddleware):
    """Convert any unhandled tool exception into an error ``ToolMessage``.

    Positioned outer to the network-error recovery middleware so it catches
    the exceptions that path re-raises. Tools returning their own error
    strings are unaffected; only exceptions escaping every inner handler
    and the graph's default tool-error catch are handled here.
    ``CancelledError`` is re-raised so cooperative shutdown is unaffected.

    Example:
        mw = ToolErrorGuardMiddleware()
    """

    name = "ToolErrorGuardMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            return await handler(request)
        except Exception as exc:
            # ``CancelledError`` is not an error — propagate so cooperative
            # shutdown during step interrupts is unaffected.
            if isinstance(exc, asyncio.CancelledError):
                raise
            tool_call = request.tool_call or {}
            tool_name = str(tool_call.get("name", "tool"))
            tool_call_id = tool_call.get("id")
            if not tool_call_id:
                # ToolMessage requires a non-None ``tool_call_id``; synthesize a
                # stable fallback so an error from a malformed/partial tool call
                # still surfaces as a recoverable ToolMessage rather than raising.
                tool_call_id = f"_error_guard_{tool_name}"
            error_text = self._format_error(exc, tool_name)
            logger.warning(
                "[ToolErrorGuard] %s raised %s — surfacing as error ToolMessage "
                "so the step can continue (step would otherwise abort)",
                tool_name,
                type(exc).__name__,
                exc_info=True,
            )
            return ToolMessage(
                content=error_text,
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
            )

    @staticmethod
    def _format_error(exc: BaseException, tool_name: str) -> str:
        """Build a compact, agent-actionable error message from an exception."""
        exc_type = type(exc).__name__
        msg = str(exc).strip()
        if not msg:
            msg = "(no detail)"
        text = f"Error: tool '{tool_name}' raised {exc_type}: {msg}"
        if len(text) > _MAX_TOOL_ERROR_CHARS:
            text = text[:_MAX_TOOL_ERROR_CHARS] + "\n...[truncated]"
        return text
