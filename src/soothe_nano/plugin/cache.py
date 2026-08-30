"""In-memory cache of loaded plugin instances."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_plugin_cache: dict[str, Any] = {}


def get_cached_plugin(name: str) -> Any | None:
    """Return the cached plugin instance for `name`, or `None` if not cached."""
    return _plugin_cache.get(name)


def cache_plugin(name: str, instance: Any) -> None:
    """Store `instance` in the cache under `name`."""
    _plugin_cache[name] = instance
    logger.debug("Cached plugin '%s'", name)


def clear_plugin_cache() -> None:
    """Remove all cached plugin instances."""
    global _plugin_cache
    _plugin_cache = {}
    logger.debug("Cleared plugin cache")
