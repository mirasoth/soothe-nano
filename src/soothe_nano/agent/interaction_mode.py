"""ASK vs AGENT interaction-mode profiles for Coding CoreAgent.

Default mode is ``agent`` (full mutating tool surface). ``ask`` is hard
read-only: filesystem allowlist without writes, no shell/surgical tool
groups, write-deny FS permissions, and an ask policy profile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from soothe_deepagents.middleware.filesystem import FilesystemPermission, FsToolName

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

InteractionMode = Literal["agent", "ask"]
"""Supported CoreAgent interaction modes."""

FILESYSTEM_TOOLS_AGENT: list[FsToolName] = [
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "delete",
    "glob",
    "grep",
]
"""Built-in FS tools for AGENT mode (no sandbox ``execute``)."""

FILESYSTEM_TOOLS_ASK: list[FsToolName] = [
    "ls",
    "read_file",
    "file_info",
    "glob",
    "grep",
]
"""Hard Ask FS surface: reads only (aligned with planner recon tools)."""

ASK_MUTATING_TOOL_GROUPS: frozenset[str] = frozenset({"execution", "file_ops"})
"""Tool groups omitted when resolving tools for Ask mode."""

ASK_SUBAGENT_ALLOWLIST: frozenset[str] = frozenset({"planner"})
"""Subagents allowed on the Ask ``task`` catalog."""

ASK_POLICY_PROFILE = "ask"
"""Policy profile name for hard Ask (deny write/execute)."""

ASK_SYSTEM_PROMPT_SUFFIX = """\
## Interaction mode: Ask

You are in Ask mode. You may inspect the workspace with read-only tools \
(`ls`, `read_file`, `file_info`, `glob`, `grep`) and answer questions. \
Do not create, edit, or delete files. Do not run shell commands or other \
mutating tools. If the user needs changes applied, explain what to do and \
ask them to switch to Agent mode."""


def ask_permissions() -> list[FilesystemPermission]:
    """Return soothe-deepagents permissions that deny all filesystem writes."""
    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/**"],
            mode="deny",
        ),
    ]


def resolve_interaction_mode(
    explicit: InteractionMode | None,
    config: SootheConfig | Any | None = None,
) -> InteractionMode:
    """Resolve interaction mode from kwarg, then config, defaulting to agent.

    Args:
        explicit: Optional override from ``create_nano_agent`` / builder.
        config: Optional Soothe config with ``agent.runtime.interaction_mode``.

    Returns:
        ``\"agent\"`` or ``\"ask\"``.
    """
    if explicit in ("agent", "ask"):
        return explicit
    runtime = getattr(getattr(config, "agent", None), "runtime", None)
    raw = getattr(runtime, "interaction_mode", None)
    if raw in ("agent", "ask"):
        return raw
    return "agent"


def filter_subagents_for_mode(
    subagents: list[Any],
    mode: InteractionMode,
) -> list[Any]:
    """Filter subagent specs for the active interaction mode.

    Args:
        subagents: Resolved subagent specs.
        mode: Active interaction mode.

    Returns:
        Unchanged list for agent mode; Ask allowlist only for ask mode.
    """
    if mode != "ask":
        return list(subagents)
    from soothe_nano.agent.subagent_catalog import spec_subagent_name

    kept: list[Any] = []
    for spec in subagents:
        name = spec_subagent_name(spec)
        if name and name in ASK_SUBAGENT_ALLOWLIST:
            kept.append(spec)
    return kept


def append_ask_system_prompt(system_prompt: str) -> str:
    """Append the Ask-mode instruction block to a system prompt."""
    body = system_prompt.rstrip()
    if not body:
        return ASK_SYSTEM_PROMPT_SUFFIX
    return f"{body}\n\n{ASK_SYSTEM_PROMPT_SUFFIX}"


__all__ = [
    "ASK_MUTATING_TOOL_GROUPS",
    "ASK_POLICY_PROFILE",
    "ASK_SUBAGENT_ALLOWLIST",
    "ASK_SYSTEM_PROMPT_SUFFIX",
    "FILESYSTEM_TOOLS_AGENT",
    "FILESYSTEM_TOOLS_ASK",
    "InteractionMode",
    "append_ask_system_prompt",
    "ask_permissions",
    "filter_subagents_for_mode",
    "resolve_interaction_mode",
]
