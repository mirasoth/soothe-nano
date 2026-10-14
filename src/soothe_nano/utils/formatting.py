"""Formatting utilities for CLI display.

Utility functions for formatting paths, errors, and other display-related
operations used by both the SDK and CLI.

Module renamed from display.py to formatting.py (SDK refactoring)
for clearer purpose indication.
"""

from __future__ import annotations

from soothe_nano._rust_compat import (
    convert_and_abbreviate_path_rust as convert_and_abbreviate_path,
)
from soothe_nano._rust_compat import (
    format_cli_error_rust,
)
from soothe_nano._rust_compat import (
    log_preview_rust as log_preview,
)


def format_cli_error(error: Exception) -> str:
    """Format exception for CLI display (delegates to Rust).

    Args:
        error: Exception to format.

    Returns:
        Formatted error string suitable for CLI output.
    """
    return format_cli_error_rust(type(error).__name__, str(error))


__all__ = [
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "get_tool_display_name",
]


# Re-export get_tool_display_name from tools.metadata (canonical registry)
from soothe_nano.tools.metadata import get_tool_display_name  # noqa: E402, F401, I001 -- re-export after code
