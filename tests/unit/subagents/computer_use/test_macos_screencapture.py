"""Unit tests for macOS-native screenshot fallback and permission probes.

Covers the LYZ-03 deliverable:

- ``_PyAutoGUIBackend`` honors ``screenshot_source`` config:
  * ``screencapture`` → routes to the macOS CLI on Darwin
  * ``pyautogui`` → routes to pyautogui even on Darwin
  * ``auto`` → ``screencapture`` on Darwin, pyautogui elsewhere
- screencapture failure falls back to pyautogui (``screenshot_fallback`` log)
- ``screenshot_format``/``screenshot_quality`` are honored (PNG default, JPEG
  re-encode path)
- macOS permission probes return the documented shape on non-Darwin and are
  import-safe on every platform
- plugin ``on_load`` softens on macOS when pyautogui is absent (warn instead of
  raising) so screenshot-only flows still load

The screencapture CLI is never actually invoked: ``shutil.which`` and
``subprocess.run`` are patched so the test is deterministic and hermetic.
"""

from __future__ import annotations

import os
import types
from typing import Any
from unittest.mock import patch

import pytest

from soothe_nano.subagents.computer_use.config_model import (
    ComputerUseSubagentConfig,
)
from soothe_nano.subagents.computer_use.implementation import (
    _check_macos_accessibility_permission,
    _check_macos_screen_recording_permission,
    _PyAutoGUIBackend,
)

# ─── Config model ─────────────────────────────────────────────────────────


class TestScreenshotSourceConfig:
    def test_default_screenshot_source_is_auto(self) -> None:
        cfg = ComputerUseSubagentConfig()
        assert cfg.screenshot_source == "auto"

    def test_screenshot_source_accepts_all_three_values(self) -> None:
        for val in ("auto", "pyautogui", "screencapture"):
            cfg = ComputerUseSubagentConfig(screenshot_source=val)
            assert cfg.screenshot_source == val

    def test_screenshot_source_rejects_unknown(self) -> None:
        with pytest.raises(Exception):
            ComputerUseSubagentConfig(screenshot_source="mss")

    def test_screenshot_format_and_quality_defaults(self) -> None:
        cfg = ComputerUseSubagentConfig()
        assert cfg.screenshot_format == "png"
        assert cfg.screenshot_quality == 85


# ─── Backend screenshot_source routing ───────────────────────────────────


class _FakePyAutoGUIBackend(_PyAutoGUIBackend):
    """Test double that records which capture path was used.

    We subclass and stub ``_ensure_pagu`` / ``_capture_via_screencapture`` /
    ``_capture_via_pyautogui`` so no real CLI or pyautogui import is needed.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(screenshots_dir="/tmp/soothe-tests", **kwargs)
        self.screencapture_calls: list[dict[str, Any]] = []
        self.pyautogui_calls: list[dict[str, Any]] = []

    # Override _is_darwin so tests are deterministic regardless of host.
    def _is_darwin(self) -> bool:  # type: ignore[override]
        return self._test_is_darwin  # type: ignore[attr-defined]

    def _capture_via_screencapture(
        self, *, region: str, save_path: str | None
    ) -> dict[str, Any] | None:
        self.screencapture_calls.append({"region": region, "save_path": save_path})
        return {
            "action": "screenshot",
            "path": "/tmp/sc.png",
            "width": 2,
            "height": 2,
            "source": "screencapture",
        }

    def _capture_via_pyautogui(self, *, region: str, save_path: str | None) -> dict[str, Any]:
        self.pyautogui_calls.append({"region": region, "save_path": save_path})
        return {
            "action": "screenshot",
            "path": "/tmp/pag.png",
            "width": 3,
            "height": 3,
            "source": "pyautogui",
        }


def _make_backend(
    *,
    screenshot_source: str = "auto",
    screenshot_format: str = "png",
    is_darwin: bool = True,
) -> _FakePyAutoGUIBackend:
    b = _FakePyAutoGUIBackend(
        coordinate_scale=2,
        screenshot_source=screenshot_source,
        screenshot_format=screenshot_format,
    )
    b._test_is_darwin = is_darwin  # type: ignore[attr-defined]
    return b


class TestScreenshotSourceRouting:
    def test_auto_on_darwin_uses_screencapture(self) -> None:
        b = _make_backend(screenshot_source="auto", is_darwin=True)
        result = b.capture_screenshot()
        assert result["source"] == "screencapture"
        assert b.screencapture_calls and not b.pyautogui_calls

    def test_auto_on_non_darwin_uses_pyautogui(self) -> None:
        b = _make_backend(screenshot_source="auto", is_darwin=False)
        result = b.capture_screenshot()
        assert result["source"] == "pyautogui"
        assert b.pyautogui_calls and not b.screencapture_calls

    def test_pyautogui_source_bypasses_screencapture_even_on_darwin(self) -> None:
        b = _make_backend(screenshot_source="pyautogui", is_darwin=True)
        result = b.capture_screenshot()
        assert result["source"] == "pyautogui"
        assert b.pyautogui_calls and not b.screencapture_calls

    def test_screencapture_source_on_non_darwin_falls_to_pyautogui(self) -> None:
        # screencapture source is Darwin-only; on Linux it must fall back.
        b = _make_backend(screenshot_source="screencapture", is_darwin=False)
        result = b.capture_screenshot()
        assert result["source"] == "pyautogui"

    def test_region_is_forwarded(self) -> None:
        b = _make_backend(screenshot_source="auto", is_darwin=True)
        b.capture_screenshot(region="10,20,100,200")
        assert b.screencapture_calls[0]["region"] == "10,20,100,200"


# ─── screencapture fallback on CLI failure ───────────────────────────────


class TestScreencaptureFallback:
    def test_screencapture_none_falls_back_to_pyautogui(self) -> None:
        b = _make_backend(screenshot_source="auto", is_darwin=True)

        # screencapture returns None (CLI missing / failed) → pyautogui path
        b._capture_via_screencapture = lambda *, region, save_path: None  # type: ignore[assignment]
        result = b.capture_screenshot()
        assert result["source"] == "pyautogui"
        assert b.pyautogui_calls


# ─── Permission probes ───────────────────────────────────────────────────


class TestPermissionProbes:
    def test_accessibility_probe_returns_documented_keys(self) -> None:
        result = _check_macos_accessibility_permission()
        assert set(result.keys()) >= {
            "platform",
            "supported",
            "accessibility_granted",
            "detail",
        }
        # On non-Darwin the probe short-circuits to granted=True.
        if result["platform"] != "darwin":
            assert result["supported"] is False
            assert result["accessibility_granted"] is True

    def test_screen_recording_probe_returns_documented_keys(self) -> None:
        result = _check_macos_screen_recording_permission()
        assert set(result.keys()) >= {
            "platform",
            "supported",
            "screen_recording_granted",
            "detail",
        }
        if result["platform"] != "darwin":
            assert result["supported"] is False
            assert result["screen_recording_granted"] is True

    def test_probes_never_raise_on_non_darwin(self) -> None:
        # Ensure calling the probes is safe on any host.
        a = _check_macos_accessibility_permission()
        s = _check_macos_screen_recording_permission()
        assert isinstance(a["accessibility_granted"], bool)
        assert isinstance(s["screen_recording_granted"], bool)

    @patch("platform.system", return_value="darwin")
    @patch("ctypes.CDLL", side_effect=OSError("no ctypes"))
    def test_accessibility_probe_probe_unavailable_when_ctypes_fails(
        self, _cdll: Any, _system: Any
    ) -> None:
        result = _check_macos_accessibility_permission()
        assert result["platform"] == "darwin"
        assert result["supported"] is True
        assert result["accessibility_granted"] is False
        assert result["detail"] == "probe_unavailable"


# ─── Real screencapture path (mocked subprocess) ─────────────────────────


class TestRealScreencapturePath:
    """Exercise the real ``_capture_via_screencapture`` with mocked subprocess."""

    def test_screencapture_missing_returns_none(self, tmp_path: Any) -> None:
        b = _PyAutoGUIBackend(
            screenshots_dir=str(tmp_path),
            screenshot_source="screencapture",
        )
        # Force Darwin + no screencapture binary available.
        with (
            patch.object(b, "_is_darwin", return_value=True),
            patch("shutil.which", return_value=None),
        ):
            result = b._capture_via_screencapture(region="full", save_path=None)
        assert result is None

    def test_screencapture_failure_returns_none(self, tmp_path: Any) -> None:
        b = _PyAutoGUIBackend(
            screenshots_dir=str(tmp_path),
            screenshot_source="screencapture",
        )
        fake_proc = types.SimpleNamespace(returncode=1, stdout="", stderr="")

        def fake_run(*args: Any, **kwargs: Any) -> Any:
            return fake_proc

        with (
            patch.object(b, "_is_darwin", return_value=True),
            patch("shutil.which", return_value="/usr/sbin/screencapture"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = b._capture_via_screencapture(region="full", save_path=None)
        assert result is None

    def test_screencapture_success_returns_metadata(self, tmp_path: Any) -> None:
        b = _PyAutoGUIBackend(
            screenshots_dir=str(tmp_path),
            screenshot_source="screencapture",
        )

        def fake_run(cmd: Any, **kwargs: Any) -> Any:
            # Write a tiny valid PNG to the target path.
            target = cmd[-1]
            from PIL import Image  # type: ignore

            Image.new("RGB", (4, 4), (0, 0, 0)).save(target, format="PNG")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch.object(b, "_is_darwin", return_value=True),
            patch("shutil.which", return_value="/usr/sbin/screencapture"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = b._capture_via_screencapture(region="full", save_path=None)
        assert result is not None
        assert result["source"] == "screencapture"
        assert result["width"] == 4
        assert result["height"] == 4
        assert os.path.exists(result["path"])

    def test_jpeg_reencode_path(self, tmp_path: Any) -> None:
        b = _PyAutoGUIBackend(
            screenshots_dir=str(tmp_path),
            screenshot_source="screencapture",
            screenshot_format="jpeg",
            screenshot_quality=60,
        )

        def fake_run(cmd: Any, **kwargs: Any) -> Any:
            target = cmd[-1]
            from PIL import Image  # type: ignore

            # screencapture writes to temp PNG; final path is JPEG.
            Image.new("RGB", (8, 8), (10, 20, 30)).save(target, format="PNG")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch.object(b, "_is_darwin", return_value=True),
            patch("shutil.which", return_value="/usr/sbin/screencapture"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = b._capture_via_screencapture(region="full", save_path=None)
        assert result is not None
        assert result["path"].endswith(".jpeg")
        assert os.path.exists(result["path"])
        # Verify it's actually a JPEG.
        from PIL import Image  # type: ignore

        with Image.open(result["path"]) as img:
            assert img.format == "JPEG"
            assert img.size == (8, 8)


# ─── Plugin on_load soft-fail ─────────────────────────────────────────────


class TestPluginOnLoadSoftFail:
    """On macOS, missing pyautogui should warn — not raise."""

    @pytest.mark.asyncio
    async def test_macos_missing_pyautogui_warns_not_raises(self) -> None:
        from soothe_nano.subagents.computer_use import ComputerUsePlugin

        plugin = ComputerUsePlugin()

        class _Ctx:
            def __init__(self) -> None:
                self.logger = types.SimpleNamespace(
                    info=lambda *a, **k: None,
                    warning=lambda *a, **k: None,
                )

        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "pyautogui":
                raise ImportError("no pyautogui")
            return real_import(name, *args, **kwargs)

        with (
            patch("platform.system", return_value="Darwin"),
            patch("builtins.__import__", side_effect=fake_import),
        ):
            # Should NOT raise on macOS.
            await plugin.on_load(_Ctx())

    @pytest.mark.asyncio
    async def test_non_macos_missing_pyautogui_raises(self) -> None:
        from soothe_sdk.core.exceptions import PluginError

        from soothe_nano.subagents.computer_use import ComputerUsePlugin

        plugin = ComputerUsePlugin()

        class _Ctx:
            def __init__(self) -> None:
                self.logger = types.SimpleNamespace(
                    info=lambda *a, **k: None,
                    warning=lambda *a, **k: None,
                )

        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "pyautogui":
                raise ImportError("no pyautogui")
            return real_import(name, *args, **kwargs)

        with (
            patch("platform.system", return_value="Linux"),
            patch("builtins.__import__", side_effect=fake_import),
        ):
            with pytest.raises(PluginError):
                await plugin.on_load(_Ctx())
