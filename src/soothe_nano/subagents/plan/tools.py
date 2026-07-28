"""Readonly filesystem tools for the plan subagent (RFC-633)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLANNER_READONLY_TOOL_NAMES: tuple[str, ...] = (
    "glob",
    "grep",
    "ls",
    "read_file",
    "file_info",
)


def get_planner_readonly_tools(workspace: str | None = None) -> list[Any]:
    """Build the planner recon tool surface (no write/edit/delete/execute).

    Args:
        workspace: Workspace root; defaults to the process cwd.

    Returns:
        Ordered langchain tool instances present on ``SootheFilesystemMiddleware``.
    """
    from soothe_deepagents.backends.filesystem import FilesystemBackend

    from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

    root = workspace or os.getcwd()
    backend = FilesystemBackend(root_dir=Path(root), virtual_mode=False)
    middleware = SootheFilesystemMiddleware(
        backend=backend,
        backup_enabled=False,
        workspace_root=root,
    )
    by_name = {getattr(t, "name", ""): t for t in middleware.tools}
    tools = [by_name[name] for name in PLANNER_READONLY_TOOL_NAMES if name in by_name]
    missing = [n for n in PLANNER_READONLY_TOOL_NAMES if n not in by_name]
    if missing:
        logger.debug("Planner readonly tools missing from middleware: %s", missing)
    return tools
