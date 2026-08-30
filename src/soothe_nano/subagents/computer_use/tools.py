"""LangChain ``BaseTool`` schemas for computer_use desktop input.

Defines schemas for screenshots, mouse clicks, keyboard events, and scroll.
Each tool accepts structured Pydantic input and returns a JSON-serializable
dict. Input execution is delegated to a ``_DesktopInputBackend`` adapter that
the agent loop injects at runtime, so the tool schemas are pure interface
definitions and the backend can be swapped (pyautogui, osascript, etc.).
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─── Input Schemas ────────────────────────────────────────────────────────


class ScreenshotInput(BaseModel):
    """Input for screenshot capture."""

    reason: str = Field(
        default="",
        description="Optional reason for capturing this screenshot (for audit log).",
    )
    region: str = Field(
        default="full",
        description=(
            "Screenshot region. 'full' captures the entire screen. "
            "Alternatively, 'left,top,right,bottom' for a specific rectangle."
        ),
    )


class ClickInput(BaseModel):
    """Input for mouse click actions."""

    x: int = Field(
        ...,
        ge=0,
        description="X coordinate (in pixels) of the click target.",
    )
    y: int = Field(
        ...,
        ge=0,
        description="Y coordinate (in pixels) of the click target.",
    )
    button: str = Field(
        default="left",
        description="Mouse button: 'left', 'right', or 'middle'.",
    )
    click_type: str = Field(
        default="single",
        description="Click type: 'single', 'double', or 'triple'.",
    )


class KeyboardInput(BaseModel):
    """Input for keyboard typing and hotkey actions."""

    action_type: str = Field(
        ...,
        description=(
            "Keyboard action type: 'type' for typing a string of text, "
            "'key' for pressing a single key (e.g. 'enter', 'tab', 'escape'), "
            "'hotkey' for pressing a key combination (e.g. 'ctrl+c')."
        ),
    )
    text: str = Field(
        default="",
        description="Text to type when action_type='type'.",
    )
    key: str = Field(
        default="",
        description="Key to press when action_type='key' (e.g. 'enter', 'tab').",
    )
    keys: str = Field(
        default="",
        description=(
            "Comma-separated key combination when action_type='hotkey' (e.g. 'ctrl,shift,esc')."
        ),
    )


class ScrollInput(BaseModel):
    """Input for mouse scroll actions."""

    x: int = Field(
        default=0,
        ge=0,
        description="X coordinate to scroll at (0 = current position).",
    )
    y: int = Field(
        default=0,
        ge=0,
        description="Y coordinate to scroll at (0 = current position).",
    )
    direction: str = Field(
        default="down",
        description="Scroll direction: 'up' or 'down'.",
    )
    amount: int = Field(
        default=3,
        ge=1,
        description="Number of scroll clicks.",
    )


# ─── Backend Protocol ─────────────────────────────────────────────────────


class _DesktopInputBackend:
    """Abstract backend protocol for desktop input execution.

    The agent loop provides a concrete implementation (pyautogui, osascript,
    etc.) and injects it into each tool at runtime. This keeps the tool
    schemas as pure interface definitions.
    """

    def capture_screenshot(
        self,
        *,
        region: str = "full",
        save_path: str | None = None,
    ) -> dict[str, Any]:
        """Capture a screenshot and return metadata."""
        msg = "capture_screenshot not implemented"
        raise NotImplementedError(msg)

    async def acapture_screenshot(
        self,
        *,
        region: str = "full",
        save_path: str | None = None,
    ) -> dict[str, Any]:
        """Async screenshot capture (default: delegates to sync)."""
        return self.capture_screenshot(region=region, save_path=save_path)

    def click(
        self,
        *,
        x: int,
        y: int,
        button: str = "left",
        click_type: str = "single",
    ) -> dict[str, Any]:
        """Perform a mouse click at (x, y)."""
        msg = "click not implemented"
        raise NotImplementedError(msg)

    async def aclick(
        self,
        *,
        x: int,
        y: int,
        button: str = "left",
        click_type: str = "single",
    ) -> dict[str, Any]:
        """Async click (default: delegates to sync)."""
        return self.click(x=x, y=y, button=button, click_type=click_type)

    def keyboard(
        self,
        *,
        action_type: str,
        text: str = "",
        key: str = "",
        keys: str = "",
    ) -> dict[str, Any]:
        """Perform a keyboard action."""
        msg = "keyboard not implemented"
        raise NotImplementedError(msg)

    async def akeyboard(
        self,
        *,
        action_type: str,
        text: str = "",
        key: str = "",
        keys: str = "",
    ) -> dict[str, Any]:
        """Async keyboard (default: delegates to sync)."""
        return self.keyboard(action_type=action_type, text=text, key=key, keys=keys)

    def scroll(
        self,
        *,
        x: int = 0,
        y: int = 0,
        direction: str = "down",
        amount: int = 3,
    ) -> dict[str, Any]:
        """Perform a scroll action."""
        msg = "scroll not implemented"
        raise NotImplementedError(msg)

    async def ascroll(
        self,
        *,
        x: int = 0,
        y: int = 0,
        direction: str = "down",
        amount: int = 3,
    ) -> dict[str, Any]:
        """Async scroll (default: delegates to sync)."""
        return self.scroll(x=x, y=y, direction=direction, amount=amount)

    def close(self) -> None:
        """Release any resources held by the backend."""
        pass

    async def aclose(self) -> None:
        """Async cleanup (default: delegates to sync)."""
        self.close()


# ─── Tool Implementations ─────────────────────────────────────────────────


class ScreenshotTool(BaseTool):
    """Capture a desktop screenshot.

    Captures the full screen (or a specified region) and saves it to the
    session's screenshot directory. Returns the file path and screen dimensions
    so the agent can reason about the visual state.
    """

    name: str = "computer_screenshot"
    description: str = (
        "Capture a desktop screenshot. Returns the screenshot file path and "
        "screen dimensions. Use to inspect the current screen state before "
        "deciding the next action."
    )
    args_schema: type[BaseModel] = ScreenshotInput
    backend: Any = None  # Injected _DesktopInputBackend instance

    def _run(
        self,
        reason: str = "",
        region: str = "full",
        *,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return self.backend.capture_screenshot(region=region)

    async def _arun(
        self,
        reason: str = "",
        region: str = "full",
        *,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return await self.backend.acapture_screenshot(region=region)


class ClickTool(BaseTool):
    """Perform a mouse click at a screen coordinate.

    Moves the cursor to (x, y) and performs a click with the specified
    button and click type.
    """

    name: str = "computer_click"
    description: str = (
        "Click at a screen coordinate (x, y). Supports left/right/middle "
        "buttons and single/double/triple clicks. Use after taking a "
        "screenshot to identify the target coordinate."
    )
    args_schema: type[BaseModel] = ClickInput
    backend: Any = None

    def _run(
        self,
        x: int,
        y: int,
        button: str = "left",
        click_type: str = "single",
        *,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return self.backend.click(x=x, y=y, button=button, click_type=click_type)

    async def _arun(
        self,
        x: int,
        y: int,
        button: str = "left",
        click_type: str = "single",
        *,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return await self.backend.aclick(x=x, y=y, button=button, click_type=click_type)


class KeyboardTool(BaseTool):
    """Perform keyboard actions (type text, press keys, hotkeys).

    Supports three action types:
    - 'type': Type a string of text character-by-character
    - 'key': Press and release a single key (e.g. 'enter', 'tab')
    - 'hotkey': Press a key combination (e.g. 'ctrl+c')
    """

    name: str = "computer_keyboard"
    description: str = (
        "Perform keyboard actions. Use action_type='type' to type text, "
        "'key' to press a single key (enter, tab, escape), or 'hotkey' "
        "for key combinations (ctrl+c, cmd+space)."
    )
    args_schema: type[BaseModel] = KeyboardInput
    backend: Any = None

    def _run(
        self,
        action_type: str,
        text: str = "",
        key: str = "",
        keys: str = "",
        *,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return self.backend.keyboard(action_type=action_type, text=text, key=key, keys=keys)

    async def _arun(
        self,
        action_type: str,
        text: str = "",
        key: str = "",
        keys: str = "",
        *,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return await self.backend.akeyboard(action_type=action_type, text=text, key=key, keys=keys)


class ScrollTool(BaseTool):
    """Scroll the mouse wheel at a coordinate.

    Moves to (x, y) and scrolls up or down by the specified amount.
    """

    name: str = "computer_scroll"
    description: str = (
        "Scroll the mouse wheel at a screen coordinate. Use direction='up' "
        "or 'down' with an amount (number of scroll clicks)."
    )
    args_schema: type[BaseModel] = ScrollInput
    backend: Any = None

    def _run(
        self,
        x: int = 0,
        y: int = 0,
        direction: str = "down",
        amount: int = 3,
        *,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return self.backend.scroll(x=x, y=y, direction=direction, amount=amount)

    async def _arun(
        self,
        x: int = 0,
        y: int = 0,
        direction: str = "down",
        amount: int = 3,
        *,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        if self.backend is None:
            return {"error": "No input backend configured"}
        return await self.backend.ascroll(x=x, y=y, direction=direction, amount=amount)


# ─── Toolkit Assembly ────────────────────────────────────────────────────


class ComputerUseToolkit:
    """Assemble the computer_use input tools.

    Returns LangChain ``BaseTool`` instances. The ``backend`` must be
    injected into each tool before first invocation.
    """

    def __init__(self, backend: _DesktopInputBackend | None = None) -> None:
        self._backend = backend

    def get_tools(self) -> list[BaseTool]:
        """Return the list of computer_use input tools."""
        tools: list[BaseTool] = [
            ScreenshotTool(backend=self._backend),
            ClickTool(backend=self._backend),
            KeyboardTool(backend=self._backend),
            ScrollTool(backend=self._backend),
        ]
        return tools


__all__ = [
    "ClickInput",
    "ClickTool",
    "ComputerUseToolkit",
    "KeyboardInput",
    "KeyboardTool",
    "ScreenshotInput",
    "ScreenshotTool",
    "ScrollInput",
    "ScrollTool",
    "_DesktopInputBackend",
]
