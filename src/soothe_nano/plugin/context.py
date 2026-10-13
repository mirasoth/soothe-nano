"""Plugin context, config protocol, and context factory.

``PluginContext`` provides plugins with access to Soothe configuration,
logging, and event emission. ``SootheConfigProtocol`` decouples this module
from the concrete ``SootheConfig`` implementation, and ``create_plugin_context``
wires a context to Soothe's logging and events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from soothe_nano.config.settings import SootheConfig

logger = logging.getLogger(__name__)


class SootheConfigProtocol(Protocol):
    """Protocol defining the interface SootheConfig must implement.

    This protocol enables plugin code to reference SootheConfig functionality
    without creating a circular dependency. The main Soothe package's
    SootheConfig class implements this protocol.

    Methods:
        resolve_model: Resolve a model role to a provider:model string.
        get_plugin_config: Get plugin-specific configuration dictionary.
    """

    def resolve_model(self, role: str) -> str:
        """Resolve a model role to a provider:model string.

        Args:
            role: Model role (e.g., "default", "planner", "fast").

        Returns:
            Model identifier string (e.g., "openai:gpt-4o-mini").
        """
        ...

    def get_plugin_config(self, name: str) -> dict[str, Any]:
        """Get plugin-specific configuration.

        Args:
            name: Plugin name.

        Returns:
            Configuration dictionary for the plugin.
        """
        ...


class PluginContext:
    """Context provided to plugin lifecycle hooks, with runtime services.

    This class provides plugins with access to Soothe configuration,
    logging, event emission, and runtime service injection.

    Attributes:
        config: Plugin-specific configuration dictionary.
        soothe_config: Soothe configuration (via protocol).
        logger: Python logger instance for this plugin.
        services: Runtime services dict (populated by the host during plugin loading).
            Keys include: "policy", "persistence", "emit_progress", "vector_store".
    """

    def __init__(
        self,
        config: dict[str, Any],
        soothe_config: SootheConfigProtocol,
        logger: logging.Logger,
        emit_event: Callable[[str, dict[str, Any]], None],
        services: dict[str, Any] | None = None,
    ):
        """Initialize plugin context.

        Args:
            config: Plugin-specific configuration.
            soothe_config: Soothe configuration object.
            logger: Logger instance for this plugin.
            emit_event: Callback to emit events.
            services: Runtime services dict (optional, defaults to empty dict).
        """
        self.config = config
        self.soothe_config = soothe_config
        self.logger = logger
        self._emit_event = emit_event
        self.services: dict[str, Any] = services or {}

    def emit_event(self, name: str, data: dict[str, Any]) -> None:
        """Emit a plugin event.

        Args:
            name: Event name (e.g., "plugin.loaded").
            data: Event data dictionary.
        """
        self._emit_event(name, data)


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
