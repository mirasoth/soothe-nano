"""Unit tests for the vision-driven computer_use decision loop.

The agent loop previously sent the LLM a text-only trajectory, so a vision
model could never see the desktop and would request screenshots forever
without acting. These tests pin the behaviour that fixes that:

- screenshots are inlined into the prompt as ``image_url`` data URIs
- unreadable / unsupported / oversized captures degrade to a text prompt
- repeated observe-only actions trigger an explicit "act now" nudge
- a screenshot-only run is reported as no-progress
- ``coordinate_scale`` is corrected from the first full-screen capture
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from soothe_nano.subagents.computer_use.implementation import (
    _MAX_SCREENSHOT_IMAGE_BYTES,
    DesktopInputUnavailableError,
    _capture_observation,
    _computer_history_had_no_progress,
    _ComputerAction,
    _decide_next_action,
    _execute_step,
    _PyAutoGUIBackend,
    _screenshot_data_url,
    _StepHistory,
)
from soothe_nano.subagents.computer_use.tools import _DesktopInputBackend

# ─── Helpers ──────────────────────────────────────────────────────────────


def _write_png(path: Any, size: tuple[int, int] = (4, 4)) -> str:
    """Write a tiny valid PNG and return its path."""
    from PIL import Image  # type: ignore

    Image.new("RGB", size, (1, 2, 3)).save(path, format="PNG")
    return str(path)


def _history_with(*action_types: str) -> _StepHistory:
    history = _StepHistory()
    for idx, action_type in enumerate(action_types, start=1):
        history.add(
            step=idx,
            action=_ComputerAction(action_type=action_type),
            result={"action": action_type},
        )
    return history


class _CapturingLLM:
    """Stand-in chat model; the structured call is patched, not this."""


@pytest.fixture
def captured_messages(monkeypatch: pytest.MonkeyPatch) -> list[list[Any]]:
    """Patch structured invocation and record the messages it receives."""
    seen: list[list[Any]] = []

    async def fake_invoke(chat: Any, messages: list[Any], schema: Any, **kwargs: Any) -> Any:
        seen.append(messages)
        return _ComputerAction(action_type="click", x=1, y=2)

    monkeypatch.setattr(
        "soothe_nano.llm.structured.invoke_structured_chat_typed",
        fake_invoke,
    )
    return seen


def _human_content(messages: list[Any]) -> Any:
    return next(m for m in messages if isinstance(m, HumanMessage)).content


def _prompt_text(messages: list[Any]) -> str:
    content = _human_content(messages)
    if isinstance(content, str):
        return content
    return "\n".join(block["text"] for block in content if block.get("type") == "text")


# ─── Screenshot encoding ──────────────────────────────────────────────────


class TestScreenshotDataUrl:
    def test_encodes_png_as_data_uri(self, tmp_path: Any) -> None:
        path = _write_png(tmp_path / "shot.png")
        url = _screenshot_data_url(path)

        assert url is not None
        assert url.startswith("data:image/png;base64,")

    def test_encodes_jpeg_mime_for_jpg_suffix(self, tmp_path: Any) -> None:
        from PIL import Image  # type: ignore

        path = tmp_path / "shot.jpg"
        Image.new("RGB", (4, 4), (0, 0, 0)).save(path, format="JPEG")

        url = _screenshot_data_url(str(path))
        assert url is not None
        assert url.startswith("data:image/jpeg;base64,")

    def test_none_path_returns_none(self) -> None:
        assert _screenshot_data_url(None) is None
        assert _screenshot_data_url("") is None

    def test_missing_file_returns_none(self, tmp_path: Any) -> None:
        assert _screenshot_data_url(str(tmp_path / "absent.png")) is None

    def test_unsupported_suffix_returns_none(self, tmp_path: Any) -> None:
        path = tmp_path / "shot.tiff"
        path.write_bytes(b"not-an-image")
        assert _screenshot_data_url(str(path)) is None

    def test_oversized_file_returns_none(self, tmp_path: Any, monkeypatch: Any) -> None:
        path = _write_png(tmp_path / "big.png")
        monkeypatch.setattr(
            "soothe_nano.subagents.computer_use.implementation._MAX_SCREENSHOT_IMAGE_BYTES",
            1,
        )
        assert _screenshot_data_url(path) is None

    def test_default_ceiling_is_twenty_mib(self) -> None:
        assert _MAX_SCREENSHOT_IMAGE_BYTES == 20 * 1024 * 1024


# ─── Decision prompt construction ─────────────────────────────────────────


class TestDecideNextActionVision:
    @pytest.mark.asyncio
    async def test_attaches_screenshot_as_image_block(
        self, tmp_path: Any, captured_messages: list[list[Any]]
    ) -> None:
        path = _write_png(tmp_path / "shot.png")

        action = await _decide_next_action(
            llm=_CapturingLLM(),
            task="click the button",
            history=_StepHistory(),
            max_steps=10,
            screenshot_path=path,
            screen_size=(2560, 1600),
        )

        assert action.action_type == "click"
        content = _human_content(captured_messages[0])
        assert isinstance(content, list)
        image_blocks = [b for b in content if b.get("type") == "image_url"]
        assert len(image_blocks) == 1
        assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_includes_screen_dimensions_in_prompt(
        self, tmp_path: Any, captured_messages: list[list[Any]]
    ) -> None:
        path = _write_png(tmp_path / "shot.png")

        await _decide_next_action(
            llm=_CapturingLLM(),
            task="t",
            history=_StepHistory(),
            max_steps=10,
            screenshot_path=path,
            screen_size=(2560, 1600),
        )

        assert "2560x1600" in _prompt_text(captured_messages[0])

    @pytest.mark.asyncio
    async def test_falls_back_to_text_prompt_without_screenshot(
        self, captured_messages: list[list[Any]]
    ) -> None:
        await _decide_next_action(
            llm=_CapturingLLM(),
            task="t",
            history=_StepHistory(),
            max_steps=10,
            screenshot_path=None,
        )

        content = _human_content(captured_messages[0])
        assert isinstance(content, str)
        assert "Task: t" in content

    @pytest.mark.asyncio
    async def test_unreadable_screenshot_degrades_to_text(
        self, tmp_path: Any, captured_messages: list[list[Any]]
    ) -> None:
        await _decide_next_action(
            llm=_CapturingLLM(),
            task="t",
            history=_StepHistory(),
            max_steps=10,
            screenshot_path=str(tmp_path / "missing.png"),
        )

        assert isinstance(_human_content(captured_messages[0]), str)

    @pytest.mark.asyncio
    async def test_nudges_after_repeated_observations(
        self, tmp_path: Any, captured_messages: list[list[Any]]
    ) -> None:
        path = _write_png(tmp_path / "shot.png")

        await _decide_next_action(
            llm=_CapturingLLM(),
            task="t",
            history=_history_with("screenshot", "screenshot"),
            max_steps=10,
            screenshot_path=path,
            consecutive_observations=2,
        )

        assert "take a concrete action" in _prompt_text(captured_messages[0])

    @pytest.mark.asyncio
    async def test_no_nudge_before_threshold(
        self, tmp_path: Any, captured_messages: list[list[Any]]
    ) -> None:
        path = _write_png(tmp_path / "shot.png")

        await _decide_next_action(
            llm=_CapturingLLM(),
            task="t",
            history=_history_with("screenshot"),
            max_steps=10,
            screenshot_path=path,
            consecutive_observations=1,
        )

        assert "take a concrete action" not in _prompt_text(captured_messages[0])

    @pytest.mark.asyncio
    async def test_decision_failure_returns_done(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("provider down")

        monkeypatch.setattr(
            "soothe_nano.llm.structured.invoke_structured_chat_typed",
            boom,
        )

        action = await _decide_next_action(
            llm=_CapturingLLM(),
            task="t",
            history=_StepHistory(),
            max_steps=5,
        )

        assert action.action_type == "done"
        assert "provider down" in action.reason


# ─── Observation capture ──────────────────────────────────────────────────


class _ObservingBackend(_DesktopInputBackend):
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self._result = result
        self.captures = 0

    async def acapture_screenshot(
        self, *, region: str = "full", save_path: str | None = None
    ) -> dict[str, Any]:
        self.captures += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class TestCaptureObservation:
    @pytest.mark.asyncio
    async def test_returns_capture_metadata(self) -> None:
        backend = _ObservingBackend({"action": "screenshot", "path": "/tmp/a.png", "width": 100})

        result = await _capture_observation(backend=backend)

        assert result is not None
        assert result["path"] == "/tmp/a.png"
        assert backend.captures == 1

    @pytest.mark.asyncio
    async def test_capture_failure_returns_none(self) -> None:
        backend = _ObservingBackend(RuntimeError("no display"))
        assert await _capture_observation(backend=backend) is None

    @pytest.mark.asyncio
    async def test_pathless_result_returns_none(self) -> None:
        backend = _ObservingBackend({"error": "No input backend configured"})
        assert await _capture_observation(backend=backend) is None

    @pytest.mark.asyncio
    async def test_delay_is_awaited_before_capture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)
        backend = _ObservingBackend({"path": "/tmp/a.png"})

        await _capture_observation(backend=backend, delay_s=0.8)

        assert slept == [0.8]


# ─── No-progress detection ────────────────────────────────────────────────


class TestNoProgressDetection:
    def test_screenshot_only_run_is_no_progress(self) -> None:
        assert _computer_history_had_no_progress(_history_with("screenshot", "screenshot")) is True

    def test_mixed_observe_only_run_is_no_progress(self) -> None:
        assert _computer_history_had_no_progress(_history_with("screenshot", "wait")) is True

    def test_click_counts_as_progress(self) -> None:
        assert _computer_history_had_no_progress(_history_with("screenshot", "click")) is False

    def test_empty_history_is_no_progress(self) -> None:
        assert _computer_history_had_no_progress(_StepHistory()) is True


# ─── Coordinate scale probe ───────────────────────────────────────────────


class TestCoordinateScaleProbe:
    def test_detects_retina_scale_from_capture_width(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp", coordinate_scale=1)
        pag = MagicMock()
        pag.size.return_value = (1512, 982)
        backend._pyautogui = pag

        backend._probe_coordinate_scale(3024)

        assert backend._coordinate_scale == 2
        assert backend._rescale_coord(200) == 100

    def test_leaves_matching_scale_untouched(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp", coordinate_scale=2)
        pag = MagicMock()
        pag.size.return_value = (1512, 982)
        backend._pyautogui = pag

        backend._probe_coordinate_scale(3024)

        assert backend._coordinate_scale == 2

    def test_corrects_overstated_scale_on_non_hidpi_display(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp", coordinate_scale=2)
        pag = MagicMock()
        pag.size.return_value = (1920, 1080)
        backend._pyautogui = pag

        backend._probe_coordinate_scale(1920)

        assert backend._coordinate_scale == 1

    def test_probes_only_once(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp", coordinate_scale=1)
        pag = MagicMock()
        pag.size.return_value = (1512, 982)
        backend._pyautogui = pag

        backend._probe_coordinate_scale(3024)
        backend._probe_coordinate_scale(1512)

        assert backend._coordinate_scale == 2
        assert pag.size.call_count == 1

    def test_probe_failure_leaves_scale_unchanged(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp", coordinate_scale=2)
        pag = MagicMock()
        pag.size.side_effect = RuntimeError("no display")
        backend._pyautogui = pag

        backend._probe_coordinate_scale(3024)

        assert backend._coordinate_scale == 2

    def test_zero_width_capture_is_ignored(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp", coordinate_scale=1)
        pag = MagicMock()
        backend._pyautogui = pag

        backend._probe_coordinate_scale(0)

        assert backend._coordinate_scale == 1
        pag.size.assert_not_called()


# ─── Missing pyautogui ────────────────────────────────────────────────────


def _hide_pyautogui(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import pyautogui`` fail the way an unprovisioned interpreter does."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pyautogui":
            raise ModuleNotFoundError("No module named 'pyautogui'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class TestMissingPyAutoGUI:
    """Screenshots can work via screencapture while input is unavailable, so the
    missing dependency must surface as an actionable error, not a crash."""

    def test_ensure_pagu_raises_actionable_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        _hide_pyautogui(monkeypatch)

        with pytest.raises(DesktopInputUnavailableError, match="pip install pyautogui"):
            backend._ensure_pagu()

    def test_input_available_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        _hide_pyautogui(monkeypatch)

        assert backend.input_available() is False

    def test_input_available_is_true_when_importable(self) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        backend._pyautogui = MagicMock()

        assert backend.input_available() is True

    @pytest.mark.asyncio
    async def test_click_returns_error_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _PyAutoGUIBackend(screenshots_dir="/tmp")
        _hide_pyautogui(monkeypatch)

        result = await _execute_step(
            action=_ComputerAction(action_type="click", x=5, y=5),
            backend=backend,
        )

        assert result["action"] == "click"
        assert "pip install pyautogui" in result["error"]

    @pytest.mark.asyncio
    async def test_backend_exception_becomes_step_error(self) -> None:
        class _Exploding(_DesktopInputBackend):
            async def aclick(self, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("mouse is on fire")

        result = await _execute_step(
            action=_ComputerAction(action_type="click", x=1, y=1),
            backend=_Exploding(),
        )

        assert "mouse is on fire" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_action_is_unwrapped(self) -> None:
        backend = _ObservingBackend({"action": "screenshot", "path": "/tmp/a.png"})

        result = await _execute_step(
            action=_ComputerAction(action_type="screenshot"),
            backend=backend,
        )

        assert result == {"action": "screenshot", "path": "/tmp/a.png"}
        assert "error" not in result
