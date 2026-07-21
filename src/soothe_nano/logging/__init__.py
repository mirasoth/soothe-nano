"""Soothe-nano logging — thread context and setup (no daemon history store).

``ThreadLogger`` is host-owned (``soothe.logging.thread_logger``); nano does not
define it (IG-678 PR-6).
"""

from soothe_nano.logging.context import get_thread_id, set_thread_id
from soothe_nano.logging.setup import ThreadFormatter, setup_logging

__all__ = [
    "ThreadFormatter",
    "get_thread_id",
    "set_thread_id",
    "setup_logging",
]
