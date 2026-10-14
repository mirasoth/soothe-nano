"""Configuration module for MemU."""

# Import markdown configuration (primary public API)
from .markdown_config import (
    MarkdownConfigManager,
    MarkdownFileConfig,
    get_config_manager,
)

__all__ = [
    "MarkdownConfigManager",
    "MarkdownFileConfig",
    "get_config_manager",
]
