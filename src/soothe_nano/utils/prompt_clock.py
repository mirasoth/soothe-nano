"""Local wall-clock helpers for LLM prompts.

The 6 string formatters are Rust-backed (no Python fallback).
``now_local()`` stays Python-only — it returns a ``datetime`` object.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from soothe_nano._rust_compat import (
    format_friendly_local_date_rust,
    local_date_str_rust,
    local_time_str_rust,
    local_timestamp_iso_rust,
    local_timezone_label_rust,
    prompt_datetime_context_rust,
)


def _parse_tz(tz: str | timezone | None) -> str | None:
    """Normalize a tz argument into an IANA name (or None for local)."""
    if tz is None:
        return None
    if isinstance(tz, str):
        return tz or None
    return getattr(tz, "key", str(tz))


def now_local(tz: str | timezone | None = None) -> datetime:
    """Return current time in the system local timezone (or *tz* when given).

    Stays Python-only: Rust ``now_local`` returns an ISO string, but callers
    depend on receiving a ``datetime`` object.
    """
    tz_name = _parse_tz(tz)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz_name))
        except Exception:  # noqa: BLE001 — fall back to local on bad tz
            pass
    return datetime.now(UTC).astimezone()


def local_date_str(
    timestamp: float | None = None,
    tz: str | timezone | None = None,
) -> str:
    """Current local calendar date (YYYY-MM-DD)."""
    return local_date_str_rust(timestamp, _parse_tz(tz))


def local_time_str(
    timestamp: float | None = None,
    tz: str | timezone | None = None,
) -> str:
    """Current local wall time (HH:MM:SS)."""
    return local_time_str_rust(timestamp, _parse_tz(tz))


def local_timestamp_iso(
    timestamp: float | None = None,
    tz: str | timezone | None = None,
) -> str:
    """Current local time as ISO-8601 (includes offset)."""
    return local_timestamp_iso_rust(timestamp, _parse_tz(tz))


def local_timezone_label(tz: str | timezone | None = None) -> str:
    """IANA timezone name or fallback label for the system local zone."""
    return local_timezone_label_rust(_parse_tz(tz))


def prompt_datetime_context(
    tz: str | timezone | None = None,
) -> dict[str, str]:
    """Standard date/time fields for prompt templates."""
    return prompt_datetime_context_rust(_parse_tz(tz))


def format_friendly_local_date(
    timestamp: float | None = None,
    tz: str | timezone | None = None,
) -> str:
    """Return a user-facing local date (e.g. ``October 14, 2026``)."""
    return format_friendly_local_date_rust(timestamp, _parse_tz(tz))


__all__: tuple[str, ...] = (
    "format_friendly_local_date",
    "local_date_str",
    "local_time_str",
    "local_timestamp_iso",
    "local_timezone_label",
    "now_local",
    "prompt_datetime_context",
)
