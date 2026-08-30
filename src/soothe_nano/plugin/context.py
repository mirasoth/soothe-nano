"""Factory for `PluginContext` instances wired to Soothe's logging and events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_sdk.plugin import PluginContext

if TYPE_CHECKING:
    from soothe_nano.config.settings import SootheConfig

logger = logging.getLogger(__name__)


def create_plugin_context(
    plugin_name: str,
    config: dict[str, Any],
    soothe_config: SootheConfig,
    emit_event_callback: Any | None = None,
    **extra_context: Any,
) -> PluginContext:
    """Create a `PluginContext` for a plugin.

    Wires a plugin-specific logger (`soothe.plugins.<plugin_name>`) and an
    event-emission wrapper. When `emit_event_callback` is `None`, events are
    logged at debug level instead of emitted. Extra keyword arguments are
    attached as attributes on the returned context.

    Args:
        plugin_name: Plugin name (used for logger naming).
        config: Plugin-specific configuration dictionary.
        soothe_config: Soothe configuration instance.
        emit_event_callback: Optional callback invoked as `(name, data)`.
            If `None`, events are logged but not emitted.
        **extra_context: Additional context fields to attach to the context.

    Returns:
        Configured `PluginContext` instance.

    Example:
        context = create_plugin_context(
            plugin_name="datetime",
            config={},
            soothe_config=config,
        )
    """
    # Create plugin-specific logger
    plugin_logger = logging.getLogger(f"soothe.plugins.{plugin_name}")

    # Create event emission wrapper
    def emit_event_wrapper(name: str, data: dict[str, Any]) -> None:
        """Forward `name`/`data` to `emit_event_callback`, or log at debug if absent."""
        if emit_event_callback:
            emit_event_callback(name, data)
        else:
            logger.debug("Plugin event: %s -> %s", name, data)

    # Create context
    context = PluginContext(
        config=config,
        soothe_config=soothe_config,
        logger=plugin_logger,
        emit_event=emit_event_wrapper,
    )

    # Attach extra context fields
    for key, value in extra_context.items():
        setattr(context, key, value)

    return context
