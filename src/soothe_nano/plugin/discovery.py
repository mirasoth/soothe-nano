"""Plugin discovery from entry points, config, and the filesystem."""

import importlib
import importlib.metadata
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from soothe_nano.config import SOOTHE_HOME

if TYPE_CHECKING:
    from soothe_nano.config.settings import SootheConfig

logger = logging.getLogger(__name__)

PluginDiscoverySource = Literal["built-in", "entry_point", "config", "filesystem"]


def _try_extract_plugin_name(module_path: str) -> str | None:
    """Attempt to extract a plugin's name from its manifest by importing its module.

    Used so deduplication works by name rather than module path. Returns
    `None` when the manifest cannot be loaded.
    """
    try:
        if ":" in module_path:
            module_name, class_name = module_path.split(":", 1)
        else:
            class_name = None
            module_name = module_path

        mod = importlib.import_module(module_name)
        if class_name and hasattr(mod, class_name):
            cls = getattr(mod, class_name)
            if hasattr(cls, "_plugin_manifest"):
                return cls._plugin_manifest.name
        # Fallback: look for any class with _plugin_manifest
        if class_name is None:
            for attr_name in dir(mod):
                if attr_name.endswith("Plugin") and not attr_name.startswith("_"):
                    cls = getattr(mod, attr_name)
                    if hasattr(cls, "_plugin_manifest"):
                        return cls._plugin_manifest.name
    except Exception as e:
        logger.debug("Could not extract plugin name from %s: %s", module_path, e)
    return None


def discover_entry_points() -> list[str]:
    """Discover plugins declared via the `soothe.plugins` entry point group.

    Returns:
        List of `module_path:ClassName` strings, one per discovered entry point.
    """
    plugins = []
    try:
        entry_points = importlib.metadata.entry_points(group="soothe.plugins")
        for ep in entry_points:
            module_path = ep.value
            plugins.append(module_path)
            logger.info("Discovered plugin '%s' from entry point: %s", ep.name, module_path)
    except Exception as e:
        logger.debug("No soothe.plugins entry points found: %s", e)

    return plugins


def discover_config_declared(config: "SootheConfig") -> list[tuple[str, dict]]:
    """Discover enabled plugins declared in Soothe configuration.

    Args:
        config: Resolved Soothe configuration.

    Returns:
        List of `(module_path, config_dict)` tuples for each enabled plugin.
    """
    plugins = []

    if not hasattr(config, "plugins"):
        logger.debug("No plugins field in config")
        return plugins

    for plugin_config in config.plugins:
        if not plugin_config.enabled:
            logger.debug("Plugin '%s' is disabled", plugin_config.name)
            continue

        if not plugin_config.module:
            logger.warning("Plugin '%s' has no module path", plugin_config.name)
            continue

        plugins.append((plugin_config.module, plugin_config.config))
        logger.info(
            "Discovered plugin '%s' from config: %s", plugin_config.name, plugin_config.module
        )

    return plugins


def discover_filesystem(base_dir: Path | None = None) -> list[str]:
    """Discover plugins by scanning a directory for `plugin.py` or `__init__.py`.

    The directory is added to `sys.path` so discovered plugins can be imported.
    Each subdirectory whose name does not start with `.` is treated as a
    candidate plugin.

    Args:
        base_dir: Base directory to scan. Defaults to `~/.soothe/plugins/`.

    Returns:
        List of importable module paths (e.g., `["my_plugin.plugin", "research"]`).
    """
    if base_dir is None:
        base_dir = SOOTHE_HOME / "plugins"

    base = base_dir.expanduser()

    if not base.is_dir():
        logger.debug("Plugin directory does not exist: %s", base)
        return []

    # Add plugin directory to sys.path so plugins can be imported
    plugin_dir_str = str(base)
    if plugin_dir_str not in sys.path:
        sys.path.insert(0, plugin_dir_str)
        logger.debug("Added plugin directory to sys.path: %s", plugin_dir_str)

    plugins = []

    for plugin_dir in base.iterdir():
        if not plugin_dir.is_dir():
            continue

        # Skip hidden directories
        if plugin_dir.name.startswith("."):
            continue

        # Look for plugin.py or __init__.py
        plugin_file = plugin_dir / "plugin.py"
        init_file = plugin_dir / "__init__.py"

        if plugin_file.exists():
            # plugin.py -> module_name.plugin
            module_path = f"{plugin_dir.name}.plugin"
            plugins.append(module_path)
            logger.info("Discovered plugin from filesystem: %s", module_path)
        elif init_file.exists():
            # __init__.py -> module_name
            module_path = plugin_dir.name
            plugins.append(module_path)
            logger.info("Discovered plugin from filesystem: %s", module_path)

    return plugins


def discover_all_plugins(
    config: "SootheConfig",
) -> dict[str, tuple[str, dict, PluginDiscoverySource]]:
    """Run all discovery mechanisms and return a map of plugin identifiers to sources.

    Built-in plugins are listed first; duplicates from lower-priority sources
    overwrite higher-priority ones only at registry registration time.

    Args:
        config: Soothe configuration.

    Returns:
        Dict mapping a unique identifier (plugin name when discoverable
        from the manifest, otherwise the module path) to a
        `(module_path, config_dict, source)` tuple.
    """
    discovered: dict[str, tuple[str, dict, PluginDiscoverySource]] = {}

    # Built-in plugins must use ``module:ClassName`` — PluginLoader rejects bare paths.
    # Do not list removed/never-shipped toolkits (goals, audio, video).
    _builtin_plugins: list[tuple[str, str]] = [
        ("planner", "soothe_nano.subagents.plan:PlanPlugin"),
        ("deep_research", "soothe_nano.subagents.deep_research:DeepResearchPlugin"),
        (
            "academic_research",
            "soothe_nano.subagents.academic_research:AcademicResearchPlugin",
        ),
        ("browser_use", "soothe_nano.subagents.browser_use:BrowserUsePlugin"),
        ("execution", "soothe_nano.toolkits.execution:ExecutionPlugin"),
        ("file_ops", "soothe_nano.toolkits.file_ops:FileOpsPlugin"),
        ("data", "soothe_nano.toolkits.data:DataPlugin"),
        ("datetime", "soothe_nano.toolkits.datetime:DatetimePlugin"),
        ("wizsearch", "soothe_nano.toolkits.wizsearch:WizsearchPlugin"),
        ("http_requests", "soothe_nano.toolkits.http_requests:HttpRequestsPlugin"),
        ("image", "soothe_nano.toolkits.image:ImagePlugin"),
    ]
    for plugin_name, module_path in _builtin_plugins:
        discovered[plugin_name] = (module_path, {}, "built-in")
        logger.debug("Discovered built-in plugin: %s", plugin_name)

    # Entry points (no config available)
    for module_path in discover_entry_points():
        name = _try_extract_plugin_name(module_path) or module_path
        discovered[name] = (module_path, {}, "entry_point")

    # Config-declared (has config)
    for module_path, plugin_config in discover_config_declared(config):
        discovered[module_path] = (module_path, plugin_config, "config")

    # Filesystem (no config available)
    for module_path in discover_filesystem():
        name = _try_extract_plugin_name(f"{module_path}:Plugin") or module_path
        discovered[name] = (module_path, {}, "filesystem")

    logger.info("Discovered %s total plugins", len(discovered))
    return discovered
