"""Middleware that persists large tool results to disk with compact references.

Sits before ToolOutputCapMiddleware in the stack. Intercepts large results
and replaces them with disk-backed compact references. The model can
re-fetch the full output via read_file if needed.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe_nano.middleware.tool_result_storage import (
    DEFAULT_PER_MESSAGE_BUDGET_CHARS,
    DEFAULT_PERSIST_THRESHOLD_CHARS,
    DEFAULT_PREVIEW_CHARS,
    is_persisted_content,
    maybe_persist_tool_result,
)

logger = logging.getLogger(__name__)


class ToolResultStorageMiddleware(AgentMiddleware):
    """Persist large tool results to disk, replacing content with references.

    Operates in two modes:

    1. **Per-tool persistence** (awrap_tool_call): When a single tool result
       exceeds the persistence threshold, write it to disk and replace the
       content with a compact reference containing the file path and a preview.

    2. **Per-message budget** (awrap_model_call): When the aggregate size of
       tool results in a single turn exceeds the per-message budget, persist
       the largest results to disk until under budget.

    The middleware is idempotent: re-application on subsequent hops is a
    no-op because persisted results are already replaced with references
    (detected by the ``<persisted-output>`` tag prefix).
    """

    name = "ToolResultStorageMiddleware"

    def __init__(
        self,
        *,
        workspace_root: str,
        session_id: str = "",
        persist_threshold: int = DEFAULT_PERSIST_THRESHOLD_CHARS,
        per_message_budget: int = DEFAULT_PER_MESSAGE_BUDGET_CHARS,
        preview_chars: int = DEFAULT_PREVIEW_CHARS,
    ) -> None:
        super().__init__()
        self._workspace_root = workspace_root
        self._session_id = session_id
        self._persist_threshold = persist_threshold
        self._per_message_budget = per_message_budget
        self._preview_chars = preview_chars

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Persist large single-tool results to disk after execution.

        Args:
            request: Tool call request.
            handler: Next handler in the middleware chain.

        Returns:
            ToolMessage with compact reference if persisted, or original
            result if under threshold.
        """
        result = await handler(request)

        if isinstance(result, ToolMessage):
            content = str(result.content or "")
            if is_persisted_content(content):
                return result
            if len(content) <= self._persist_threshold:
                return result
            return maybe_persist_tool_result(
                result,
                self._session_id,
                Path(self._workspace_root),
                self._persist_threshold,
                self._preview_chars,
            )

        if isinstance(result, Command):
            update = result.update
            if isinstance(update, dict):
                messages = update.get("messages")
                if isinstance(messages, list):
                    patched: list[Any] = []
                    changed = False
                    for msg in messages:
                        if isinstance(msg, ToolMessage):
                            content = str(msg.content or "")
                            if (
                                not is_persisted_content(content)
                                and len(content) > self._persist_threshold
                            ):
                                msg = maybe_persist_tool_result(
                                    msg,
                                    self._session_id,
                                    Path(self._workspace_root),
                                    self._persist_threshold,
                                    self._preview_chars,
                                )
                                changed = True
                        patched.append(msg)
                    if changed:
                        return Command(update={**update, "messages": patched})
        return result

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Enforce per-message aggregate budget on tool results.

        Args:
            request: Model request containing messages.
            handler: Next handler in the middleware chain.

        Returns:
            Model response from handler (with possibly modified messages).
        """
        messages = list(getattr(request, "messages", None) or [])
        if not messages:
            return await handler(request)

        candidates: list[tuple[int, ToolMessage, int]] = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                content = str(msg.content or "")
                if is_persisted_content(content):
                    continue
                size = len(content)
                if size > self._persist_threshold:
                    candidates.append((i, msg, size))

        if not candidates:
            return await handler(request)

        total_size = sum(size for _, _, size in candidates)
        if total_size <= self._per_message_budget:
            return await handler(request)

        candidates.sort(key=lambda x: x[2], reverse=True)

        patched = list(messages)
        changed = False
        for idx, msg, size in candidates:
            if total_size <= self._per_message_budget:
                break
            persisted = maybe_persist_tool_result(
                msg,
                self._session_id,
                Path(self._workspace_root),
                self._persist_threshold,
                self._preview_chars,
            )
            if persisted is not msg:
                patched[idx] = persisted
                new_size = len(str(persisted.content or ""))
                total_size -= size - new_size
                changed = True

        if changed:
            request = request.override(messages=patched)
        return await handler(request)
