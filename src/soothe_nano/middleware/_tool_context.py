"""Tool-trigger and tool-context registries for system-prompt injection.

Built-in tools declare which system-message sections they require via
``BUILTIN_TOOL_TRIGGERS``; plugins contribute their own triggers and
system-context fragments through the registries below.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig
    from soothe_nano.plugin.registry import PluginRegistry

logger = logging.getLogger(__name__)

# Built-in tool triggers (hardcoded for core tools)
BUILTIN_TOOL_TRIGGERS: dict[str, list[str]] = {
    # File operation tools
    "read_file": ["WORKSPACE"],
    "write_file": ["WORKSPACE"],
    "glob": ["WORKSPACE"],
    "grep": ["WORKSPACE"],
    "edit_file": ["WORKSPACE"],
    "delete": ["WORKSPACE"],
    "insert_lines": ["WORKSPACE"],
    "apply_diff": ["WORKSPACE"],
    "file_info": ["WORKSPACE"],
    # Execution tools
    "run_command": ["WORKSPACE"],
    "run_python": ["WORKSPACE"],
    "run_background": ["WORKSPACE"],
    "kill_process": [],
    # Web tools
    "search_web": [],  # No workspace dependency
    "crawl_web": [],
    "requests_get": [],
    "requests_post": [],
    "requests_patch": [],
    "requests_put": [],
    "requests_delete": [],
    # Data tools
    "inspect_data": ["WORKSPACE"],
    "summarize_data": ["WORKSPACE"],
    "check_data_quality": ["WORKSPACE"],
    "extract_text": ["WORKSPACE"],
    "get_data_info": ["WORKSPACE"],
    "ask_about_file": ["WORKSPACE"],
    # Subagents (task tool targets — core: plan, deep_research, academic_research; plugins add more)
    "deep_research": ["DEEP_RESEARCH_RULES", "context"],
    "academic_research": ["ACADEMIC_RESEARCH_RULES", "context"],
    # Datetime
    "datetime": [],
}


class ToolTriggerRegistry:
    """Resolve tool names to the system-message sections they require.

    Built-in tools carry hardcoded trigger mappings; plugin tools declare
    their own via plugin metadata. The registry is read-only and stateless
    aside from the optional plugin registry reference.

    Example:
        reg = ToolTriggerRegistry(plugin_registry)
        sections = reg.get_triggered_sections(["read_file", "glob"])
    """

    def __init__(self, plugin_registry: PluginRegistry | None = None) -> None:
        self._plugin_registry = plugin_registry

    def get_triggered_sections(self, tool_names: list[str]) -> set[str]:
        """Return the section names triggered by ``tool_names``.

        Args:
            tool_names: Recently invoked tool names.

        Returns:
            Section names to inject into the system prompt.
        """
        sections = set()

        for tool_name in tool_names:
            # Check built-in triggers first
            if tool_name in BUILTIN_TOOL_TRIGGERS:
                sections.update(BUILTIN_TOOL_TRIGGERS[tool_name])
            elif self._plugin_registry:
                # Check plugin metadata for custom tools
                tool_metadata = self._plugin_registry.get_tool_metadata(tool_name)
                if tool_metadata and "triggers" in tool_metadata:
                    sections.update(tool_metadata["triggers"])

        return sections


class ToolContextRegistry:
    """Resolve a tool or subagent name to an XML system-context fragment.

    Resolution priority: config override > plugin metadata > ``None``.
    Results are cached per tool name for the lifetime of the instance.

    Args:
        config: SootheConfig carrying subagent and plugin config blocks.
        plugin_registry: Optional plugin registry for tool/subagent metadata.

    Example:
        reg = ToolContextRegistry(config, plugin_registry)
        fragment = reg.get_system_context("deep_research")
    """

    def __init__(self, config: SootheConfig, plugin_registry: PluginRegistry | None = None) -> None:
        self._config = config
        self._plugin_registry = plugin_registry
        self._cache: dict[str, str | None] = {}

    def get_system_context(self, tool_name: str) -> str | None:
        """Return the cached XML context fragment for ``tool_name``, if any.

        Args:
            tool_name: Tool or subagent name.

        Returns:
            System context string, or ``None`` when undefined.
        """
        if tool_name in self._cache:
            return self._cache[tool_name]

        # 1. Check config override (highest priority)
        config_fragment = self._get_config_override(tool_name)
        if config_fragment:
            logger.debug("Using config override for tool '%s' system_context", tool_name)
            self._cache[tool_name] = config_fragment
            return config_fragment

        # 2. Check plugin metadata
        plugin_fragment = self._get_plugin_metadata(tool_name)
        if plugin_fragment:
            logger.debug("Using plugin metadata for tool '%s' system_context", tool_name)

        self._cache[tool_name] = plugin_fragment
        return plugin_fragment

    def _get_config_override(self, tool_name: str) -> str | None:
        """Return a config-defined system context for ``tool_name``, if any.

        Looks up ``subagents[name].config.system_context`` and matching
        plugin config blocks.

        Args:
            tool_name: Tool or subagent name.

        Returns:
            System context string from config, or ``None``.
        """
        # Check subagents config
        if tool_name in self._config.subagents:
            subagent_config = self._config.subagents[tool_name]
            if subagent_config.config and "system_context" in subagent_config.config:
                return subagent_config.config["system_context"]

        # Check plugins config
        for plugin_cfg in self._config.plugins:
            if plugin_cfg.name == tool_name:
                if plugin_cfg.config and "system_context" in plugin_cfg.config:
                    return plugin_cfg.config["system_context"]

        return None

    def _get_plugin_metadata(self, tool_name: str) -> str | None:
        """Return a plugin-defined system context for ``tool_name``, if any.

        Args:
            tool_name: Tool or subagent name.

        Returns:
            System context string from plugin metadata, or ``None``.
        """
        if not self._plugin_registry:
            return None

        # Check tool metadata
        tool_metadata = self._plugin_registry.get_tool_metadata(tool_name)
        if tool_metadata and "system_context" in tool_metadata:
            return tool_metadata["system_context"]

        # Check subagent metadata
        subagent_metadata = self._plugin_registry.get_subagent_metadata(tool_name)
        if subagent_metadata and "system_context" in subagent_metadata:
            return subagent_metadata["system_context"]

        return None
