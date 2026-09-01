"""Catch-all tool error guard — converts unhandled tool exceptions into error ToolMessages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

logger = logging.getLogger(__name__)

# Truncate the captured exception text so a verbose traceback does not blow
# out the model context when the failure message is returned as a ToolMessage.
_MAX_TOOL_ERROR_CHARS = 2000


class ToolErrorGuardMiddleware(AgentMiddleware):
    """Convert any unhandled tool exception into an error ``ToolMessage``."""

    name = "ToolErrorGuardMiddleware"

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            return await handler(request)
        except asyncio.CancelledError:
            raise
        except GraphBubbleUp:
            raise
        except Exception as exc:
            tool_call = request.tool_call or {}
            tool_name = str(tool_call.get("name", "tool"))
            tool_call_id = tool_call.get("id")
            if not tool_call_id:
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
