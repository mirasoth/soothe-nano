"""Typed YAML for the computer_use desktop-automation subagent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ComputerUseSubagentConfig(BaseModel):
    """Typed YAML config for the computer_use subagent runtime.

    Coordinate conventions: ``x``/``y`` are pixels from the top-left corner
    (0, 0); set ``coordinate_scale`` to ``2`` for Retina/HiDPI 2x scaling.
    ``screenshot_source``: ``auto`` uses the macOS-native ``screencapture(1)``
    CLI on Darwin (falls back to pyautogui); ``screencapture`` forces the
    macOS CLI (Darwin only); ``pyautogui`` forces the cross-platform backend.
    ``input_mode`` selects the input backend (``auto`` picks the best platform
    backend). ``synthesis_role`` drives the post-run result quality gate.

    Example::

        config = ComputerUseSubagentConfig(max_steps=50, coordinate_scale=2)
    """

    max_steps: int = Field(
        default=99, ge=1, description="Maximum desktop automation steps per task."
    )
    runtime_dir: str = ""
    screenshots_dir: str = ""
    cleanup_on_exit: bool = True
    backend: str = Field(
        default="pyautogui",
        description=(
            "Desktop input backend implementation to instantiate. "
            "``pyautogui`` uses the pyautogui-based backend (default, "
            "cross-platform). ``auto`` resolves to the best available "
            "platform backend at runtime. ``osascript`` uses AppleScript "
            "input on macOS (not yet implemented)."
        ),
    )
    screenshot_interval_s: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
        description="Seconds between automatic screenshots (0 = disabled).",
    )
    screenshot_quality: int = Field(
        default=85, ge=1, le=100, description="Screenshot JPEG quality."
    )
    screenshot_format: Literal["png", "jpeg"] = "png"
    screenshot_source: Literal["auto", "pyautogui", "screencapture"] = Field(
        default="auto",
        description=(
            "Screenshot capture source. ``auto`` uses the macOS-native "
            "``screencapture(1)`` CLI on Darwin and falls back to pyautogui "
            "on failure; on non-Darwin it uses pyautogui directly. "
            "``screencapture`` forces the macOS CLI (Darwin only). "
            "``pyautogui`` forces the cross-platform pyautogui backend."
        ),
    )
    input_mode: Literal["auto", "pyautogui", "osascript"] = "auto"
    coordinate_scale: int = Field(
        default=1, ge=1, le=4, description="Coordinate scale factor (1=1x, 2=Retina)."
    )
    action_delay_s: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description="Delay after each input action for UI to settle.",
    )
    synthesis_role: str = Field(
        default="default",
        description="Router role for computer_use result synthesis/quality gate.",
    )
    synthesis_timeout_sec: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Timeout in seconds for computer_use synthesis call.",
    )


__all__ = ["ComputerUseSubagentConfig"]
