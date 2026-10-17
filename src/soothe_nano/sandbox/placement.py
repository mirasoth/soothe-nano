"""Tool placement model for sandbox mode (RFC §7.5).

Every tool active under a sandbox backend gets a placement:

- ``protocol``: FS primitive — served by the middleware over the backend.
- ``guest``: semantics migrated to guest commands (shell group; rerouted
  by the shell executor).
- ``shuttle``: byte shuttle — arguments pointing at guest paths are
  downloaded to a host temp dir, the original implementation runs
  host-side, results are uploaded back and temp paths are remapped.
- ``host``: no workspace coupling — runs as-is.
- ``deny``: fail-closed — not registered (build error or drop per
  ``sandbox.on_deny``).

Resolution order: config ``placement_overrides`` > explicit tool
declaration (``@tool(placement=...)`` / ``ToolMeta.placement``) > default
derivation table (registry category/outcome_type) > ``deny`` (registry
miss).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLACEMENT_PROTOCOL = "protocol"
PLACEMENT_GUEST = "guest"
PLACEMENT_SHUTTLE = "shuttle"
PLACEMENT_HOST = "host"
PLACEMENT_DENY = "deny"
VALID_PLACEMENTS = frozenset(
    {PLACEMENT_PROTOCOL, PLACEMENT_GUEST, PLACEMENT_SHUTTLE, PLACEMENT_HOST, PLACEMENT_DENY}
)

DEFAULT_SHUTTLE_MAX_BYTES = 32 * 1024 * 1024

_FS_PRIMITIVE_NAMES = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "file_info",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "apply_diff",
    }
)
_SHELL_TOOL_NAMES = frozenset(
    {"run_command", "run_python", "run_background", "tail_background_log", "kill_process"}
)

HOST_INFRA_TOOL_NAMES = frozenset(
    {
        # Catalog/listing tools: pure metadata over the host tool registry —
        # no filesystem or execution reach.
        "search_tools",
        "search_skills",
        "invoke_skill",
        "search_mcp_tools",
        "mcp_resources_list",
    }
)

_FALLBACK_PATH_ARG_KEYS = ("path", "file_path", "filepath", "filename")


@dataclass(frozen=True, slots=True)
class ToolPlacementReport:
    """Build-time placement decisions, for logs and test assertions."""

    placements: dict[str, str] = field(default_factory=dict)
    dropped: tuple[str, ...] = ()


def resolve_placement(
    tool_name: str,
    *,
    tool: Any = None,
    config: Any = None,
) -> str:
    """Resolve the placement for one tool (precedence per module docstring)."""
    override = getattr(getattr(config, "sandbox", None), "placement_overrides", None) or {}
    if tool_name in override:
        return str(override[tool_name])

    declared = getattr(tool, "_tool_placement", None)
    if declared is None:
        from soothe_nano.tools.metadata import TOOL_REGISTRY

        meta = TOOL_REGISTRY.get(tool_name)
        declared = getattr(meta, "placement", None)
    if declared is not None:
        return str(declared)

    if tool_name in _FS_PRIMITIVE_NAMES:
        return PLACEMENT_PROTOCOL
    if tool_name in _SHELL_TOOL_NAMES:
        return PLACEMENT_GUEST
    if tool_name in HOST_INFRA_TOOL_NAMES:
        return PLACEMENT_HOST

    from soothe_nano.tools.metadata import TOOL_REGISTRY

    meta = TOOL_REGISTRY.get(tool_name)
    if meta is None:
        # Fail-closed: unregistered custom / MCP / plugin tools (§7.5.5).
        return PLACEMENT_DENY
    outcome = getattr(meta, "outcome_type", None) or ""
    category = getattr(meta, "category", "generic")
    if outcome == "code_exec" or category == "execution":
        return PLACEMENT_GUEST
    if outcome in ("file_read", "file_write"):
        return PLACEMENT_SHUTTLE
    return PLACEMENT_HOST


def _shuttle_path_arg_keys(tool_name: str, args: dict[str, Any]) -> tuple[str, ...]:
    from soothe_nano.tools.metadata import TOOL_REGISTRY

    meta = TOOL_REGISTRY.get(tool_name)
    keys = tuple(getattr(meta, "path_arg_keys", ()) or ()) or _FALLBACK_PATH_ARG_KEYS
    return tuple(k for k in keys if k in args and isinstance(args[k], str) and args[k])


def _writes_back(tool_name: str) -> bool:
    from soothe_nano.tools.metadata import TOOL_REGISTRY

    meta = TOOL_REGISTRY.get(tool_name)
    return (getattr(meta, "outcome_type", None) or "") == "file_write"


def _reverse_map(output: str, mapping: dict[str, str]) -> str:
    """Replace host temp paths in tool output with the guest paths they mirror."""
    for tmp_path, vm_path in mapping.items():
        output = output.replace(tmp_path, vm_path)
    return output


def wrap_shuttle_tool(
    tool: Any,
    *,
    backend: Any,
    config: Any = None,
) -> Any:
    """Wrap a tool for ``shuttle`` placement (§7.5.6).

    Path arguments (per ``ToolMeta.path_arg_keys``) are downloaded from the
    guest backend into a per-call host temp dir, the original implementation
    runs on the copies, ``file_write`` outcomes are uploaded back, and every
    host temp path that leaks into the result is remapped to the guest path.
    Non-StructuredTool values pass through unchanged with a warning.
    """
    from langchain_core.tools import StructuredTool

    if not isinstance(tool, StructuredTool):
        logger.warning(
            "[Init] Shuttle placement not supported for %r (%s); running host-side",
            getattr(tool, "name", tool),
            type(tool).__name__,
        )
        return tool

    max_bytes = int(
        getattr(getattr(config, "sandbox", None), "max_shuttle_bytes", None)
        or DEFAULT_SHUTTLE_MAX_BYTES
    )
    original_func = tool.func

    def _shuttled(**kwargs: Any) -> Any:
        tool_name = tool.name
        mapping: dict[str, str] = {}
        tmp_dir = tempfile.mkdtemp(prefix="soothe-shuttle-")
        try:
            path_args = _shuttle_path_arg_keys(tool_name, kwargs)
            for key in path_args:
                vm_path = kwargs[key]
                downloads = backend.download_files([vm_path])
                entry = downloads[0]
                if entry.error is not None:
                    raise RuntimeError(f"shuttle download failed for {vm_path!r}: {entry.error}")
                content = entry.content or b""
                if len(content) > max_bytes:
                    raise RuntimeError(
                        f"shuttle transfer for {vm_path!r} exceeds sandbox.max_shuttle_bytes "
                        f"({len(content)} > {max_bytes})"
                    )
                host_path = str(Path(tmp_dir) / Path(vm_path).name)
                Path(host_path).write_bytes(content)
                mapping[host_path] = vm_path
                kwargs[key] = host_path

            result = original_func(**kwargs)
            if isinstance(result, str):
                result = _reverse_map(result, mapping)

            if _writes_back(tool_name):
                for key in path_args:
                    host_path = kwargs[key]
                    vm_path = mapping.get(host_path)
                    if vm_path is None:
                        continue
                    uploads = backend.upload_files([(vm_path, Path(host_path).read_bytes())])
                    if uploads[0].error is not None:
                        raise RuntimeError(
                            f"shuttle upload failed for {vm_path!r}: {uploads[0].error}"
                        )
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return tool.__class__(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        func=_shuttled,
    )
