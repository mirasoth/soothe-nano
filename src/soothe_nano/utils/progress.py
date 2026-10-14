"""Shared progress event emission for Soothe subagents."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import logging

# Intake-only / outer bridges when LangGraph ``get_stream_writer`` is unavailable
# (e.g. long single-node browser_use runs). Sync callback; may schedule onto a loop.
_wire_bridge: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = (
    contextvars.ContextVar("subagent_wire_bridge", default=None)
)

# Per-event-loop fallback for cases where ContextVar propagation is lost across
# tasks/callback boundaries while still running on the same loop.
_loop_wire_bridge: dict[int, Callable[[dict[str, Any]], None]] = {}
_loop_wire_bridge_lock = threading.Lock()


def set_wire_bridge(callback: Callable[[dict[str, Any]], None] | None) -> contextvars.Token:
    """Install a sync sink for wire/progress events (intake-only stream bridge)."""
    token = _wire_bridge.set(callback)
    if callback is not None:
        try:
            import asyncio

            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            with _loop_wire_bridge_lock:
                _loop_wire_bridge[id(loop)] = callback
    return token


def reset_wire_bridge(token: contextvars.Token) -> None:
    """Restore the previous wire bridge callback."""
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    previous_callback = _wire_bridge.get()
    loop_id = id(loop) if loop is not None else None
    if loop_id is not None and previous_callback is not None:
        with _loop_wire_bridge_lock:
            if _loop_wire_bridge.get(loop_id) is previous_callback:
                _loop_wire_bridge.pop(loop_id, None)

    _wire_bridge.reset(token)

    # Nested set/reset support: re-install the now-current callback if present.
    if loop_id is not None:
        current_callback = _wire_bridge.get()
        with _loop_wire_bridge_lock:
            if current_callback is None:
                _loop_wire_bridge.pop(loop_id, None)
            else:
                _loop_wire_bridge[loop_id] = current_callback


def get_wire_bridge() -> Callable[[dict[str, Any]], None] | None:
    """Return the active wire bridge sink, if any."""
    callback = _wire_bridge.get()
    if callback is not None:
        return callback

    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    with _loop_wire_bridge_lock:
        return _loop_wire_bridge.get(id(loop))


def _format_event_compact(event: dict[str, Any]) -> str:
    """Format event dict into a compact, readable string (delegates to Rust).

    Extracts key fields and formats them concisely:
    - Shortens event type (removes 'soothe.' prefix)
    - Shows important fields based on event type
    - Truncates long values

    Args:
        event: Event dictionary with at minimum a 'type' key.

    Returns:
        Compact string representation.
    """
    from soothe_nano._rust_compat import format_event_compact_rust

    return format_event_compact_rust(event)


def emit_progress(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit a progress event via wire bridge or LangGraph stream writer.

    Always logs to file first for backend audit trail, then attempts stream emission.
    This is the canonical way for Soothe subagent graph nodes to surface
    `soothe.*` custom events to the TUI / headless renderer.

    Automatically injects step_id from context if available and not already present.

    When an intake-only wire bridge is installed, events go only through that sink
    (avoiding duplicate astream `custom` delivery).

    Args:
        event: Event dict with at minimum a `type` key.
        logger: Caller's logger instance for logging.
    """
    # Always log to file first for audit trail (compact format)
    logger.debug(_format_event_compact(event))

    bridge = get_wire_bridge()
    if bridge is not None:
        try:
            bridge(event)
        except Exception:
            logger.debug("Wire bridge sink failed", exc_info=True)
        return

    # LangGraph custom stream (parented task / when no outer bridge).
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer:
            writer(event)
    except (ImportError, RuntimeError, KeyError):
        pass
