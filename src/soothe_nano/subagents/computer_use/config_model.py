"""Typed YAML for the computer_use desktop-automation subagent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ComputerUseSubagentConfig(BaseModel):
    """Configuration for the computer_use subagent runtime.

    Args:
        runtime_dir: Base directory for desktop runtime files (screenshots, logs).
        screenshots_dir: Directory for captured screenshots.
        cleanup_on_exit: Remove temporary screenshots when session ends.
        max_steps: Maximum desktop automation steps per delegated task.
        screenshot_interval_s: Seconds between automatic screenshot captures.
            ``0`` disables periodic capture (only action-driven screenshots).
        screenshot_quality: JPEG quality (1-100) when saving screenshots.
        screenshot_format: Image format for screenshot persistence.
        screenshot_source: Capture source for screenshots. ``auto`` uses
            the macOS-native ``screencapture(1)`` CLI on Darwin (falling back
            to pyautogui on failure), ``screencapture`` forces the macOS
            ``screencapture`` CLI (Darwin only), ``pyautogui`` forces the
            cross-platform pyautogui backend.
        input_mode: Desktop input backend. ``auto`` selects the best available
            platform backend (pyautogui on macOS/Linux, Win32 on Windows).
            ``pyautogui`` forces the pyautogui backend. ``osascript`` forces
            AppleScript-based input on macOS.
        coordinate_scale: Coordinate space scale. ``1`` assumes pixel-accurate
            coordinates. ``2`` assumes Retina/HiDPI 2x scaling.
        action_delay_s: Delay in seconds after each input action (click, key)
            to allow UI to settle before the next screenshot.
        synthesis_role: Router role used for post-run result synthesis/quality gate.
        synthesis_timeout_sec: Timeout budget for synthesis LLM call.
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
