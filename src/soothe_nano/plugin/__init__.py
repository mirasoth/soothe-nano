"""Soothe plugin system: decorator API, discovery, registry, loading, and lifecycle.

Third-party plugin authors build plugins with the decorator-based API here
(``@plugin`` / ``@tool`` / ``@tool_group`` / ``@subagent``); plugins are
discovered from entry points, config, or the filesystem and loaded with
dependency resolution.
"""

from soothe_nano.core.registry import register_event
from soothe_nano.plugin.context import PluginContext, SootheConfigProtocol, create_plugin_context
from soothe_nano.plugin.decorators import plugin, subagent, tool, tool_group
from soothe_nano.plugin.depends import library
from soothe_nano.plugin.discovery import (
    discover_all_plugins,
    discover_config_declared,
    discover_entry_points,
    discover_filesystem,
)
from soothe_nano.plugin.emit import emit_progress, set_stream_writer
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
    ValidationError,
)
from soothe_nano.plugin.health import PluginHealth
from soothe_nano.plugin.lifecycle import PluginLifecycleManager
from soothe_nano.plugin.loader import PluginLoader
from soothe_nano.plugin.manifest import PluginManifest
from soothe_nano.plugin.registry import PluginRegistry, RegistryEntry

__all__ = [
    # Decorator API (plugin authors)
    "plugin",
    "tool",
    "tool_group",
    "subagent",
    "library",
    "register_event",
    "emit_progress",
    "set_stream_writer",
    # Types
    "PluginManifest",
    "PluginContext",
    "SootheConfigProtocol",
    "PluginHealth",
    # Exceptions
    "DependencyError",
    "DiscoveryError",
    "InitializationError",
    "PluginError",
    "ValidationError",
    # Events
    "PluginFailedEvent",
    "PluginHealthCheckedEvent",
    "PluginLoadedEvent",
    "PluginUnloadedEvent",
    # Core classes
    "PluginLifecycleManager",
    "PluginLoader",
    "PluginRegistry",
    "RegistryEntry",
    # Context
    "create_plugin_context",
    # Discovery
    "discover_all_plugins",
    "discover_config_declared",
    "discover_entry_points",
    "discover_filesystem",
]
