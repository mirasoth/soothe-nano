"""Tool metadata registry and display utilities.

This package provides the canonical tool display metadata registry
used by CLI, TUI, and formatting utilities to present tools consistently.

The registry includes:
- Tool display names and aliases
- Path argument indicators (which tools take file/workspace paths)
- Header-style tool names for TUI
- Outcome type classification for event handling
"""

__all__ = [
    "ToolMeta",
    "TOOL_REGISTRY",
    "get_tool_meta",
    "is_policy_filesystem_tool",
    "extract_filesystem_path_for_policy",
]

from soothe_nano.tools.metadata import (
    TOOL_REGISTRY,
    ToolMeta,
    extract_filesystem_path_for_policy,
    get_tool_meta,
    is_policy_filesystem_tool,
)
