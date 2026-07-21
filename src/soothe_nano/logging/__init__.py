"""Soothe-nano logging — thread context and setup.

``ThreadLogger`` is host-owned (defined by the host application); nano does not
define it.
"""

from soothe_nano.logging.context import get_thread_id, set_thread_id
from soothe_nano.logging.setup import ThreadFormatter, setup_logging

__all__ = [
    "ThreadFormatter",
    "get_thread_id",
    "set_thread_id",
    "setup_logging",
]
