"""Thread id helpers for nano backends."""

from __future__ import annotations

from soothe_nano._rust_compat import generate_thread_id

__all__ = ["generate_thread_id"]
