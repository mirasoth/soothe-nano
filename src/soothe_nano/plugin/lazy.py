"""Lazy-loading plugin proxy that defers instantiation until first access."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class LazyPlugin:
    """Proxy that defers plugin instantiation until first attribute access.

    Improves startup performance by skipping plugins that may never be used
    during a session. The wrapped `loader` callable is invoked once, on the
    first attribute access, and the resulting instance is cached.

    Example:
        proxy = LazyPlugin("my-plugin", lambda: MyPlugin())
        # MyPlugin is not constructed yet
        proxy.some_method()
        # MyPlugin is now constructed and cached
    """

    def __init__(self, name: str, loader: Callable[[], Any]) -> None:
        """Initialize with a `name` (for logging) and a `loader` callable."""
        self._name = name
        self._loader = loader
        self._instance: Any | None = None

    def __getattr__(self, attr: str) -> Any:
        """Load the plugin on first access, then delegate attribute lookup to it."""
        if self._instance is None:
            logger.info("Lazy-loading plugin '%s'", self._name)
            self._instance = self._loader()
        return getattr(self._instance, attr)

    def is_loaded(self) -> bool:
        """Return `True` if the underlying instance has been loaded."""
        return self._instance is not None

    def get_instance(self) -> Any | None:
        """Return the underlying instance without triggering a load, or `None`."""
        return self._instance


__all__ = ["LazyPlugin"]
