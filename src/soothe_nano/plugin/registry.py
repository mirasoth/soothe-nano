"""Plugin registry with priority-based conflict resolution."""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from soothe_sdk.plugin import PluginManifest

logger = logging.getLogger(__name__)


def _resolve_plugin_tool_name(tool_like: Any) -> str | None:
    """Return the invoke name of a plugin tool method or LangChain tool, or `None`."""
    explicit = getattr(tool_like, "_tool_name", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    name = getattr(tool_like, "name", None)
    return name if isinstance(name, str) and name else None


def _rfc210_metadata_from_tool_like(tool_like: Any) -> dict[str, Any] | None:
    """Build `triggers` / `system_context` metadata from a `@tool` or wrapped `BaseTool`.

    Metadata may live directly on the callable or on a wrapped `func` /
    `coroutine` attribute. Returns `None` when no metadata is present.
    """

    def _extract(target: Any) -> dict[str, Any] | None:
        triggers = getattr(target, "_tool_triggers", None)
        system_context = getattr(target, "_tool_system_context", None)
        meta: dict[str, Any] = {}
        if triggers:
            meta["triggers"] = list(triggers)
        if system_context:
            meta["system_context"] = system_context
        return meta if meta else None

    direct = _extract(tool_like)
    if direct is not None:
        return direct
    inner = getattr(tool_like, "func", None)
    if inner is None:
        inner = getattr(tool_like, "coroutine", None)
    if inner is not None and inner is not tool_like:
        return _extract(inner)
    return None


@dataclass
class RegistryEntry:
    """A registered plugin and the tools/subagents it exposes.

    Attributes:
        manifest: Plugin manifest with metadata.
        source: Discovery source (`built-in`, `entry_point`, `config`, `filesystem`).
        priority: Priority level; higher wins on name conflicts.
        plugin_instance: Loaded plugin instance (`None` until loaded).
        tools: LangChain `BaseTool` instances provided by this plugin.
        subagents: Subagent factory functions provided by this plugin.
    """

    manifest: PluginManifest
    source: Literal["built-in", "entry_point", "config", "filesystem"]
    priority: int
    plugin_instance: Any = None
    tools: list[Any] = field(default_factory=list)
    subagents: list[Any] = field(default_factory=list)


class PluginRegistry:
    """Priority-based registry of discovered plugins with conflict resolution.

    When two sources provide a plugin with the same name, the entry with the
    higher priority is kept. Priority ordering:
    `built-in` (100) > `entry_point` (50) > `config` (30) > `filesystem` (10).

    Example:
        registry = PluginRegistry()
        registry.register(manifest, source="entry_point")
        entry = registry.get("my-plugin")
        tools = registry.get_all_tools()
    """

    PRIORITY_BUILTIN = 100
    PRIORITY_ENTRY_POINT = 50
    PRIORITY_CONFIG = 30
    PRIORITY_FILESYSTEM = 10

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._plugins: dict[str, RegistryEntry] = {}

    def register(
        self,
        manifest: PluginManifest,
        source: Literal["built-in", "entry_point", "config", "filesystem"],
        priority: int | None = None,
    ) -> None:
        """Register a plugin manifest with its source and priority.

        On a name conflict the entry with higher priority wins; ties keep the
        existing entry.

        Args:
            manifest: Plugin manifest with metadata.
            source: Discovery source.
            priority: Optional priority override. If `None`, the default for
                `source` is used.
        """
        if priority is None:
            priority = {
                "built-in": self.PRIORITY_BUILTIN,
                "entry_point": self.PRIORITY_ENTRY_POINT,
                "config": self.PRIORITY_CONFIG,
                "filesystem": self.PRIORITY_FILESYSTEM,
            }[source]

        existing = self._plugins.get(manifest.name)
        if existing and existing.priority >= priority:
            logger.warning(
                "Ignoring duplicate plugin '%s' from %s (existing has priority %d >= %d)",
                manifest.name,
                source,
                existing.priority,
                priority,
            )
            return

        self._plugins[manifest.name] = RegistryEntry(
            manifest=manifest,
            source=source,
            priority=priority,
        )
        logger.info(
            "Registered plugin '%s' v%s from %s (priority=%d)",
            manifest.name,
            manifest.version,
            source,
            priority,
        )

    def get(self, name: str) -> RegistryEntry | None:
        """Return the registry entry for `name`, or `None` if not registered."""
        return self._plugins.get(name)

    def list_all(self) -> list[RegistryEntry]:
        """Return all registered entries."""
        return list(self._plugins.values())

    def get_all_tools(self) -> list[Any]:
        """Return every `BaseTool` instance from all loaded plugins."""
        tools = []
        for entry in self._plugins.values():
            if entry.tools:
                tools.extend(entry.tools)
        return tools

    def get_all_subagents(self) -> list[Any]:
        """Return every subagent factory function from all loaded plugins."""
        subagents = []
        for entry in self._plugins.values():
            if entry.subagents:
                subagents.extend(entry.subagents)
        return subagents

    def get_tools_for_group(self, group_name: str) -> list[Any]:
        """Return tools for a tool group.

        A group is matched first by plugin name, then by tools carrying a
        matching `_tool_group` attribute.

        Args:
            group_name: Tool group name (e.g., `execution`, `file_ops`).

        Returns:
            List of tools for the group, or an empty list if none match.
        """
        # Look for a plugin whose name matches the group name
        entry = self._plugins.get(group_name)
        if entry and entry.tools:
            return entry.tools

        # Search for tools with matching group metadata
        return [
            tool
            for entry in self._plugins.values()
            for tool in entry.tools
            if hasattr(tool, "_tool_group") and tool._tool_group == group_name
        ]

    def get_subagent_factory(self, name: str) -> Any | None:
        """Return a subagent factory by name, or `None` if not registered."""
        # Search all plugins for a subagent with this name
        for entry in self._plugins.values():
            for factory in entry.subagents:
                if hasattr(factory, "_subagent_name") and factory._subagent_name == name:
                    return factory

        return None

    def get_subagent_default_config(self, name: str) -> dict[str, Any]:
        """Return the default config dict for a plugin subagent, or `{}` if none."""
        factory = self.get_subagent_factory(name)
        if factory and hasattr(factory, "_subagent_default_config"):
            return factory._subagent_default_config
        return {}

    def list_subagent_names(self) -> list[str]:
        """Return the names of all registered plugin subagents."""
        return [
            factory._subagent_name
            for entry in self._plugins.values()
            for factory in entry.subagents
            if hasattr(factory, "_subagent_name")
        ]

    def get_tool_metadata(self, tool_name: str) -> dict[str, Any] | None:
        """Return trigger/context metadata for a plugin tool by invoke name.

        Resolves metadata from `@tool`-decorated callables and from LangChain
        `BaseTool` instances (metadata may live on the wrapped `func` /
        `coroutine`).

        Args:
            tool_name: Tool name as exposed to the model (e.g., `glob`).

        Returns:
            Dict with optional `triggers` and `system_context` keys, or `None`.
        """
        for entry in self._plugins.values():
            for tool in entry.tools:
                resolved = _resolve_plugin_tool_name(tool)
                if resolved == tool_name:
                    return _rfc210_metadata_from_tool_like(tool)
        return None

    def get_subagent_metadata(self, subagent_name: str) -> dict[str, Any] | None:
        """Return trigger/context metadata for a plugin subagent factory by name.

        Args:
            subagent_name: Subagent name (e.g., `claude`).

        Returns:
            Dict with optional `triggers` and `system_context` keys, or `None`.
        """
        factory = self.get_subagent_factory(subagent_name)
        if factory is None:
            return None
        meta: dict[str, Any] = {}
        triggers = getattr(factory, "_subagent_triggers", None)
        if triggers:
            meta["triggers"] = list(triggers)
        ctx = getattr(factory, "_subagent_system_context", None)
        if ctx:
            meta["system_context"] = ctx
        return meta if meta else None

    def clear(self) -> None:
        """Remove all registered plugins. Intended for tests and cleanup."""
        self._plugins.clear()
