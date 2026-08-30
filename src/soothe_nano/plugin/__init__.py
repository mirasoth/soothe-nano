"""Soothe plugin system: discovery, registry, loading, and lifecycle.

Built on the decorator-based API in `soothe_sdk`. Third-party plugins
register tools and subagents that are discovered from entry points,
config, or the filesystem and loaded with dependency resolution.
"""

from soothe_sdk.plugin import PluginManifest

from soothe_nano.plugin.context import create_plugin_context
from soothe_nano.plugin.discovery import (
    discover_all_plugins,
    discover_config_declared,
    discover_entry_points,
    discover_filesystem,
)
from soothe_nano.plugin.events import (
    PluginFailedEvent,
    PluginHealthCheckedEvent,
    PluginLoadedEvent,
    PluginUnloadedEvent,
)
from soothe_nano.plugin.exceptions import (
    DependencyError,
    DiscoveryError,
    InitializationError,
    PluginError,
    SubagentCreationError,
    ToolCreationError,
    ValidationError,
)
from soothe_nano.plugin.lifecycle import PluginLifecycleManager
from soothe_nano.plugin.loader import PluginLoader
from soothe_nano.plugin.registry import PluginRegistry, RegistryEntry

__all__ = [
    # Exceptions
    "DependencyError",
    "DiscoveryError",
    "InitializationError",
    "PluginError",
    # Events
    "PluginFailedEvent",
    "PluginHealthCheckedEvent",
    # Core classes
    "PluginLifecycleManager",
    "PluginLoadedEvent",
    "PluginLoader",
    "PluginManifest",
    "PluginRegistry",
    "PluginUnloadedEvent",
    "RegistryEntry",
    "SubagentCreationError",
    "ToolCreationError",
    "ValidationError",
    # Context
    "create_plugin_context",
    # Discovery
    "discover_all_plugins",
    "discover_config_declared",
    "discover_entry_points",
    "discover_filesystem",
]
