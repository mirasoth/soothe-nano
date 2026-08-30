"""Process-wide singleton plugin registry initialized during agent creation."""

import logging
from typing import TYPE_CHECKING

from soothe_nano.plugin.cache import clear_plugin_cache
from soothe_nano.plugin.lifecycle import PluginLifecycleManager
from soothe_nano.plugin.registry import PluginRegistry

if TYPE_CHECKING:
    from soothe_nano.config.settings import SootheConfig

logger = logging.getLogger(__name__)

# Global plugin registry singleton
_global_registry: PluginRegistry | None = None
_global_lifecycle_manager: PluginLifecycleManager | None = None


def get_plugin_registry() -> PluginRegistry:
    """Return the global plugin registry.

    Raises:
        RuntimeError: If `load_plugins()` has not been called yet.
    """
    if _global_registry is None:
        raise RuntimeError(
            "Plugin registry not initialized. Call load_plugins(config) during agent creation first."
        )
    return _global_registry


async def load_plugins(config: "SootheConfig") -> PluginRegistry:
    """Discover and load all plugins, initializing the global registry.

    Must be called once during agent creation, before tool and subagent
    resolution. Subsequent calls return the existing registry without
    reloading.

    Args:
        config: Soothe configuration.

    Returns:
        Initialized `PluginRegistry` with all loaded plugins.
    """
    global _global_registry, _global_lifecycle_manager

    if _global_registry is not None:
        logger.warning("Plugins already loaded, returning existing registry")
        return _global_registry

    logger.info("Loading plugins...")

    # Create registry and lifecycle manager
    _global_registry = PluginRegistry()
    _global_lifecycle_manager = PluginLifecycleManager(_global_registry)

    # Load all plugins
    await _global_lifecycle_manager.load_all(config)

    logger.info(
        "Plugin loading complete: %d plugins, %d tools, %d subagents",
        len(_global_registry.list_all()),
        len(_global_registry.get_all_tools()),
        len(_global_registry.get_all_subagents()),
    )

    return _global_registry


async def shutdown_plugins() -> None:
    """Call `on_unload()` on all loaded plugins and reset the global registry."""
    global _global_registry, _global_lifecycle_manager

    if _global_lifecycle_manager:
        await _global_lifecycle_manager.shutdown_all()

    _global_registry = None
    _global_lifecycle_manager = None
    clear_plugin_cache()

    logger.info("Plugins shutdown complete")


def is_plugins_loaded() -> bool:
    """Return `True` if `load_plugins()` has completed successfully."""
    return _global_registry is not None
