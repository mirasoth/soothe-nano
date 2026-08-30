"""Swap the chat model for a single stream when a daemon/TUI override is active."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from soothe_nano.utils.runtime import get_stream_model_override

logger = logging.getLogger(__name__)


class PerTurnModelMiddleware(AgentMiddleware):
    """Replace the chat model for a single stream when a per-stream override is active.

    Reads the override set via ``attach_stream_model_override`` and, when
    present, builds a model from the spec/params and swaps it onto the
    request before delegating to the handler. Failures fall back to the
    default model.

    Args:
        config: SootheConfig providing ``create_chat_model_for_spec``.

    Example:
        mw = PerTurnModelMiddleware(config)
    """

    name = "PerTurnModelMiddleware"

    def __init__(self, config: Any) -> None:
        """Store the SootheConfig used to build per-stream override models.

        Args:
            config: SootheConfig instance from the running daemon / runner.
        """
        super().__init__()
        self._config = config

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        override = get_stream_model_override()
        if not override:
            return handler(request)
        spec, params = override
        try:
            model = self._config.create_chat_model_for_spec(spec, model_params=params)
        except Exception:
            logger.exception("Per-turn model override failed for %s; using default model", spec)
            return handler(request)
        return handler(request.override(model=model))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        override = get_stream_model_override()
        if not override:
            return await handler(request)
        spec, params = override
        try:
            model = self._config.create_chat_model_for_spec(spec, model_params=params)
        except Exception:
            logger.exception("Per-turn model override failed for %s; using default model", spec)
            return await handler(request)
        return await handler(request.override(model=model))
