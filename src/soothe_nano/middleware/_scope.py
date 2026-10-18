"""Shared request-scope identity for middleware with pending per-session state."""

from __future__ import annotations

from typing import Any


def request_scope_id(request: Any) -> str:
    """Build a ``thread_id:checkpoint_ns`` scope id for a tool/model request.

    Middlewares that hold pending queues on the shared middleware instance
    (coalescers) key them by this id so concurrent graph threads never
    share detection windows or staging state.
    """
    runtime = getattr(request, "runtime", None)
    cfg = getattr(runtime, "config", None)
    configurable = cfg.get("configurable", {}) if isinstance(cfg, dict) else {}
    if not isinstance(configurable, dict):
        configurable = {}
    thread_id = str(configurable.get("thread_id") or "")
    checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
    return f"{thread_id}:{checkpoint_ns}"


__all__ = ["request_scope_id"]
