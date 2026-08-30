"""Plugin lifecycle events in the `soothe.internal.plugin.*` namespace.

Events self-register at module load time via `register_event()`.
"""

from typing import Literal

from soothe_sdk.core.events import SootheEvent


class PluginLoadedEvent(SootheEvent):
    """Signals that a plugin finished initialization and is ready to serve tools/subagents.

    Attributes:
        type: Event type identifier (`soothe.internal.plugin.loaded`).
        name: Plugin name.
        version: Plugin version.
        source: Discovery source (`built-in`, `entry_point`, `config`, `filesystem`).
    """

    type: Literal["soothe.internal.plugin.loaded"] = "soothe.internal.plugin.loaded"
    name: str
    version: str
    source: str


class PluginFailedEvent(SootheEvent):
    """Signals that a plugin failed during a loading phase and is unavailable.

    Attributes:
        type: Event type identifier (`soothe.internal.plugin.failed`).
        name: Plugin name (empty if failure occurred before manifest parsing).
        error: Error message describing the failure.
        phase: Phase where the failure occurred (`discovery`, `validation`,
            `dependency`, or `initialization`).
    """

    type: Literal["soothe.internal.plugin.failed"] = "soothe.internal.plugin.failed"
    name: str = ""
    error: str
    phase: Literal["discovery", "validation", "dependency", "initialization"]


class PluginHealthCheckedEvent(SootheEvent):
    """Signals completion of a plugin's `health_check()` hook.

    Attributes:
        type: Event type identifier (`soothe.internal.plugin.health_checked`).
        name: Plugin name.
        status: Health status (`healthy`, `degraded`, or `unhealthy`).
        details: Optional details about the health check result.
    """

    type: Literal["soothe.internal.plugin.health_checked"] = "soothe.internal.plugin.health_checked"
    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    details: str = ""


class PluginUnloadedEvent(SootheEvent):
    """Signals that a plugin's `on_unload()` hook has been called and it is no longer available.

    Attributes:
        type: Event type identifier (`soothe.internal.plugin.unloaded`).
        name: Plugin name.
    """

    type: Literal["soothe.internal.plugin.unloaded"] = "soothe.internal.plugin.unloaded"
    name: str


# Register all plugin events with the global registry
# This happens at module load time
from soothe_sdk.core.verbosity import VerbosityTier  # noqa: E402

from soothe_nano.events.catalog import register_event  # noqa: E402

register_event(
    PluginLoadedEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Plugin {name} v{version} loaded from {source}",
)
register_event(
    PluginFailedEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Plugin {name} failed during {phase}: {error}",
)
register_event(
    PluginHealthCheckedEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Plugin {name} health: {status}",
)
register_event(
    PluginUnloadedEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Plugin {name} unloaded",
)

__all__ = [
    "PluginFailedEvent",
    "PluginHealthCheckedEvent",
    "PluginLoadedEvent",
    "PluginUnloadedEvent",
]
