"""Exception types for the Soothe SDK.

These are Python exception classes (inheriting from ``Exception``) used for
control flow throughout the SDK. Exception hierarchies are inherently
Python-specific (they integrate with ``try``/``except`` and traceback
machinery) and have no Rust equivalent; the class definitions stay in Python.
"""


class PluginError(Exception):
    """Base error for plugin system."""

    pass


class DiscoveryError(PluginError):
    """Error during plugin discovery."""

    pass


class ValidationError(PluginError):
    """Error during manifest validation."""

    pass


class DependencyError(PluginError):
    """Error during dependency resolution."""

    pass


class InitializationError(PluginError):
    """Error during plugin initialization."""

    pass


class ToolCreationError(PluginError):
    """Error during tool creation."""

    pass


class SubagentCreationError(PluginError):
    """Error during subagent instance creation."""

    pass


class ConfigurationError(Exception):
    """Error in configuration validation or backend initialization."""

    pass
