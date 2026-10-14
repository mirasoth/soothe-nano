"""Compact logging formatter helpers (short level codes, abbreviated logger names)."""

import logging
import time

from soothe_nano._rust_compat import (
    abbreviate_logger_name_rust as _abbreviate_logger_name_rust,
)
from soothe_nano._rust_compat import (
    short_level_letter_rust as _short_level_letter_rust,
)


def short_level_letter(levelno: int) -> str:
    """Return one-letter code for a logging level number (delegates to Rust)."""
    return _short_level_letter_rust(levelno)


def abbreviate_logger_name(name: str) -> str:
    """Shorten a dotted logger path by abbreviating all but the last two segments.

    Each earlier segment becomes its first character (e.g. ``soothe`` → ``s``).
    The last two segments stay unchanged so package/module context stays readable.

    Args:
        name: Logger name, typically ``__name__`` with dots.

    Returns:
        Compact form, or ``name`` unchanged when fewer than three segments.
    """
    return _abbreviate_logger_name_rust(name)


class ShortLevelFormatter(logging.Formatter):
    """Formatter that supplies ``level_short`` and compact ``%(asctime)s`` timestamps.

    Timestamps use ``YYYYMMDDTHHMMSS.mmm`` (local time, same ``converter`` as the
    standard formatter). This preserves full calendar date, wall-clock time, and
    millisecond resolution while shortening the default
    ``YYYY-MM-DD HH:MM:SS,mmm`` form.

    If ``datefmt`` is set on the formatter, that format is used instead (via
    ``super()``).
    """

    def formatTime(  # noqa: N802 — matches ``logging.Formatter.formatTime``
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        """Format ``record.created`` as compact local time with milliseconds."""
        if datefmt:
            return super().formatTime(record, datefmt)
        ct = self.converter(record.created)
        stamp = time.strftime("%Y%m%dT%H%M%S", ct)
        # ``LogRecord.msecs`` is usually int but may be float on some versions/paths.
        ms = int(round(float(record.msecs))) % 1000
        return f"{stamp}.{ms:03d}"

    def format(self, record: logging.LogRecord) -> str:
        record.level_short = short_level_letter(record.levelno)
        saved_name = record.name
        record.name = abbreviate_logger_name(saved_name)
        try:
            return super().format(record)
        finally:
            record.name = saved_name


__all__ = [
    "ShortLevelFormatter",
    "abbreviate_logger_name",
    "short_level_letter",
]
