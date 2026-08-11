"""Unit tests for computer_use click and typing workflows.

Validates the click/type action surface end-to-end through mocked backends:

- ``ClickTool._run`` / ``_arun`` sync & async paths
- ``KeyboardTool._run`` / ``_arun`` for ``type`` / ``key`` / ``hotkey``
- ``_execute_step`` agent-loop dispatcher routing for click and typing actions
- ``ComputerUseToolkit.get_tools()`` backend injection wiring
- Error path when ``backend is None``
- Pydantic schema validation (required fields, ge=0 bounds)

The mock backend (``_RecordingBackend``) records every call so tests assert
both that the backend received the expected arguments and that the tool
returned the backend's response dict verbatim.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe_nano.subagents.computer_use.config_model import (
    ComputerUseSubagentConfig,
)
from soothe_nano.subagents.computer_use.implementation import (
    _ComputerAction,
    _execute_step,
    _PyAutoGUIBackend,
)
from soothe_nano.subagents.computer_use.tools import (
    ClickInput,
    ClickTool,
    ComputerUseToolkit,
    KeyboardInput,
    KeyboardTool,
    _DesktopInputBackend,
)

# ─── Test doubles ─────────────────────────────────────────────────────────


class _RecordingBackend(_DesktopInputBackend):
    """Backend double that records calls and echoes canned responses.

    Each method appends the kwargs it was called with to ``calls`` and
    returns a deterministic dict. Async methods are real coroutines (not
    mocks) so they exercise the ``await`` path in tools.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def capture_screenshot(
        self,
        *,
        region: str = "full",
        save_path: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("capture_screenshot", {"region": region, "save_path": save_path}))
        return {"action": "screenshot", "path": "/tmp/x.png", "width": 1920, "height": 1080}

    async def acapture_screenshot(
        self,
        *,
        region: str = "full",
        save_path: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("acapture_screenshot", {"region": region, "save_path": save_path}))
        return {"action": "screenshot", "path": "/tmp/x.png", "width": 1920, "height": 1080}

    def click(
        self,
        *,
        x: int,
        y: int,
        button: str = "left",
        click_type: str = "single",
    ) -> dict[str, Any]:
        self.calls.append(("click", {"x": x, "y": y, "button": button, "click_type": click_type}))
        return {"action": "click", "x": x, "y": y, "button": button, "click_type": click_type}

    async def aclick(
        self,
        *,
        x: int,
        y: int,
        button: str = "left",
        click_type: str = "single",
    ) -> dict[str, Any]:
        self.calls.append(("aclick", {"x": x, "y": y, "button": button, "click_type": click_type}))
        return {"action": "click", "x": x, "y": y, "button": button, "click_type": click_type}

    def keyboard(
        self,
        *,
        action_type: str,
        text: str = "",
        key: str = "",
        keys: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "keyboard",
                {
                    "action_type": action_type,
                    "text": text,
                    "key": key,
                    "keys": keys,
                },
            )
        )
        return {"action": action_type, "text": text, "key": key, "keys": keys}

    async def akeyboard(
        self,
        *,
        action_type: str,
        text: str = "",
        key: str = "",
        keys: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "akeyboard",
                {
                    "action_type": action_type,
                    "text": text,
                    "key": key,
                    "keys": keys,
                },
            )
        )
        return {"action": action_type, "text": text, "key": key, "keys": keys}

    def scroll(
        self,
        *,
        x: int = 0,
        y: int = 0,
        direction: str = "down",
        amount: int = 3,
    ) -> dict[str, Any]:
        self.calls.append(("scroll", {"x": x, "y": y, "direction": direction, "amount": amount}))
        return {"action": "scroll", "x": x, "y": y, "direction": direction, "amount": amount}

    async def ascroll(
        self,
        *,
        x: int = 0,
        y: int = 0,
        direction: str = "down",
        amount: int = 3,
    ) -> dict[str, Any]:
        self.calls.append(("ascroll", {"x": x, "y": y, "direction": direction, "amount": amount}))
        return {"action": "scroll", "x": x, "y": y, "direction": direction, "amount": amount}


@pytest.fixture
def backend() -> _RecordingBackend:
    """Fresh recording backend for each test."""
    return _RecordingBackend()


@pytest.fixture
def click_tool(backend: _RecordingBackend) -> ClickTool:
    """ClickTool wired to the recording backend."""
    return ClickTool(backend=backend)


@pytest.fixture
def keyboard_tool(backend: _RecordingBackend) -> KeyboardTool:
    """KeyboardTool wired to the recording backend."""
    return KeyboardTool(backend=backend)


# ─── ClickTool: sync path ─────────────────────────────────────────────────


class TestClickToolSync:
    """ClickTool._run delegates to backend.click with forwarded args."""

    def test_single_click_defaults(self, click_tool: ClickTool, backend: _RecordingBackend) -> None:
        result = click_tool._run(x=100, y=200)

        assert result == {
            "action": "click",
            "x": 100,
            "y": 200,
            "button": "left",
            "click_type": "single",
        }
        assert backend.calls == [
            ("click", {"x": 100, "y": 200, "button": "left", "click_type": "single"})
        ]

    def test_double_click_right_button(
        self, click_tool: ClickTool, backend: _RecordingBackend
    ) -> None:
        result = click_tool._run(x=5, y=5, button="right", click_type="double")

        assert result["button"] == "right"
        assert result["click_type"] == "double"
        assert backend.calls[0] == (
            "click",
            {"x": 5, "y": 5, "button": "right", "click_type": "double"},
        )

    def test_triple_click_middle_button(
        self, click_tool: ClickTool, backend: _RecordingBackend
    ) -> None:
        result = click_tool._run(x=0, y=0, button="middle", click_type="triple")

        assert result["button"] == "middle"
        assert result["click_type"] == "triple"

    def test_returns_backend_response_verbatim(
        self, click_tool: ClickTool, backend: _RecordingBackend
    ) -> None:
        """Tool must not mutate the backend's return dict."""
        backend.click = lambda **kw: {"custom": "marker"}  # type: ignore[assignment]
        result = click_tool._run(x=1, y=1)
        assert result == {"custom": "marker"}


# ─── ClickTool: async path ──────────────────────────────────────────────────


class TestClickToolAsync:
    """ClickTool._arun delegates to backend.aclick."""

    @pytest.mark.asyncio
    async def test_aclick_forwards_args(
        self, click_tool: ClickTool, backend: _RecordingBackend
    ) -> None:
        result = await click_tool._arun(x=300, y=400, button="right", click_type="double")

        assert result == {
            "action": "click",
            "x": 300,
            "y": 400,
            "button": "right",
            "click_type": "double",
        }
        assert backend.calls == [
            ("aclick", {"x": 300, "y": 400, "button": "right", "click_type": "double"})
        ]

    @pytest.mark.asyncio
    async def test_aclick_defaults(self, click_tool: ClickTool, backend: _RecordingBackend) -> None:
        await click_tool._arun(x=10, y=20)
        assert backend.calls[0][0] == "aclick"
        assert backend.calls[0][1]["button"] == "left"
        assert backend.calls[0][1]["click_type"] == "single"


# ─── KeyboardTool: sync path ──────────────────────────────────────────────


class TestKeyboardToolSync:
    """KeyboardTool._run routes action_type to backend.keyboard."""

    def test_type_text(self, keyboard_tool: KeyboardTool, backend: _RecordingBackend) -> None:
        result = keyboard_tool._run(action_type="type", text="hello world")

        assert result == {"action": "type", "text": "hello world", "key": "", "keys": ""}
        assert backend.calls == [
            (
                "keyboard",
                {"action_type": "type", "text": "hello world", "key": "", "keys": ""},
            )
        ]

    def test_press_key(self, keyboard_tool: KeyboardTool, backend: _RecordingBackend) -> None:
        result = keyboard_tool._run(action_type="key", key="enter")

        assert result["action"] == "key"
        assert result["key"] == "enter"
        assert backend.calls[0][1]["action_type"] == "key"
        assert backend.calls[0][1]["key"] == "enter"

    def test_hotkey(self, keyboard_tool: KeyboardTool, backend: _RecordingBackend) -> None:
        result = keyboard_tool._run(action_type="hotkey", keys="ctrl,shift,esc")

        assert result["action"] == "hotkey"
        assert result["keys"] == "ctrl,shift,esc"
        assert backend.calls[0][1]["action_type"] == "hotkey"
        assert backend.calls[0][1]["keys"] == "ctrl,shift,esc"

    def test_empty_text_defaults(
        self, keyboard_tool: KeyboardTool, backend: _RecordingBackend
    ) -> None:
        """action_type required; text/key/keys default to empty string."""
        result = keyboard_tool._run(action_type="type")
        assert result["text"] == ""

        result = keyboard_tool._run(action_type="key")
        assert result["key"] == ""


# ─── KeyboardTool: async path ──────────────────────────────────────────────


class TestKeyboardToolAsync:
    """KeyboardTool._arun routes to backend.akeyboard."""

    @pytest.mark.asyncio
    async def test_atype_text(
        self, keyboard_tool: KeyboardTool, backend: _RecordingBackend
    ) -> None:
        result = await keyboard_tool._arun(action_type="type", text="abc")

        assert result["action"] == "type"
        assert result["text"] == "abc"
        assert backend.calls[0][0] == "akeyboard"

    @pytest.mark.asyncio
    async def test_akey(self, keyboard_tool: KeyboardTool, backend: _RecordingBackend) -> None:
        result = await keyboard_tool._arun(action_type="key", key="tab")
        assert result["key"] == "tab"
        assert backend.calls[0] == (
            "akeyboard",
            {"action_type": "key", "text": "", "key": "tab", "keys": ""},
        )

    @pytest.mark.asyncio
    async def test_ahotkey(self, keyboard_tool: KeyboardTool, backend: _RecordingBackend) -> None:
        result = await keyboard_tool._arun(action_type="hotkey", keys="cmd,space")
        assert result["keys"] == "cmd,space"
        assert backend.calls[0][1]["action_type"] == "hotkey"


# ─── _execute_step: agent-loop dispatcher ──────────────────────────────────


def _make_action(**kwargs: Any) -> _ComputerAction:
    """Build a _ComputerAction with sensible defaults for click/type tests."""
    defaults: dict[str, Any] = {
        "action_type": "click",
        "x": 0,
        "y": 0,
        "button": "left",
        "click_type": "single",
        "text": "",
        "key": "",
        "keys": "",
        "direction": "down",
        "amount": 3,
        "reason": "",
    }
    defaults.update(kwargs)
    return _ComputerAction(**defaults)


class TestExecuteStepClickAndType:
    """_execute_step routes action_type to the correct backend method."""

    @pytest.mark.asyncio
    async def test_click_routes_to_aclick(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="click", x=42, y=99)
        result = await _execute_step(action=action, backend=backend)

        assert result["action"] == "click"
        assert result["x"] == 42
        assert result["y"] == 99
        assert backend.calls[0][0] == "aclick"
        assert backend.calls[0][1]["x"] == 42
        assert backend.calls[0][1]["y"] == 99

    @pytest.mark.asyncio
    async def test_double_click_forces_click_type_double(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="double_click", x=10, y=10, click_type="single")
        result = await _execute_step(action=action, backend=backend)

        assert result["click_type"] == "double"
        assert backend.calls[0][1]["click_type"] == "double"

    @pytest.mark.asyncio
    async def test_right_click_forces_button_right(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="right_click", x=1, y=2, button="left")
        result = await _execute_step(action=action, backend=backend)

        assert result["button"] == "right"
        assert backend.calls[0][1]["button"] == "right"

    @pytest.mark.asyncio
    async def test_type_routes_to_akeyboard(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="type", text="typed text")
        result = await _execute_step(action=action, backend=backend)

        assert result["action"] == "type"
        assert result["text"] == "typed text"
        assert backend.calls[0][0] == "akeyboard"
        assert backend.calls[0][1]["action_type"] == "type"
        assert backend.calls[0][1]["text"] == "typed text"

    @pytest.mark.asyncio
    async def test_key_routes_to_akeyboard(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="key", key="escape")
        result = await _execute_step(action=action, backend=backend)

        assert result["key"] == "escape"
        assert backend.calls[0][1]["action_type"] == "key"

    @pytest.mark.asyncio
    async def test_hotkey_routes_to_akeyboard(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="hotkey", keys="ctrl,c")
        result = await _execute_step(action=action, backend=backend)

        assert result["keys"] == "ctrl,c"
        assert backend.calls[0][1]["action_type"] == "hotkey"

    @pytest.mark.asyncio
    async def test_done_returns_reason(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="done", reason="task complete")
        result = await _execute_step(action=action, backend=backend)

        assert result == {"action": "done", "reason": "task complete"}
        assert backend.calls == []  # no backend interaction for done

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, backend: _RecordingBackend) -> None:
        action = _make_action(action_type="nonexistent")
        result = await _execute_step(action=action, backend=backend)

        assert "error" in result
        assert "nonexistent" in result["error"]


# ─── ComputerUseToolkit: backend injection wiring ──────────────────────────


class TestToolkitWiring:
    """ComputerUseToolkit.get_tools() injects the backend into each tool."""

    def test_get_tools_returns_four_tools(self, backend: _RecordingBackend) -> None:
        toolkit = ComputerUseToolkit(backend=backend)
        tools = toolkit.get_tools()

        assert len(tools) == 4
        names = {t.name for t in tools}
        assert "computer_screenshot" in names
        assert "computer_click" in names
        assert "computer_keyboard" in names
        assert "computer_scroll" in names

    def test_click_tool_receives_backend(self, backend: _RecordingBackend) -> None:
        toolkit = ComputerUseToolkit(backend=backend)
        tools = toolkit.get_tools()
        click_tool = next(t for t in tools if t.name == "computer_click")

        assert click_tool.backend is backend
        result = click_tool._run(x=7, y=8)
        assert result["x"] == 7
        assert result["y"] == 8

    def test_keyboard_tool_receives_backend(self, backend: _RecordingBackend) -> None:
        toolkit = ComputerUseToolkit(backend=backend)
        tools = toolkit.get_tools()
        keyboard_tool = next(t for t in tools if t.name == "computer_keyboard")

        assert keyboard_tool.backend is backend
        result = keyboard_tool._run(action_type="type", text="wired")
        assert result["text"] == "wired"

    def test_none_backend_yields_tools_without_backend(self, backend: _RecordingBackend) -> None:
        """When backend is None, tools are returned but report no backend."""
        toolkit = ComputerUseToolkit(backend=None)
        tools = toolkit.get_tools()

        assert len(tools) == 4
        for tool in tools:
            assert tool.backend is None


# ─── Error path: backend is None ──────────────────────────────────────────


class TestNoBackendErrorPath:
    """Tools return error dict when backend is None."""

    def test_click_no_backend(self) -> None:
        tool = ClickTool(backend=None)
        result = tool._run(x=1, y=1)
        assert result == {"error": "No input backend configured"}

    def test_keyboard_no_backend(self) -> None:
        tool = KeyboardTool(backend=None)
        result = tool._run(action_type="type", text="x")
        assert result == {"error": "No input backend configured"}

    @pytest.mark.asyncio
    async def test_aclick_no_backend(self) -> None:
        tool = ClickTool(backend=None)
        result = await tool._arun(x=1, y=1)
        assert result == {"error": "No input backend configured"}

    @pytest.mark.asyncio
    async def test_akeyboard_no_backend(self) -> None:
        tool = KeyboardTool(backend=None)
        result = await tool._arun(action_type="key", key="enter")
        assert result == {"error": "No input backend configured"}


# ─── Schema validation ────────────────────────────────────────────────────


class TestSchemaValidation:
    """Pydantic input schemas enforce required fields and bounds."""

    def test_click_input_requires_x(self) -> None:
        with pytest.raises(ValueError, match="x"):
            ClickInput(y=10)  # type: ignore[call-arg]

    def test_click_input_requires_y(self) -> None:
        with pytest.raises(ValueError, match="y"):
            ClickInput(x=10)  # type: ignore[call-arg]

    def test_click_input_x_must_be_nonnegative(self) -> None:
        with pytest.raises(ValueError):
            ClickInput(x=-1, y=0)

    def test_click_input_y_must_be_nonnegative(self) -> None:
        with pytest.raises(ValueError):
            ClickInput(x=0, y=-1)

    def test_click_input_defaults(self) -> None:
        ci = ClickInput(x=100, y=200)
        assert ci.button == "left"
        assert ci.click_type == "single"

    def test_keyboard_input_requires_action_type(self) -> None:
        with pytest.raises(ValueError, match="action_type"):
            KeyboardInput()  # type: ignore[call-arg]

    def test_keyboard_input_defaults(self) -> None:
        ki = KeyboardInput(action_type="type")
        assert ki.text == ""
        assert ki.key == ""
        assert ki.keys == ""


# ─── Config integration ────────────────────────────────────────────────────


class TestConfigBackendDefault:
    """ComputerUseSubagentConfig.backend defaults to pyautogui."""

    def test_backend_defaults_to_pyautogui(self) -> None:
        config = ComputerUseSubagentConfig()
        assert config.backend == "pyautogui"

    def test_backend_overridable(self) -> None:
        config = ComputerUseSubagentConfig(backend="auto")
        assert config.backend == "auto"


# ─── _PyAutoGUIBackend: click/type method contracts (no live pyautogui) ───


class TestPyAutoGUIBackendMethodShapes:
    """Verify _PyAutoGUIBackend.click/keyboard return contracts.

    These tests patch ``_ensure_pagu`` so no real pyautogui import happens,
    exercising only the method logic that maps args → pyautogui calls and
    builds the response dict.
    """

    def test_click_builds_response(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        mock_pag = MagicMock()
        backend._pyautogui = mock_pag

        result = backend.click(x=50, y=60, button="right", click_type="double")

        mock_pag.click.assert_called_once_with(x=50, y=60, button="right", clicks=2)
        assert result == {
            "action": "click",
            "x": 50,
            "y": 60,
            "scale": 1,
            "input_x": 50,
            "input_y": 60,
            "button": "right",
            "click_type": "double",
        }

    def test_click_single_defaults_to_one_click(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        mock_pag = MagicMock()
        backend._pyautogui = mock_pag

        backend.click(x=1, y=1)
        mock_pag.click.assert_called_once_with(x=1, y=1, button="left", clicks=1)

    def test_click_triple_maps_to_three(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        mock_pag = MagicMock()
        backend._pyautogui = mock_pag

        backend.click(x=0, y=0, click_type="triple")
        assert mock_pag.click.call_args.kwargs["clicks"] == 3

    def test_keyboard_type_calls_typewrite(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        mock_pag = MagicMock()
        backend._pyautogui = mock_pag

        result = backend.keyboard(action_type="type", text="hello")

        mock_pag.typewrite.assert_called_once_with("hello")
        assert result == {"action": "type", "text": "hello"}

    def test_keyboard_key_calls_press(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        mock_pag = MagicMock()
        backend._pyautogui = mock_pag

        result = backend.keyboard(action_type="key", key="enter")

        mock_pag.press.assert_called_once_with("enter")
        assert result == {"action": "key", "key": "enter"}

    def test_keyboard_hotkey_splits_commas(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        mock_pag = MagicMock()
        backend._pyautogui = mock_pag

        result = backend.keyboard(action_type="hotkey", keys="ctrl, shift ,esc")

        mock_pag.hotkey.assert_called_once_with("ctrl", "shift", "esc")
        assert result == {"action": "hotkey", "keys": "ctrl, shift ,esc"}

    def test_keyboard_unknown_action_returns_error(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        mock_pag = MagicMock()
        backend._pyautogui = mock_pag

        result = backend.keyboard(action_type="bogus", text="x")

        assert "error" in result
        assert "bogus" in result["error"]
        mock_pag.typewrite.assert_not_called()
        mock_pag.press.assert_not_called()
        mock_pag.hotkey.assert_not_called()
