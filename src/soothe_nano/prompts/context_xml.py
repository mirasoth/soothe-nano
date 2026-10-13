"""Dynamic context as nested XML (shared cache-aligned prefix)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from soothe_nano._rust_compat import (
    build_context_xml_rust,
    build_environment_section_rust,
    build_workspace_section_rust,
)
from soothe_nano.utils.text_preview import preview_first

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

RFC104_CONTEXT_XML_VERSION = "1"


def _xml_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_attr(value: object) -> str:
    return _xml_text(value).replace('"', "&quot;")


def build_soothe_environment_section(*, model: str) -> str:
    """Build nested ENVIRONMENT XML block (no SOOTHE_ prefix).

    Delegates to Rust for XML assembly and platform introspection.
    The Rust binding round-trips into Python for ``is_rg_available()``
    and ``get_knowledge_cutoff(model)``.

    Args:
        model: Resolved default model id (e.g. from `config.resolve_model` for the default role).

    Returns:
        Single XML section string.
    """
    return build_environment_section_rust(model)


def build_soothe_workspace_section(
    workspace: Path | None,
    *,
    include_layout_preview: bool = False,
    max_layout_entries: int = 40,
    include_readme_excerpt: bool = False,
    readme_max_chars: int = 500,
) -> str:
    """Build nested WORKSPACE XML block (no SOOTHE_ prefix).

    Delegates to Rust for directory listing, README reading, and XML assembly.

    Args:
        workspace: Project root; when None, the process current working directory is used.
        include_layout_preview: When True, add capped top-level name list.
        max_layout_entries: Cap for layout preview.
        include_readme_excerpt: When True, add short README snippet if present.
        readme_max_chars: Max characters for README excerpt.

    Returns:
        Single XML section string.
    """
    ws_str = str(workspace) if workspace is not None else None
    return build_workspace_section_rust(
        ws_str,
        include_layout_preview=include_layout_preview,
        max_layout_entries=max_layout_entries,
        include_readme_excerpt=include_readme_excerpt,
        readme_max_chars=readme_max_chars,
    )


def build_soothe_thread_section(thread_context: dict[str, Any]) -> str:
    """Build SOOTHE_THREAD XML block from runner thread dict.

    Optimized for prompt caching - removed version attribute.
    """
    thread_id = thread_context.get("thread_id", "unknown")
    turns = thread_context.get("conversation_turns", 0)
    plan = thread_context.get("current_plan")

    parts: list[str] = [
        f"<thread_id>{_xml_text(thread_id)}</thread_id>",
        f"<conversation_turns>{int(turns)}</conversation_turns>",
    ]
    if plan:
        parts.append(f"<current_plan>{_xml_text(preview_first(str(plan), 100))}</current_plan>")
    inner = "\n".join(parts)
    # Removed version attribute for cache optimization.
    return f"<SOOTHE_THREAD>\n{inner}\n</SOOTHE_THREAD>"


def build_soothe_protocols_section(protocol_summary: dict[str, Any]) -> str:
    """Build SOOTHE_PROTOCOLS XML block, or empty string when nothing is active.

    Optimized for prompt caching - removed version attribute.
    """
    entries: list[str] = []
    proto_names = ["memory", "planner", "policy"]
    for proto_name in proto_names:
        proto_info = protocol_summary.get(proto_name)
        if not proto_info:
            continue
        proto_type = proto_info.get("type", "unknown")
        stats = proto_info.get("stats", "")
        stat_attr = f' stats="{_xml_attr(stats)}"' if stats else ""
        entries.append(
            f'<protocol id="{_xml_attr(proto_name)}" type="{_xml_attr(proto_type)}"{stat_attr}/>'
        )
    if not entries:
        return ""
    inner = "\n".join(entries)
    # Removed version attribute for cache optimization.
    return f"<SOOTHE_PROTOCOLS>\n{inner}\n</SOOTHE_PROTOCOLS>"


def build_shared_environment_workspace_prefix(
    config: SootheConfig,
    workspace: str | None,
    *,
    include_workspace_extras: bool = False,
) -> str:
    """ENVIRONMENT + WORKSPACE prefix for planners and Reason prompts."""
    model = config.resolve_model("default")
    env = build_soothe_environment_section(model=model)
    ws_path = Path(workspace).expanduser().resolve() if workspace else None
    ws = build_soothe_workspace_section(
        ws_path,
        include_layout_preview=include_workspace_extras,
        include_readme_excerpt=include_workspace_extras,
    )
    return f"{env}\n\n{ws}\n"


def build_context_sections_for_complexity(
    *,
    config: SootheConfig,
    complexity: Literal["minimal", "simple", "medium", "complex"],
    state: dict[str, Any],
    include_workspace_extras: bool = False,
) -> list[str]:
    """Ordered XML blocks for system prompt (excludes static base prompt and date line)."""
    if complexity == "minimal":
        return []
    model = config.resolve_model("default")
    sections: list[str] = [build_soothe_environment_section(model=model)]
    workspace_raw = state.get("workspace")
    workspace_path = Path(str(workspace_raw)).expanduser().resolve() if workspace_raw else None
    sections.append(
        build_soothe_workspace_section(
            workspace_path,
            include_layout_preview=include_workspace_extras,
            include_readme_excerpt=include_workspace_extras,
        )
    )
    if complexity == "complex":
        thread_context = state.get("thread_context") or {}
        if thread_context:
            sections.append(build_soothe_thread_section(thread_context))
        protocol_summary = state.get("protocol_summary") or {}
        proto = build_soothe_protocols_section(protocol_summary)
        if proto:
            sections.append(proto)
    return sections


def build_context_xml(workspace: str, files: list[tuple[str, int, int]]) -> str:
    """Build a simple context XML from workspace path and file list."""
    return build_context_xml_rust(workspace, files)
