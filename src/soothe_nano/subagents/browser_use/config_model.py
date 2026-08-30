"""Typed YAML for the browser_use community subagent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BrowserUseSubagentConfig(BaseModel):
    """Typed YAML config for the browser_use subagent runtime.

    ``profile_mode`` controls browser profile lifecycle: ``persistent`` reuses
    a shared profile across invocations (keeps cookies/sessions); ``ephemeral``
    creates a fresh UUID-named profile per invocation and deletes it on exit
    (safe for concurrent browser tasks). ``synthesis_role`` drives the
    post-run result quality gate.

    Example::

        config = BrowserUseSubagentConfig(max_steps=20, profile_mode="persistent")
    """

    max_steps: int = Field(
        default=10, ge=1, description="Maximum browser automation steps per task."
    )
    runtime_dir: str = ""
    downloads_dir: str = ""
    user_data_dir: str = ""
    extensions_dir: str = ""
    cleanup_on_exit: bool = True
    disable_extensions: bool = True
    disable_cloud: bool = True
    disable_telemetry: bool = True
    enable_existing_browser: bool = True
    browser_start_timeout: int = 90
    profile_mode: Literal["persistent", "ephemeral"] = "ephemeral"
    synthesis_role: str = Field(
        default="default",
        description="Router role for browser_use result synthesis/quality gate.",
    )
    synthesis_timeout_sec: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Timeout in seconds for browser_use synthesis call.",
    )


__all__ = ["BrowserUseSubagentConfig"]
