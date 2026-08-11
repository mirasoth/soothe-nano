"""Desktop automation subagent package.

This package provides desktop automation capabilities using pyautogui.
Can take screenshots, click at screen coordinates, type text, and press
keyboard hotkeys. Uses a vision-capable LLM to drive an agentic loop.
"""

from __future__ import annotations

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from . import events as _events  # noqa: F401 — register soothe.subagent.computer_use.* wire types
from .implementation import (
    _build_computer_use_graph,  # noqa: F401 - needed for tests
    create_computer_use_subagent,
)

__all__ = ["ComputerUsePlugin", "create_computer_use_subagent"]


@plugin(
    name="computer_use",
    version="1.0.0",
    description="Desktop automation using pyautogui (screenshots, clicks, keyboard)",
    trust_level="built-in",
)
class ComputerUsePlugin:
    """Desktop automation plugin.

    Provides computer_use subagent for desktop GUI automation: screenshots,
    mouse clicks, keyboard typing, and hotkey combinations.
    """

    async def on_load(self, context: Any) -> None:
        """Soft-check pyautogui availability (backend is lazy).

        pyautogui is the default input backend, but on macOS the screenshot
        path can fall back to the native ``screencapture`` CLI when pyautogui
        is absent or Screen Recording permission is missing. Therefore we
        only emit a warning (not a hard ``PluginError``) when pyautogui
        cannot be imported, so that screenshot-only flows still work.
        """
        try:
            import pyautogui  # noqa: F401
        except ImportError:
            import platform as _platform

            if _platform.system().lower() == "darwin":
                # macOS: screencapture CLI provides a native screenshot
                # fallback, so the plugin can still load and support
                # screenshot-only flows without pyautogui.
                context.logger.warning(
                    "pyautogui not installed; macOS screencapture fallback "
                    "will be used for screenshots, but click/keyboard "
                    "actions will be unavailable. Install pyautogui "
                    "(pip install -U soothe-nano) for full input support."
                )
            else:
                from soothe_sdk.core.exceptions import PluginError

                raise PluginError(
                    "pyautogui library not installed. Install with: pip install -U soothe-nano"
                )
        else:
            context.logger.info("ComputerUse plugin loaded")

    @subagent(
        name="computer_use",
        description=(
            "Desktop automation specialist for GUI tasks. Can take screenshots, "
            "click at screen coordinates, type text, press keyboard keys and "
            "hotkeys, and scroll. Use for desktop application control, visual "
            "UI interaction, and screen-based automation."
        ),
        system_context="""<COMPUTER_CONTEXT>
<SCREEN_RULES>
Always take a screenshot first to understand the current screen state before acting.
Coordinates are in pixels from the top-left corner (0, 0).
Verify clickable targets are visible before clicking.
Handle dialog boxes, popups, and notifications that may appear.
</SCREEN_RULES>
<INPUT_INTERPRETATION>
Screenshot results include file path and screen dimensions (width, height).
Click results confirm the action with coordinates and button used.
Keyboard results confirm the typed text or pressed keys.
Scroll results confirm direction and amount.
</INPUT_INTERPRETATION>
<BEST_PRACTICES>
Take a screenshot after significant actions to verify the result.
Use small movements and verify each step before proceeding.
For text input, ensure the target field is focused before typing.
Use hotkeys for application shortcuts (e.g. ctrl+c, cmd+space).
</BEST_PRACTICES>
</COMPUTER_CONTEXT>""",
        triggers=["WORKSPACE", "COMPUTER_CONTEXT"],
    )
    async def create_computer_use(
        self,
        model: Any = None,  # noqa: ARG002
        config: Any = None,
        context: Any = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create computer_use automation subagent.

        Args:
            model: Unused; kept for ``@subagent`` factory wrapper compatibility.
            config: Soothe configuration (router + ``subagents.computer_use.model_role``).
            context: Plugin context.
            **kwargs: Additional computer config (max_steps, backend, etc.).

        Returns:
            Subagent dict with name, description, and runnable.
        """
        from soothe_nano.subagents.computer_use.config_model import (
            ComputerUseSubagentConfig,
        )

        computer_config = None
        if hasattr(config, "subagents") and "computer_use" in config.subagents:
            subagent_config = config.subagents["computer_use"]
            if subagent_config.enabled and subagent_config.config:
                computer_config = ComputerUseSubagentConfig(**subagent_config.config)
        if computer_config is None:
            computer_config = ComputerUseSubagentConfig()

        return create_computer_use_subagent(
            max_steps=computer_config.max_steps,
            config=computer_config,
            soothe_config=config,
        )
