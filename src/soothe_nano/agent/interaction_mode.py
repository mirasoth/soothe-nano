"""ASK / PLAN vs AGENT interaction-mode profiles for Coding CoreAgent.

Default mode is ``agent`` (full mutating tool surface). ``ask`` is hard
read-only: filesystem allowlist without writes, no shell/surgical tool
groups, write-deny FS permissions, and an ask policy profile. ``plan``
mirrors ``ask`` read-only constraints but with a plan-specific system
prompt and an empty subagent allowlist (plan mode uses no subagents).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from soothe_deepagents.middleware.filesystem import FilesystemPermission, FsToolName

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

InteractionMode = Literal["agent", "ask", "plan"]
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

FILESYSTEM_TOOLS_PLAN: list[FsToolName] = list(FILESYSTEM_TOOLS_ASK)
"""Plan-mode FS surface: same read-only allowlist as Ask."""

ASK_MUTATING_TOOL_GROUPS: frozenset[str] = frozenset({"execution", "file_ops"})
"""Tool groups omitted when resolving tools for Ask / Plan mode."""

ASK_SUBAGENT_ALLOWLIST: frozenset[str] = frozenset({"planner"})
"""Subagents allowed on the Ask ``task`` catalog."""

PLAN_SUBAGENT_ALLOWLIST: frozenset[str] = frozenset()
"""Subagents allowed on the Plan ``task`` catalog (empty — plan mode uses none)."""

ASK_POLICY_PROFILE = "ask"
"""Policy profile name for hard Ask (deny write/execute)."""

PLAN_POLICY_PROFILE = "plan"
"""Policy profile name for Plan mode (deny write/execute, same constraints as Ask)."""

ASK_SYSTEM_PROMPT_SUFFIX = """\
## Interaction mode: Ask

You are in Ask mode. You may inspect the workspace with read-only tools \
(`ls`, `read_file`, `file_info`, `glob`, `grep`) and answer questions. \
Do not create, edit, or delete files. Do not run shell commands or other \
mutating tools. If the user needs changes applied, explain what to do and \
ask them to switch to Agent mode."""

PLAN_SYSTEM_PROMPT_SUFFIX = """\
## Interaction mode: Plan

You are in Plan mode. You may inspect the workspace with read-only tools \
(`ls`, `read_file`, `file_info`, `glob`, `grep`) to research the codebase \
and produce a detailed implementation plan. Do not create, edit, or delete \
files. Do not run shell commands or other mutating tools. Focus on \
understanding the architecture, identifying the right files to change, \
and producing a clear, actionable plan that can be approved and executed \
in Agent mode."""

READONLY_GP_SYSTEM_PROMPT = """\
## General-Purpose Subagent: Read-Only Mode

You are a read-only research subagent. You may inspect the workspace with \
read-only filesystem tools (`ls`, `read_file`, `file_info`, `glob`, `grep`) \
to research complex questions, search for files and content, and gather \
context. You MUST NOT create, edit, or delete files. You MUST NOT run shell \
commands or other mutating tools. If changes are needed, report your findings \
to the parent agent so it can apply them."""


def ask_permissions() -> list[FilesystemPermission]:
    """Return soothe-deepagents permissions that deny all filesystem writes."""
    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/**"],
            mode="deny",
        ),
    ]


def plan_permissions() -> list[FilesystemPermission]:
    """Return write-deny permissions for Plan mode (same as Ask)."""
    return ask_permissions()


def resolve_interaction_mode(
    explicit: InteractionMode | None,
    config: SootheConfig | Any | None = None,
) -> InteractionMode:
    """Resolve interaction mode from kwarg, then config, defaulting to agent.

    Args:
        explicit: Optional override from ``create_nano_agent`` / builder.
        config: Optional Soothe config with ``agent.runtime.interaction_mode``.

    Returns:
        ``\"agent\"``, ``\"ask\"``, or ``\"plan\"``.
    """
    if explicit in ("agent", "ask", "plan"):
        return explicit
    runtime = getattr(getattr(config, "agent", None), "runtime", None)
    raw = getattr(runtime, "interaction_mode", None)
    if raw in ("agent", "ask", "plan"):
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
        Unchanged list for agent mode; allowlist only for ask/plan modes.
    """
    if mode not in ("ask", "plan"):
        return list(subagents)
    from soothe_nano.agent.subagent_catalog import spec_subagent_name

    allowlist = ASK_SUBAGENT_ALLOWLIST if mode == "ask" else PLAN_SUBAGENT_ALLOWLIST
    kept: list[Any] = []
    for spec in subagents:
        name = spec_subagent_name(spec)
        if name and name in allowlist:
            kept.append(spec)
    return kept


def append_ask_system_prompt(system_prompt: str) -> str:
    """Append the Ask-mode instruction block to a system prompt."""
    body = system_prompt.rstrip()
    if not body:
        return ASK_SYSTEM_PROMPT_SUFFIX
    return f"{body}\n\n{ASK_SYSTEM_PROMPT_SUFFIX}"


def append_plan_system_prompt(system_prompt: str) -> str:
    """Append the Plan-mode instruction block to a system prompt."""
    body = system_prompt.rstrip()
    if not body:
        return PLAN_SYSTEM_PROMPT_SUFFIX
    return f"{body}\n\n{PLAN_SYSTEM_PROMPT_SUFFIX}"


__all__ = [
    "ASK_MUTATING_TOOL_GROUPS",
    "ASK_POLICY_PROFILE",
    "FILESYSTEM_TOOLS_AGENT",
    "FILESYSTEM_TOOLS_ASK",
    "FILESYSTEM_TOOLS_PLAN",
    "InteractionMode",
    "PLAN_POLICY_PROFILE",
    "READONLY_GP_SYSTEM_PROMPT",
    "append_ask_system_prompt",
    "append_plan_system_prompt",
    "ask_permissions",
    "filter_subagents_for_mode",
    "plan_permissions",
    "resolve_interaction_mode",
]
