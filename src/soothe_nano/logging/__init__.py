"""Soothe-nano logging — thread context and setup.

``ThreadLogger`` is host-owned (defined by the host application); nano does not
define it. Hosts attach their logger trees via ``setup_logging(...,
extra_logger_names=...)``.
"""

from soothe_nano.logging.context import get_thread_id, set_thread_id
from soothe_nano.logging.setup import (
    COMMUNITY_LOGGER_NAME,
    PACKAGE_LOGGER_NAMES,
    ThreadFormatter,
    resolve_package_logger_names,
    setup_logging,
)

__all__ = [
    "COMMUNITY_LOGGER_NAME",
    "PACKAGE_LOGGER_NAMES",
    "ThreadFormatter",
    "get_thread_id",
    "resolve_package_logger_names",
    "set_thread_id",
    "setup_logging",
]
