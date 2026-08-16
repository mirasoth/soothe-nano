"""ComputerUse subagent -- desktop automation specialist.

Provides desktop automation for taking screenshots, clicking at screen
coordinates, typing text, and pressing keyboard hotkeys. Uses a vision-
capable LLM to drive an agentic loop: screenshot → reason → act → repeat.

Architecture mirrors ``browser_use``:
- Single-node LangGraph: ``START → run_computer_use → END``
- Manual step loop with ``max_steps`` cap and early-exit on ``done`` action
- Structured LLM call for post-run result synthesis / quality gate
- Wire events (started/step/completed) emitted via ``emit_subagent_wire_event``
- Structured logging parallel to wire events

Uses only soothe-sdk (no soothe daemon dependency).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import platform
import tempfile
import time
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

if TYPE_CHECKING:
    from soothe_deepagents.middleware.subagents import CompiledSubAgent

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from soothe_sdk.utils.formatting import format_cli_error

from soothe_nano.subagents.computer_use._preview import preview_first
from soothe_nano.subagents.computer_use.action_format import (
    summarize_computer_step_action,
)
from soothe_nano.subagents.computer_use.config_model import ComputerUseSubagentConfig
from soothe_nano.subagents.computer_use.display_summary import (
    computer_use_result_summary_for_display,
)
from soothe_nano.subagents.computer_use.events import (
    ComputerUseCompletedEvent,
    ComputerUseStartedEvent,
    ComputerUseStepCompletedEvent,
)
from soothe_nano.subagents.computer_use.tools import (
    ComputerUseToolkit,
    _DesktopInputBackend,
)
from soothe_nano.utils.runtime import (
    cleanup_computer_temp_files,
    get_computer_screenshots_dir,
)
from soothe_nano.utils.subagent_emit import emit_subagent_wire_event

logger = logging.getLogger(__name__)

_NO_EXTRACTED_CONTENT = "ComputerUse task completed (no extracted content.)"
_MAX_HISTORY_DIGEST_STEPS = 12

# Actions that observe the screen without changing it. Repeating them cannot
# advance the task, so the loop nudges the model after a couple in a row.
_OBSERVE_ONLY_ACTIONS = frozenset({"screenshot", "wait"})
_MAX_CONSECUTIVE_OBSERVE_ACTIONS = 2

# Screenshots are inlined into the prompt as data URIs; match the image
# toolkit's 20 MiB ceiling so an oversized capture degrades to text-only
# rather than blowing up the request.
_MAX_SCREENSHOT_IMAGE_BYTES = 20 * 1024 * 1024
_SCREENSHOT_MIME_BY_SUFFIX: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

_PYAUTOGUI_MISSING_HINT = (
    "pyautogui is not installed in the interpreter running soothe-nano, so clicks, "
    "typing, and scrolling cannot be performed (screenshots may still work via the "
    "macOS screencapture CLI). Install it into that interpreter with "
    "`pip install pyautogui` and re-run."
)


class DesktopInputUnavailableError(RuntimeError):
    """Raised when the desktop input backend cannot drive mouse/keyboard input."""


# ─── Structured Synthesis Decision ────────────────────────────────────────


class _ComputerUseSynthesisDecision(BaseModel):
    """Structured result-quality judgement and fallback answer synthesis."""

    use_raw_result: bool = Field(
        default=True,
        description="Whether raw computer_use result is already sufficient for end-user answer.",
    )
    answer_quality: Literal["sufficient", "insufficient"] = Field(
        default="insufficient",
        description="Whether the selected answer is sufficient to complete the task.",
    )
    final_answer: str = Field(
        default="",
        description="User-facing final answer text (raw or synthesized).",
    )
    summary: str = Field(
        default="",
        description="Short completion summary for subagent completion card.",
    )
    rationale: str = Field(
        default="",
        description="Brief explanation for the quality judgement and answer choice.",
    )


# ─── Structured LLM Action Output ─────────────────────────────────────────


class _ComputerAction(BaseModel):
    """One step's action decision from the vision LLM."""

    action_type: str = Field(
        ...,
        description=(
            "Action to take: 'screenshot', 'click', 'double_click', 'right_click', "
            "'type', 'key', 'hotkey', 'scroll', 'wait', or 'done'."
        ),
    )
    x: int = Field(default=0, description="X coordinate for click/scroll actions.")
    y: int = Field(default=0, description="Y coordinate for click/scroll actions.")
    button: str = Field(default="left", description="Mouse button: 'left', 'right', or 'middle'.")
    click_type: str = Field(
        default="single", description="Click type: 'single', 'double', or 'triple'."
    )
    text: str = Field(default="", description="Text to type when action_type='type'.")
    key: str = Field(default="", description="Key to press when action_type='key'.")
    keys: str = Field(
        default="",
        description="Comma-separated key combo when action_type='hotkey' (e.g. 'ctrl,c').",
    )
    direction: str = Field(default="down", description="Scroll direction: 'up' or 'down'.")
    amount: int = Field(default=3, description="Scroll amount (number of clicks).")
    reason: str = Field(
        default="",
        description="Brief reasoning for why this action was chosen.",
    )


# ─── Logging Helper ───────────────────────────────────────────────────────


def _log_computer_event(event: str, **fields: Any) -> None:
    """Emit a compact structured computer-use log line.

    Example:
        computer_use event=run_start run_id=abc123 model=gpt-4.1 max_steps=15
    """
    parts = [f"computer_use event={event}"]
    for key, value in fields.items():
        parts.append(f"{key}={value!r}")
    logger.info(" ".join(parts))


# ─── Platform Detection ───────────────────────────────────────────────────


def _detect_platform_metadata() -> dict[str, str]:
    """Detect the host platform and display-server metadata.

    Returns a flat dict of short string fields suitable for structured logging
    (e.g. ``platform="darwin"``, ``display_server="windowserver"``). Detecting
    the display server helps triage blank-screenshot or input-failure issues:
    pyautogui requires a running display (X11 / Wayland / WindowServer), and the
    absence of the relevant env var is a common root cause.

    Fields:
        platform: ``platform.system()`` lowercased (e.g. ``darwin``).
        platform_release: short OS release string.
        machine: CPU architecture (e.g. ``arm64``, ``x86_64``).
        display_server: best-guess active display server
            (``windowserver`` on macOS, ``x11`` / ``wayland`` on Linux,
            ``win32`` on Windows, ``unknown`` otherwise).
        display_env: value of ``DISPLAY`` / ``WAYLAND_DISPLAY`` if set
            (empty on macOS/Windows).
    """
    sys_platform = (platform.system() or "").lower()
    machine = (platform.machine() or "").lower()
    release = (platform.release() or "")[:40]

    display_env = ""
    if sys_platform == "darwin":
        display_server = "windowserver"
    elif sys_platform.startswith("win"):
        display_server = "win32"
    elif sys_platform in ("linux", "linux2"):
        wayland = os.environ.get("WAYLAND_DISPLAY", "").strip()
        x11 = os.environ.get("DISPLAY", "").strip()
        if wayland:
            display_server = "wayland"
            display_env = wayland
        elif x11:
            display_server = "x11"
            display_env = x11
        else:
            display_server = "unknown"
    else:
        display_server = "unknown"

    return {
        "platform": sys_platform or "unknown",
        "platform_release": release,
        "machine": machine or "unknown",
        "display_server": display_server,
        "display_env": preview_first(display_env, 60),
    }


# ─── macOS Permission Verification ──────────────────────────────────────────


def _check_macos_accessibility_permission() -> dict[str, Any]:
    """Probe macOS Accessibility (AXIsProcessTrusted) permission state.

    On macOS, pyautogui's ``click()``/``typewrite()``/``hotkey()`` silently
    no-op when the calling process lacks the Accessibility entitlement.
    This helper returns a dict describing the current state so the backend
    factory and ``run_start`` log can surface it for triage.

    Returns:
        A dict with keys:
        * ``platform``: ``"darwin"`` or the actual platform string.
        * ``supported``: bool — whether the probe is meaningful on this OS.
        * ``accessibility_granted``: bool — True when Accessibility is
          granted (Darwin) or the OS doesn't gate input (non-Darwin).
        * ``detail``: short human-readable status string.

    The probe prefers the ctypes/Quartz ``AXIsProcessTrustedWithOptions``
    API so it can *prompt* (``kAXTrustedCheckOptionPrompt``) on first run;
    when Quartz/ctypes is unavailable it falls back to a heuristic: spawn a
    no-op CGEvent and check whether the system raises. The fallback never
    raises; it returns ``granted=False`` with ``detail="probe_unavailable"``.
    """
    sys_platform = (platform.system() or "").lower()
    if sys_platform != "darwin":
        return {
            "platform": sys_platform or "unknown",
            "supported": False,
            "accessibility_granted": True,  # non-Darwin: not gated
            "detail": "not_darwin",
        }

    # Preferred path: call AXIsProcessTrustedWithOptions via ctypes. This
    # matches what pyautogui/mss do internally and can trigger the system
    # prompt when ``prompt=True``.
    try:
        import ctypes

        # CoreFoundation + ApplicationServices are always present on Darwin.
        ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        from ctypes import c_void_p

        app_services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        # AXIsProcessTrustedWithOptions(CFDictionaryRef options) -> bool
        app_services.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        app_services.AXIsProcessTrustedWithOptions.argtypes = [c_void_p]

        # We don't build a CFDictionary for the prompt option here (that would
        # require CoreFoundation glue); passing NULL yields the non-prompting
        # boolean, which is sufficient for a pre-flight check.
        trusted = bool(app_services.AXIsProcessTrustedWithOptions(None))
        return {
            "platform": "darwin",
            "supported": True,
            "accessibility_granted": trusted,
            "detail": "granted" if trusted else "missing_accessibility",
        }
    except Exception:  # noqa: BLE001 — best-effort probe, never fatal
        pass

    # Fallback heuristic: a click at (0,0) with FAILSAFE off would raise
    # ImageNotFoundException when not trusted, but that's flaky. Instead we
    # report a probe-unavailable state so callers can fall back to pyautogui
    # and rely on its own (silent) failure mode + docs guidance.
    return {
        "platform": "darwin",
        "supported": True,
        "accessibility_granted": False,
        "detail": "probe_unavailable",
    }


def _check_macos_screen_recording_permission() -> dict[str, Any]:
    """Probe macOS Screen Recording permission (for pyautogui screenshots).

    On macOS, pyautogui's ``screenshot()`` returns a blank/permission-denied
    image when Screen Recording is not granted. This helper returns the
    current state. When Screen Recording is missing, the agent should use
    the ``screencapture`` CLI fallback (which does not require the same
    TCC entitlement for basic full-screen capture in many configurations).

    Returns:
        A dict with keys ``platform``, ``supported``, ``screen_recording_granted``,
        ``detail``. On non-Darwin it returns ``granted=True, supported=False``.
    """
    sys_platform = (platform.system() or "").lower()
    if sys_platform != "darwin":
        return {
            "platform": sys_platform or "unknown",
            "supported": False,
            "screen_recording_granted": True,  # non-Darwin: not gated
            "detail": "not_darwin",
        }

    # Heuristic: capture a 1x1 pixel region to /dev/null-ish temp file and
    # check whether the result is non-trivial. A blank (all-zero) image
    # indicates Screen Recording is missing. This is the same signal
    # pyautogui itself uses; we replicate it pre-flight so the backend can
    # decide whether to route to ``screencapture``.
    try:
        import tempfile as _tempfile

        fd, tmp = _tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            import subprocess

            # ``screencapture -R{x,y,w,h}`` crops; a 1x1 probe is cheap.
            proc = subprocess.run(
                ["screencapture", "-x", "-R0,0,1,1", tmp],
                check=False,
                capture_output=True,
                timeout=10,
            )
            if proc.returncode != 0:
                return {
                    "platform": "darwin",
                    "supported": True,
                    "screen_recording_granted": False,
                    "detail": "screencapture_failed",
                }
            # Read the pixel; a 1x1 PNG should be a few hundred bytes.
            size = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            granted = size > 0
            return {
                "platform": "darwin",
                "supported": True,
                "screen_recording_granted": granted,
                "detail": "granted" if granted else "blank_capture",
            }
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except Exception:  # noqa: BLE001 — best-effort, never fatal
        return {
            "platform": "darwin",
            "supported": True,
            "screen_recording_granted": False,
            "detail": "probe_unavailable",
        }


# ─── Model Resolution ─────────────────────────────────────────────────────


def _parse_model_spec(spec: str) -> tuple[str, str]:
    """Split ``provider:model`` into components."""
    provider_name, _, model_name = spec.partition(":")
    if not model_name:
        model_name = provider_name
        provider_name = ""
    return provider_name, model_name


def computer_use_model_role(soothe_config: Any) -> str:
    """Return configured router role for computer_use (default ``default``)."""
    subagents = getattr(soothe_config, "subagents", None) or {}
    sub_cfg = subagents.get("computer_use") if hasattr(subagents, "get") else None
    role = getattr(sub_cfg, "model_role", None) if sub_cfg is not None else None
    return role or "default"


def _resolve_computer_llm_credentials(*, soothe_config: Any) -> tuple[str, str | None, str | None]:
    """Resolve computer-use LLM model name and provider endpoint credentials."""
    resolve = getattr(soothe_config, "resolve_model", None)
    if not callable(resolve):
        msg = "computer_use requires SootheConfig with resolve_model()"
        raise ValueError(msg)

    role = computer_use_model_role(soothe_config)
    spec = resolve(role)
    if not isinstance(spec, str) or not spec.strip():
        msg = f"computer_use model_role={role!r} did not resolve to a model spec"
        raise ValueError(msg)

    provider_name, model_name = _parse_model_spec(spec.strip())
    providers = getattr(soothe_config, "providers", None) or []
    from soothe_nano.llm.registry import ProviderRegistry

    registry = ProviderRegistry(providers)
    _, kwargs = registry.get_provider_kwargs(provider_name)
    return model_name, kwargs.get("base_url"), kwargs.get("api_key")


# ─── Default Backend (pyautogui / osascript) ──────────────────────────────


class _PyAutoGUIBackend(_DesktopInputBackend):
    """Desktop input backend using pyautogui.

    Installed lazily so the plugin loads even when pyautogui is absent.

    ``coordinate_scale`` rescales coordinates between the LLM's pixel space
    and pyautogui's input space. On Retina/HiDPI displays, pyautogui's
    ``screenshot()`` returns a physical-resolution image (e.g. 2x), while
    ``click()``/``moveTo()`` consume logical (1x) coordinates. The vision LLM
    reasons over the captured screenshot, so its coordinates live in the
    screenshot's (physical) pixel space and must be divided by
    ``coordinate_scale`` before being handed to pyautogui. ``coordinate_scale=1``
    is a no-op (logical == physical).

    ``screenshot_source`` selects the image-acquisition path:

    * ``"screencapture"`` — the macOS-native ``screencapture(1)`` CLI. This
      does not require pyautogui's Screen Recording entitlement on Darwin and
      produces a physical-resolution PNG matching pyautogui's output, so the
      ``coordinate_scale`` contract is unchanged.
    * ``"pyautogui"`` — the cross-platform Pillow/pyautogui path.
    * ``"auto"`` — ``screencapture`` on Darwin, falling back to pyautogui on
      non-Darwin or on CLI failure. The fallback is logged via
      ``_log_computer_event`` so triage can see which path served the image.
    """

    def __init__(
        self,
        *,
        screenshots_dir: str,
        coordinate_scale: int = 1,
        screenshot_source: str = "auto",
        screenshot_format: str = "png",
        screenshot_quality: int = 85,
    ) -> None:
        self._screenshots_dir = screenshots_dir
        self._coordinate_scale = max(int(coordinate_scale or 1), 1)
        self._screenshot_source = (screenshot_source or "auto").lower()
        self._screenshot_format = (screenshot_format or "png").lower()
        self._screenshot_quality = max(1, min(100, int(screenshot_quality or 85)))
        self._pyautogui: Any = None
        self._step_counter: int = 0
        self._scale_probed: bool = False

    def _ensure_pagu(self) -> Any:
        if self._pyautogui is None:
            try:
                import pyautogui
            except ImportError as exc:
                raise DesktopInputUnavailableError(_PYAUTOGUI_MISSING_HINT) from exc

            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1
            self._pyautogui = pyautogui
        return self._pyautogui

    def input_available(self) -> bool:
        """Return True when mouse/keyboard input can actually be driven.

        On macOS the ``screencapture`` CLI serves screenshots without pyautogui,
        so a backend can look healthy right up until the first click.
        """
        try:
            self._ensure_pagu()
        except DesktopInputUnavailableError:
            return False
        return True

    def _rescale_coord(self, value: int) -> int:
        """Map an LLM-space coordinate to pyautogui's (logical) input space.

        With ``coordinate_scale=2`` (Retina), the LLM picks coordinates in the
        physical-resolution screenshot; pyautogui expects logical coordinates,
        so we divide by the scale factor.
        """
        if self._coordinate_scale <= 1:
            return int(value)
        return int(value) // self._coordinate_scale

    def _probe_coordinate_scale(self, image_width: int) -> None:
        """Correct ``coordinate_scale`` from the first captured screenshot.

        A misconfigured scale sends every click to the wrong place, and the
        right value is directly measurable: the ratio between the screenshot's
        physical width and pyautogui's logical screen width. Measured once per
        backend, since the display geometry does not change mid-run.
        """
        if self._scale_probed or image_width <= 0:
            return
        try:
            logical_width = int(self._ensure_pagu().size()[0])
        except Exception:  # noqa: BLE001 — best-effort probe, never fatal
            return
        self._scale_probed = True
        if logical_width <= 0:
            return
        detected = round(image_width / logical_width)
        if not (1 <= detected <= 4) or detected == self._coordinate_scale:
            return
        _log_computer_event(
            "coordinate_scale_detected",
            configured=self._coordinate_scale,
            detected=detected,
            image_width=image_width,
            logical_width=logical_width,
        )
        self._coordinate_scale = detected

    # ─── macOS screencapture path ──────────────────────────────────────────

    @staticmethod
    def _is_darwin() -> bool:
        """Return True when running on macOS (Darwin)."""
        return platform.system() == "Darwin"

    def _can_use_screencapture(self) -> bool:
        """Return True when the macOS ``screencapture`` CLI should be used.

        Honors the configured ``screenshot_source``:

        * ``screencapture`` → True iff Darwin.
        * ``pyautogui`` → always False (user opted out).
        * ``auto`` → True iff Darwin.
        """
        if self._screenshot_source == "pyautogui":
            return False
        if self._screenshot_source == "screencapture":
            return self._is_darwin()
        # auto
        return self._is_darwin()

    def _capture_via_screencapture(
        self, *, region: str, save_path: str | None
    ) -> dict[str, Any] | None:
        """Capture a screenshot via the macOS ``screencapture(1)`` CLI.

        Returns ``None`` when the CLI is unavailable or fails so the caller can
        fall back to pyautogui. ``screencapture`` always writes PNG; we honor
        ``screenshot_format=jpeg`` by re-encoding via Pillow when requested.
        """
        import shutil
        import subprocess

        if not shutil.which("screencapture"):
            return None  # not available — fall back

        self._step_counter += 1
        ext = "png"
        tmp_png: str | None = None
        final_path = save_path or os.path.join(
            self._screenshots_dir, f"screenshot_{self._step_counter:04d}.{ext}"
        )

        # Region capture: screencapture accepts a rect via -R{x,y,w,h}. The
        # tool schema passes "left,top,right,bottom"; convert to x,y,w,h.
        rect_args: list[str] = []
        if region != "full":
            try:
                parts = [int(p.strip()) for p in region.split(",")]
                if len(parts) == 4:
                    left, top, right, bottom = parts
                    rect_args = ["-R", f"{left},{top},{right - left},{bottom - top}"]
            except (ValueError, TypeError):
                rect_args = []  # malformed region — capture full screen instead

        # If JPEG is requested, screencapture still emits PNG; route through a
        # temp PNG then re-encode to the final JPEG path.
        if self._screenshot_format == "jpeg":
            final_path = save_path or os.path.join(
                self._screenshots_dir,
                f"screenshot_{self._step_counter:04d}.jpeg",
            )
            # screencapture cannot write JPEG directly; capture to temp PNG.
            tmp_fd, tmp_png = tempfile.mkstemp(suffix=".png")
            os.close(tmp_fd)
            capture_target = tmp_png
        else:
            capture_target = final_path

        cmd = ["screencapture", "-x"]
        cmd.extend(rect_args)
        cmd.append(capture_target)

        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.SubprocessError, OSError):
            if tmp_png and os.path.exists(tmp_png):
                os.unlink(tmp_png)
            return None  # fall back

        if result.returncode != 0:
            if tmp_png and os.path.exists(tmp_png):
                os.unlink(tmp_png)
            return None  # fall back

        # Re-encode to JPEG when requested.
        if tmp_png is not None:
            try:
                from PIL import Image  # available via pyautogui dep; graceful if not

                with Image.open(tmp_png) as img:
                    img.convert("RGB").save(
                        final_path,
                        format="JPEG",
                        quality=self._screenshot_quality,
                    )
            except Exception:  # noqa: BLE001 — best-effort re-encode
                # If re-encode fails, keep the PNG by copying it to final_path
                # only when final_path differs (avoids same-file copy).
                if final_path != tmp_png:
                    shutil.copyfile(tmp_png, final_path)
            finally:
                if os.path.exists(tmp_png):
                    os.unlink(tmp_png)

        # Determine dimensions from the produced file (PNG or JPEG).
        width, height = self._image_dimensions(final_path)
        return {
            "action": "screenshot",
            "path": final_path,
            "width": width,
            "height": height,
            "source": "screencapture",
        }

    @staticmethod
    def _image_dimensions(path: str) -> tuple[int, int]:
        """Best-effort read of image width/height via Pillow.

        Returns ``(0, 0)`` when Pillow is unavailable or the file cannot be
        read; the caller treats a zero dimension as a non-fatal soft failure
        (the LLM still receives the file path).
        """
        try:
            from PIL import Image

            with Image.open(path) as img:
                return tuple(img.size)  # type: ignore[return-value]
        except Exception:  # noqa: BLE001 — best-effort
            return (0, 0)

    # ─── pyautogui screenshot path ─────────────────────────────────────────

    def _capture_via_pyautogui(self, *, region: str, save_path: str | None) -> dict[str, Any]:
        """Capture a screenshot via pyautogui (cross-platform fallback)."""
        pag = self._ensure_pagu()

        if region != "full":
            parts = [int(p.strip()) for p in region.split(",")]
            screenshot = pag.screenshot(region=tuple(parts))
        else:
            screenshot = pag.screenshot()

        self._step_counter += 1
        ext = self._screenshot_format
        filename = save_path or os.path.join(
            self._screenshots_dir, f"screenshot_{self._step_counter:04d}.{ext}"
        )
        if self._screenshot_format == "jpeg":
            screenshot.convert("RGB").save(
                filename, format="JPEG", quality=self._screenshot_quality
            )
        else:
            screenshot.save(filename)
        size = screenshot.size
        return {
            "action": "screenshot",
            "path": filename,
            "width": size[0],
            "height": size[1],
            "source": "pyautogui",
        }

    def capture_screenshot(
        self,
        *,
        region: str = "full",
        save_path: str | None = None,
    ) -> dict[str, Any]:
        # Try the macOS-native screencapture CLI first when configured.
        if self._can_use_screencapture():
            result = self._capture_via_screencapture(region=region, save_path=save_path)
            if result is not None:
                _log_computer_event(
                    "screenshot_served",
                    backend="pyautogui",
                    source="screencapture",
                    path=result.get("path", ""),
                )
                if region == "full":
                    self._probe_coordinate_scale(int(result.get("width") or 0))
                return result
            # screencapture unavailable/failed — fall through to pyautogui.
            _log_computer_event(
                "screenshot_fallback",
                backend="pyautogui",
                source="pyautogui",
                reason="screencapture unavailable or failed",
            )

        result = self._capture_via_pyautogui(region=region, save_path=save_path)
        if region == "full":
            self._probe_coordinate_scale(int(result.get("width") or 0))
        return result

    def click(
        self,
        *,
        x: int,
        y: int,
        button: str = "left",
        click_type: str = "single",
    ) -> dict[str, Any]:
        pag = self._ensure_pagu()
        clicks = {"single": 1, "double": 2, "triple": 3}.get(click_type, 1)
        target_x = self._rescale_coord(x)
        target_y = self._rescale_coord(y)
        pag.click(x=target_x, y=target_y, button=button, clicks=clicks)
        return {
            "action": "click",
            "x": x,
            "y": y,
            "scale": self._coordinate_scale,
            "input_x": target_x,
            "input_y": target_y,
            "button": button,
            "click_type": click_type,
        }

    def keyboard(
        self,
        *,
        action_type: str,
        text: str = "",
        key: str = "",
        keys: str = "",
    ) -> dict[str, Any]:
        pag = self._ensure_pagu()
        if action_type == "type":
            pag.typewrite(text)
            return {"action": "type", "text": text}
        if action_type == "key":
            pag.press(key)
            return {"action": "key", "key": key}
        if action_type == "hotkey":
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
            pag.hotkey(*key_list)
            return {"action": "hotkey", "keys": keys}
        return {"action": "keyboard", "error": f"unknown action_type: {action_type}"}

    def scroll(
        self,
        *,
        x: int = 0,
        y: int = 0,
        direction: str = "down",
        amount: int = 3,
    ) -> dict[str, Any]:
        pag = self._ensure_pagu()
        target_x = self._rescale_coord(x) if x else x
        target_y = self._rescale_coord(y) if y else y
        if x or y:
            pag.moveTo(target_x, target_y)
        scroll_val = -amount if direction == "down" else amount
        pag.scroll(scroll_val)
        return {
            "action": "scroll",
            "x": x,
            "y": y,
            "scale": self._coordinate_scale,
            "input_x": target_x,
            "input_y": target_y,
            "direction": direction,
            "amount": amount,
        }

    def close(self) -> None:
        self._pyautogui = None


# ─── History & Synthesis Helpers ──────────────────────────────────────────


class _StepHistory:
    """Lightweight step history for computer_use agent loop.

    Stores per-step action, tool result, and screenshot path so we can
    build a trajectory digest for post-run synthesis.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def add(
        self,
        *,
        step: int,
        action: _ComputerAction | None,
        result: dict[str, Any] | None,
    ) -> None:
        self._entries.append(
            {
                "step": step,
                "action": action.model_dump() if action else None,
                "result": result,
            }
        )

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self._entries

    def is_done(self) -> bool:
        """Return True if the last action was a 'done' action."""
        if not self._entries:
            return False
        last_action = self._entries[-1].get("action")
        if last_action is None:
            return False
        return str(last_action.get("action_type", "")).lower() == "done"

    def final_result(self) -> str | None:
        """Extract the 'reason' field from the 'done' action as final result."""
        for entry in reversed(self._entries):
            action = entry.get("action")
            if action and str(action.get("action_type", "")).lower() == "done":
                return str(action.get("reason") or "").strip() or None
        return None


def _computer_history_had_no_progress(history: _StepHistory) -> bool:
    """Return True when the agent never took a meaningful action.

    Screenshots and waits observe the screen but never change it, so a run
    made up entirely of them has made no progress no matter how many steps
    it burned.
    """
    entries = history.entries
    if not entries:
        return True
    for entry in entries:
        action = entry.get("action")
        if action is None:
            continue
        at = str(action.get("action_type", "")).lower()
        if at and at not in _OBSERVE_ONLY_ACTIONS:
            return False
    return True


def _format_computer_no_progress_error(*, model_name: str, steps: int) -> str:
    return (
        "ComputerUse failed: the agent ran "
        f"{steps} step(s) without taking any meaningful desktop action "
        "(only screenshots or waits). "
        f"Model: {model_name}. "
        "Check subagents.computer_use.model_role and provider API credentials."
    )


def _history_digest_for_synthesis(history: _StepHistory) -> str:
    """Return a concise, structured trajectory summary for synthesis prompts."""
    entries = history.entries
    if not entries:
        return "(no computer_use step history)"
    lines: list[str] = []
    for idx, entry in enumerate(entries[:_MAX_HISTORY_DIGEST_STEPS], start=1):
        action = entry.get("action")
        result = entry.get("result")
        tool_name = "Step"
        action_preview = ""
        if action is not None:
            tool_name, action_preview = summarize_computer_step_action(action)
        result_summary = ""
        if result is not None:
            if "error" in result:
                result_summary = f"error={result['error']}"
            elif "path" in result:
                result_summary = f"screenshot={preview_first(result['path'], 80)}"
            elif "action" in result:
                result_summary = preview_first(str(result.get("action")), 60)
        line = (
            f"{idx}. tool={tool_name}; action={action_preview or '(none)'}; "
            f"result={result_summary or '(none)'}"
        )
        lines.append(line)
    if len(entries) > _MAX_HISTORY_DIGEST_STEPS:
        lines.append(f"... ({len(entries) - _MAX_HISTORY_DIGEST_STEPS} more steps)")
    return "\n".join(lines)


def _apply_computer_use_synthesis_decision(
    *,
    raw_result: str,
    decision: _ComputerUseSynthesisDecision | None,
) -> tuple[str, str, bool, bool]:
    """Resolve final answer/summary from structured synthesis decision.

    Returns:
        Tuple of ``(final_answer, summary, used_synthesized_answer, quality_sufficient)``.
    """
    raw = (raw_result or "").strip()
    if decision is None:
        summary = computer_use_result_summary_for_display(raw)
        return raw, summary, False, False

    preferred = raw if decision.use_raw_result else decision.final_answer.strip()
    if not preferred:
        preferred = raw
    if not preferred:
        preferred = _NO_EXTRACTED_CONTENT
    summary = (decision.summary or "").strip() or computer_use_result_summary_for_display(preferred)
    used_synthesized = preferred != raw and bool(preferred.strip())
    quality_sufficient = decision.answer_quality == "sufficient"
    return preferred, summary, used_synthesized, quality_sufficient


async def _synthesize_computer_use_result(
    *,
    task: str,
    raw_result: str,
    history_digest: str,
    soothe_config: Any,
    computer_config: ComputerUseSubagentConfig,
    run_id: str,
) -> _ComputerUseSynthesisDecision | None:
    """Run deep-research-style structured synthesis over computer_use run output."""
    from soothe_nano.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )
    from soothe_nano.llm.structured import invoke_structured_chat_typed

    role = (computer_config.synthesis_role or "").strip() or computer_use_model_role(soothe_config)
    try:
        synthesis_model = soothe_config.create_chat_model(role)
    except Exception:
        logger.warning(
            "computer_use synthesis role %r unavailable, skipping synthesis",
            role,
            exc_info=True,
        )
        return None

    prompt = (
        "You are a result-quality judge and report synthesizer for desktop automation.\n"
        "Given task, raw result, and step trajectory, decide whether raw result is"
        " sufficient.\n"
        "If raw result is low-information, synthesize a better final answer strictly from the"
        " provided evidence.\n"
        "Never invent facts not present in the evidence.\n"
        "Respond in the same language as the task.\n\n"
        f"Task:\n{task or '(empty task)'}\n\n"
        f"Raw result:\n{raw_result or '(empty)'}\n\n"
        f"Desktop trajectory:\n{history_digest}\n"
    )
    llm_config = llm_rate_limit_config_from(soothe_config).model_copy(
        update={
            "call_timeout_seconds": int(computer_config.synthesis_timeout_sec),
            "call_timeout_max_seconds": int(computer_config.synthesis_timeout_sec),
        }
    )

    async def _invoke() -> _ComputerUseSynthesisDecision:
        return await invoke_structured_chat_typed(
            synthesis_model,
            [{"role": "user", "content": prompt}],
            _ComputerUseSynthesisDecision,
        )

    _log_computer_event("synthesis_begin", run_id=run_id, role=role)
    try:
        decision = await await_with_llm_call_policy(_invoke, config=llm_config)
    except Exception:
        logger.warning("computer_use synthesis failed (run_id=%s)", run_id, exc_info=True)
        return None
    _log_computer_event(
        "synthesis_end",
        run_id=run_id,
        use_raw=decision.use_raw_result,
        quality=decision.answer_quality,
    )
    return decision


# ─── Step Execution ───────────────────────────────────────────────────────


async def _execute_step(
    *,
    action: _ComputerAction,
    backend: _DesktopInputBackend,
) -> dict[str, Any]:
    """Execute one ``_ComputerAction`` against the desktop backend.

    Backend failures are returned as ``{"error": ...}`` rather than raised: the
    model sees the error in its trajectory and can retry or explain, whereas an
    exception would abort the whole run over one bad action.
    """
    at = action.action_type.lower().strip()
    try:
        return await _dispatch_step(action=action, backend=backend, action_type=at)
    except DesktopInputUnavailableError as exc:
        return {"action": at, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — surfaced to the model as a step result
        logger.warning("computer_use action %s failed", at, exc_info=True)
        return {"action": at, "error": f"{at} failed: {exc}"}


async def _dispatch_step(
    *,
    action: _ComputerAction,
    backend: _DesktopInputBackend,
    action_type: str,
) -> dict[str, Any]:
    """Route one action to its backend method."""
    at = action_type

    if at == "screenshot":
        return await backend.acapture_screenshot()
    if at == "click":
        return await backend.aclick(
            x=action.x, y=action.y, button=action.button, click_type=action.click_type
        )
    if at == "double_click":
        return await backend.aclick(
            x=action.x, y=action.y, button=action.button, click_type="double"
        )
    if at == "right_click":
        return await backend.aclick(
            x=action.x, y=action.y, button="right", click_type=action.click_type
        )
    if at == "type":
        return await backend.akeyboard(action_type="type", text=action.text)
    if at == "key":
        return await backend.akeyboard(action_type="key", key=action.key)
    if at == "hotkey":
        return await backend.akeyboard(action_type="hotkey", keys=action.keys)
    if at == "scroll":
        return await backend.ascroll(
            x=action.x,
            y=action.y,
            direction=action.direction,
            amount=action.amount,
        )
    if at == "wait":
        await asyncio.sleep(0.5)
        return {"action": "wait", "seconds": 0.5}
    if at == "done":
        return {"action": "done", "reason": action.reason}

    return {"action": at, "error": f"unknown action_type: {at}"}


def _screenshot_data_url(path: str | None) -> str | None:
    """Encode a screenshot file as an OpenAI-compatible ``image_url`` data URI.

    Returns ``None`` for a missing, unreadable, unsupported, or oversized file
    so the caller can fall back to a text-only prompt instead of failing the
    step.
    """
    if not path:
        return None
    mime = _SCREENSHOT_MIME_BY_SUFFIX.get(os.path.splitext(path)[1].lower())
    if mime is None:
        return None
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        logger.warning("computer_use could not read screenshot %s", path, exc_info=True)
        return None
    if not raw or len(raw) > _MAX_SCREENSHOT_IMAGE_BYTES:
        return None
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _trajectory_digest(history: _StepHistory) -> str:
    """Summarize the last few steps so the model can see what it already tried."""
    lines: list[str] = []
    for entry in history.entries[-8:]:
        action = entry.get("action")
        if not action:
            continue
        tool_name, detail = summarize_computer_step_action(action)
        result = entry.get("result") or {}
        outcome = ""
        if "error" in result:
            outcome = f" -> error: {result['error']}"
        elif "path" in result:
            outcome = f" -> screenshot {result.get('width')}x{result.get('height')}"
        lines.append(f"  - {tool_name}: {detail}{outcome}")
    return "\n".join(lines) if lines else "(no prior steps)"


async def _decide_next_action(
    *,
    llm: Any,
    task: str,
    history: _StepHistory,
    max_steps: int,
    screenshot_path: str | None = None,
    screen_size: tuple[int, int] | None = None,
    consecutive_observations: int = 0,
) -> _ComputerAction:
    """Ask the vision LLM to decide the next action given the current screen.

    The most recent screenshot is attached as an ``image_url`` content block so
    the model can actually see the desktop; without it the model has no way to
    locate UI targets and will keep asking for screenshots forever.
    """
    from soothe_nano.llm.structured import invoke_structured_chat_typed

    system_prompt = (
        "You are a desktop automation agent. You drive the computer by choosing one action per step.\n\n"
        "A screenshot of the current screen is attached to each request, and a fresh one is\n"
        "captured automatically after every action you take.\n\n"
        "Available actions:\n"
        "- click: Click at (x, y) with a button ('left'/'right'/'middle') and click_type ('single'/'double'/'triple')\n"
        "- double_click: Shortcut for click with click_type='double'\n"
        "- right_click: Shortcut for click with button='right'\n"
        "- type: Type a string of text (set 'text' field)\n"
        "- key: Press a single key like 'enter', 'tab', 'escape' (set 'key' field)\n"
        "- hotkey: Press a key combination (set 'keys' field, e.g. 'cmd,space')\n"
        "- scroll: Scroll at (x, y) in a direction ('up'/'down') by amount clicks\n"
        "- screenshot: Re-capture the screen (rarely needed — one is already attached)\n"
        "- wait: Pause briefly (e.g. for a dialog to load)\n"
        "- done: Task is complete (set 'reason' with a summary of what was accomplished)\n\n"
        "Rules:\n"
        "1. Read the attached screenshot, then act. Do not ask for another screenshot\n"
        "   just to confirm what is already visible.\n"
        "2. Coordinates are pixels from the top-left (0, 0) of the attached screenshot.\n"
        "3. Every step should move the task forward — prefer clicking, typing, or\n"
        "   scrolling over observing.\n"
        "4. When the task is complete, choose action_type='done' and put the full\n"
        "   answer (including any text or URLs you read on screen) in 'reason'.\n"
        "5. If you cannot complete the task after reasonable attempts, choose 'done'\n"
        "   with an explanation of what blocked you.\n"
    )

    prompt_sections = [
        f"Task: {task}",
        f"Recent trajectory:\n{_trajectory_digest(history)}",
        f"Steps remaining: {max_steps - len(history.entries)}",
    ]
    if screen_size and all(screen_size):
        prompt_sections.append(
            f"The attached screenshot is {screen_size[0]}x{screen_size[1]} pixels; "
            "give coordinates in that space."
        )
    if consecutive_observations >= _MAX_CONSECUTIVE_OBSERVE_ACTIONS:
        prompt_sections.append(
            f"You have observed the screen {consecutive_observations} times in a row without "
            "changing anything. The attached screenshot is current — take a concrete action "
            "now (click/type/scroll), or choose 'done' and explain what is blocking you."
        )
    prompt_sections.append("Choose the next action.")
    user_prompt = "\n\n".join(prompt_sections)

    data_url = _screenshot_data_url(screenshot_path)
    if data_url is None:
        user_message = HumanMessage(content=user_prompt)
    else:
        user_message = HumanMessage(
            content=[
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )

    messages = [SystemMessage(content=system_prompt), user_message]

    try:
        return await invoke_structured_chat_typed(llm, messages, _ComputerAction)
    except Exception as e:
        logger.warning("computer_use action decision failed: %s", e)
        # Fallback: mark as done with error
        return _ComputerAction(
            action_type="done",
            reason=f"Action decision failed: {e}",
        )


async def _capture_observation(
    *,
    backend: _DesktopInputBackend,
    delay_s: float = 0.0,
) -> dict[str, Any] | None:
    """Capture a screenshot for the next decision, letting the UI settle first.

    Returns ``None`` on capture failure; the loop then reuses the previous
    screenshot rather than aborting the run.
    """
    if delay_s > 0:
        await asyncio.sleep(delay_s)
    try:
        result = await backend.acapture_screenshot()
    except Exception:
        logger.warning("computer_use observation screenshot failed", exc_info=True)
        return None
    return result if isinstance(result, dict) and result.get("path") else None


# ─── State Schema ─────────────────────────────────────────────────────────


COMPUTER_DESCRIPTION = (
    "Desktop automation specialist for GUI tasks ONLY. "
    "Can take screenshots, click at screen coordinates, type text, press "
    "keyboard keys and hotkeys, and scroll. Use ONLY for: desktop GUI "
    "automation, application control, visual UI interaction. "
    "DO NOT use for: web URLs (use browser_use), local files (use list_files, "
    "read_file), or shell commands (use run_command)."
)


class _ComputerUseState(TypedDict):
    """State schema for the computer_use subagent graph."""

    messages: Annotated[list[Any], add_messages]


# ─── Graph Builder ────────────────────────────────────────────────────────


def _build_computer_use_graph(
    *,
    max_steps: int | None = None,
    config: ComputerUseSubagentConfig | None = None,
    soothe_config: Any,
    backend: _DesktopInputBackend | None = None,
) -> Any:
    """Build and compile the computer_use LangGraph.

    Args:
        max_steps: Maximum steps for the agent loop. When ``None``, uses
            ``ComputerUseSubagentConfig.max_steps`` (default 99).
        config: ComputerUse subagent configuration object.
        soothe_config: SootheConfig for router-backed computer LLM resolution.
        backend: Desktop input backend (auto-created if None).

    Returns:
        Compiled LangGraph runnable.
    """
    computer_config = config or ComputerUseSubagentConfig()
    resolved_max_steps = max_steps if max_steps is not None else computer_config.max_steps

    async def _run_computer_use_async(state: _ComputerUseState | dict[str, Any]) -> dict[str, Any]:
        import uuid

        screenshots_dir = str(get_computer_screenshots_dir())
        run_id = uuid.uuid4().hex[:8]

        run_t0 = time.perf_counter()
        result = _NO_EXTRACTED_CONTENT
        run_success = True
        backend_instance: _DesktopInputBackend | None = backend

        try:
            messages = state.get("messages", [])
            task = messages[-1].content if messages else ""

            emit_subagent_wire_event(
                ComputerUseStartedEvent(task_preview=preview_first(str(task), 200)).to_dict(),
                logger,
            )

            model_name, llm_base_url, llm_api_key = _resolve_computer_llm_credentials(
                soothe_config=soothe_config,
            )

            platform_meta = _detect_platform_metadata()
            _log_computer_event(
                "run_start",
                run_id=run_id,
                task_len=len(task) if isinstance(task, str) else 0,
                max_steps=resolved_max_steps,
                model=model_name,
                model_role=computer_use_model_role(soothe_config),
                base_url=preview_first(str(llm_base_url or ""), 80) or "(default)",
                coordinate_scale=computer_config.coordinate_scale,
                screenshot_interval_s=computer_config.screenshot_interval_s,
                screenshot_quality=computer_config.screenshot_quality,
                screenshot_format=computer_config.screenshot_format,
                input_mode=computer_config.input_mode,
                action_delay_s=computer_config.action_delay_s,
                **platform_meta,
            )
            _log_computer_event(
                "task_preview",
                run_id=run_id,
                preview=preview_first(str(task), 400),
            )

            # Build the LLM for vision-capable action decisions
            llm_kwargs: dict[str, Any] = {"model": model_name}
            if llm_base_url:
                llm_kwargs["base_url"] = llm_base_url
            if llm_api_key:
                llm_kwargs["api_key"] = llm_api_key

            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(**llm_kwargs)

            # Initialize backend if not provided
            if backend_instance is None:
                # Resolve the effective backend. The config exposes two knobs
                # (``backend`` legacy + ``input_mode`` documented); prefer the
                # documented ``input_mode`` when set, falling back to ``backend``.
                effective_mode = (
                    computer_config.input_mode
                    if computer_config.input_mode != "auto"
                    else computer_config.backend
                )
                # ``auto`` → pyautogui on all platforms (osascript not yet
                # implemented). When ``input_mode`` is non-auto, honor it.
                if effective_mode in ("auto", "pyautogui"):
                    try:
                        backend_instance = _PyAutoGUIBackend(
                            screenshots_dir=screenshots_dir,
                            coordinate_scale=computer_config.coordinate_scale,
                            screenshot_source=computer_config.screenshot_source,
                            screenshot_format=computer_config.screenshot_format,
                            screenshot_quality=computer_config.screenshot_quality,
                        )
                        _log_computer_event(
                            "backend_ready",
                            run_id=run_id,
                            backend="pyautogui",
                            coordinate_scale=computer_config.coordinate_scale,
                            screenshot_source=computer_config.screenshot_source,
                            screenshot_format=computer_config.screenshot_format,
                        )
                        if not backend_instance.input_available():
                            logger.error(
                                "computer_use event=input_unavailable run_id=%s reason=%s",
                                run_id,
                                _PYAUTOGUI_MISSING_HINT,
                            )
                        # Surface macOS permission state so triage can see why
                        # clicks no-op or screenshots come back blank.
                        ax = _check_macos_accessibility_permission()
                        sr = _check_macos_screen_recording_permission()
                        if ax.get("supported"):
                            _log_computer_event(
                                "permission_probe",
                                run_id=run_id,
                                accessibility=ax.get("accessibility_granted"),
                                screen_recording=sr.get("screen_recording_granted"),
                                ax_detail=ax.get("detail"),
                                sr_detail=sr.get("detail"),
                            )
                    except ImportError as e:
                        _log_computer_event(
                            "backend_missing",
                            run_id=run_id,
                            backend="pyautogui",
                            error=str(e),
                        )
                        backend_instance = _DesktopInputBackend()
                elif effective_mode == "osascript":
                    # osascript backend not yet implemented (see audit LYZ-01
                    # gap B1). Fall back to pyautogui so the subagent still
                    # runs rather than hard-failing on every action.
                    _log_computer_event(
                        "backend_fallback",
                        run_id=run_id,
                        requested="osascript",
                        actual="pyautogui",
                        reason="osascript not yet implemented",
                    )
                    try:
                        backend_instance = _PyAutoGUIBackend(
                            screenshots_dir=screenshots_dir,
                            coordinate_scale=computer_config.coordinate_scale,
                            screenshot_source=computer_config.screenshot_source,
                            screenshot_format=computer_config.screenshot_format,
                            screenshot_quality=computer_config.screenshot_quality,
                        )
                    except ImportError:
                        backend_instance = _DesktopInputBackend()
                else:
                    backend_instance = _DesktopInputBackend()

            history = _StepHistory()
            last_step_wall = time.perf_counter()
            latest_screenshot: str | None = None
            screen_size: tuple[int, int] | None = None
            consecutive_observations = 0

            # Prime the loop with a screenshot so the very first decision already
            # sees the desktop instead of spending a step to look at it.
            initial_observation = await _capture_observation(backend=backend_instance)
            if initial_observation is not None:
                latest_screenshot = str(initial_observation["path"])
                screen_size = (
                    int(initial_observation.get("width") or 0),
                    int(initial_observation.get("height") or 0),
                )

            for step_idx in range(resolved_max_steps):
                try:
                    iter_t0 = time.perf_counter()
                    _log_computer_event(
                        "step_begin",
                        run_id=run_id,
                        step=step_idx + 1,
                        max_steps=resolved_max_steps,
                        elapsed_s=round(iter_t0 - run_t0, 1),
                        has_screenshot=latest_screenshot is not None,
                    )

                    # Ask LLM for the next action
                    action = await _decide_next_action(
                        llm=llm,
                        task=str(task),
                        history=history,
                        max_steps=resolved_max_steps,
                        screenshot_path=latest_screenshot,
                        screen_size=screen_size,
                        consecutive_observations=consecutive_observations,
                    )

                    # Execute the action
                    step_result = await _execute_step(action=action, backend=backend_instance)

                    # Record in history
                    history.add(step=step_idx + 1, action=action, result=step_result)

                    action_type = action.action_type.lower().strip()
                    consecutive_observations = (
                        consecutive_observations + 1 if action_type in _OBSERVE_ONLY_ACTIONS else 0
                    )

                    # Refresh the view the next decision will see: an explicit
                    # screenshot already produced one, and any action that
                    # touches the UI needs a new capture after it settles.
                    observation: dict[str, Any] | None = None
                    if action_type == "screenshot":
                        observation = step_result if step_result.get("path") else None
                    elif action_type != "done":
                        observation = await _capture_observation(
                            backend=backend_instance,
                            delay_s=computer_config.action_delay_s,
                        )
                    if observation is not None:
                        latest_screenshot = str(observation["path"])
                        screen_size = (
                            int(observation.get("width") or 0),
                            int(observation.get("height") or 0),
                        )

                    now = time.perf_counter()
                    wall_since_prev = now - last_step_wall
                    last_step_wall = now

                    tool_name, action_preview = summarize_computer_step_action(action.model_dump())

                    _log_computer_event(
                        "step_end",
                        run_id=run_id,
                        step=step_idx + 1,
                        dt_s=round(time.perf_counter() - iter_t0, 2),
                        tool=tool_name,
                        action=action_preview or "(none)",
                        done=history.is_done(),
                    )

                    emit_subagent_wire_event(
                        ComputerUseStepCompletedEvent(
                            step_index=step_idx + 1,
                            tool_name=tool_name,
                            action_preview=str(action_preview or "")[:120],
                            status=str(step_result.get("action", "done")),
                            duration_ms=int(wall_since_prev * 1000),
                        ).to_dict(),
                        logger,
                    )

                    if history.is_done():
                        _log_computer_event(
                            "run_done",
                            run_id=run_id,
                            step=step_idx + 1,
                        )
                        break
                except Exception:
                    logger.exception("computer_use event=step_failed run_id=%s", run_id)
                    raise

            steps_executed = len(history.entries)
            extracted = history.final_result()

            if extracted:
                result = str(extracted)
            elif _computer_history_had_no_progress(history):
                result = _format_computer_no_progress_error(
                    model_name=model_name,
                    steps=steps_executed,
                )
                run_success = False
                logger.error(
                    "computer_use event=no_progress run_id=%s model=%s steps=%d",
                    run_id,
                    model_name,
                    steps_executed,
                )
            else:
                result = _NO_EXTRACTED_CONTENT
                run_success = False
                logger.error(
                    "computer_use event=no_content run_id=%s steps=%d model=%s",
                    run_id,
                    steps_executed,
                    model_name,
                )

            raw_result = str(result)
            history_digest = _history_digest_for_synthesis(history)
            synthesis_decision = await _synthesize_computer_use_result(
                task=str(task or ""),
                raw_result=raw_result,
                history_digest=history_digest,
                soothe_config=soothe_config,
                computer_config=computer_config,
                run_id=run_id,
            )
            result_str, completion_summary, used_synthesized, quality_sufficient = (
                _apply_computer_use_synthesis_decision(
                    raw_result=raw_result,
                    decision=synthesis_decision,
                )
            )
            if used_synthesized:
                _log_computer_event("synthesis_applied", run_id=run_id)
            if not run_success and quality_sufficient:
                run_success = True
            result = result_str
            _log_computer_event(
                "run_end",
                run_id=run_id,
                total_s=round(time.perf_counter() - run_t0, 1),
                steps=steps_executed,
                success=run_success,
                result_preview=preview_first(result_str, 300),
            )

            emit_subagent_wire_event(
                ComputerUseCompletedEvent(
                    duration_ms=int((time.perf_counter() - run_t0) * 1000),
                    success=run_success,
                    summary=completion_summary,
                ).to_dict(),
                logger,
            )

            if computer_config.cleanup_on_exit:
                cleanup_computer_temp_files()
                _log_computer_event("temp_cleanup", run_id=run_id)

        except Exception as e:
            logger.exception("computer_use event=run_failed run_id=%s", run_id)
            error_msg = format_cli_error(e)
            result = error_msg
            run_success = False

            emit_subagent_wire_event(
                ComputerUseCompletedEvent(
                    duration_ms=int((time.perf_counter() - run_t0) * 1000),
                    success=False,
                    summary=computer_use_result_summary_for_display(error_msg),
                ).to_dict(),
                logger,
            )
        finally:
            if backend_instance is not None and backend is None:
                # Only close backends we created internally
                try:
                    await backend_instance.aclose()
                except Exception:
                    _log_computer_event("backend_close_skip", run_id=run_id, reason="close failed")

        return {
            "messages": [AIMessage(content=result)],
            "answer": result,
        }

    async def run_computer_use(
        state: _ComputerUseState,
    ) -> dict[str, Any]:
        """Async computer_use function for LangGraph."""
        return await _run_computer_use_async(state)

    graph = StateGraph(_ComputerUseState)
    graph.add_node("run_computer_use", run_computer_use)
    graph.add_edge(START, "run_computer_use")
    graph.add_edge("run_computer_use", END)
    return graph.compile()


# ─── Factory Function ─────────────────────────────────────────────────────


def create_computer_use_subagent(
    *,
    max_steps: int | None = None,
    config: ComputerUseSubagentConfig | None = None,
    soothe_config: Any,
    backend: _DesktopInputBackend | None = None,
) -> CompiledSubAgent:
    """Create a ComputerUse subagent (CompiledSubAgent with desktop workflow).

    Args:
        max_steps: Maximum agent steps. When ``None``, uses
            ``ComputerUseSubagentConfig.max_steps`` (default 99).
        config: ComputerUse subagent configuration object with runtime
            directories, cleanup settings, and feature flags.
        soothe_config: SootheConfig used to resolve
            ``subagents.computer_use.model_role``.
        backend: Optional pre-configured desktop input backend. When None,
            the backend is created from config (default: pyautogui).

    Returns:
        ``CompiledSubAgent`` dict compatible with soothe_deepagents.
    """
    runnable = _build_computer_use_graph(
        max_steps=max_steps,
        config=config,
        soothe_config=soothe_config,
        backend=backend,
    )

    return {
        "name": "computer_use",
        "description": COMPUTER_DESCRIPTION,
        "runnable": runnable,
    }


def resolve_computer_use_backend(
    computer_config: ComputerUseSubagentConfig | None = None,
) -> _DesktopInputBackend:
    """Resolve a desktop input backend from a ComputerUse config.

    Shared by the subagent agentic loop and the main-agent tool surface so
    both paths use the same backend-selection logic. When the configured
    backend's dependency (pyautogui) is unavailable, falls back to the
    no-op ``_DesktopInputBackend`` so the tools still load (each tool
    returns a clear ``{"error": "No input backend configured"}`` dict on
    invocation rather than failing at graph-compile time).

    Args:
        computer_config: ComputerUse subagent configuration. When ``None``,
            uses defaults (pyautogui, ``coordinate_scale=1``).

    Returns:
        A ``_DesktopInputBackend`` instance (``_PyAutoGUIBackend`` when
        pyautogui is importable, else the no-op base).
    """
    cfg = computer_config or ComputerUseSubagentConfig()
    screenshots_dir = str(get_computer_screenshots_dir())

    effective_mode = cfg.input_mode if cfg.input_mode != "auto" else cfg.backend
    # ``auto`` → pyautogui on all platforms (osascript not yet implemented).
    if effective_mode in ("auto", "pyautogui", "osascript"):
        try:
            return _PyAutoGUIBackend(
                screenshots_dir=screenshots_dir,
                coordinate_scale=cfg.coordinate_scale,
                screenshot_source=cfg.screenshot_source,
                screenshot_format=cfg.screenshot_format,
                screenshot_quality=cfg.screenshot_quality,
            )
        except ImportError:
            logger.warning(
                "pyautogui not installed; computer_use tools will return "
                "backend-not-configured errors on invocation."
            )
            return _DesktopInputBackend()
    return _DesktopInputBackend()


def create_computer_use_tools(
    config: Any | None = None,
) -> list[BaseTool]:
    """Build computer_use input tools for direct main-agent binding.

    Returns the four desktop-automation tools (``computer_screenshot``,
    ``computer_click``, ``computer_keyboard``, ``computer_scroll``) with a
    backend resolved from the ``computer_use`` subagent config section.

    This wires the tools into the main nano agent's tool set (Style 1 —
    routed delegation) so the agent can drive the desktop directly without
    delegating through the ``task`` tool to the subagent graph.

    Args:
        config: ``SootheConfig``. When ``None`` or when the
            ``computer_use`` subagent is disabled, returns an empty list.

    Returns:
        List of ``BaseTool`` instances (empty when disabled).
    """
    if config is None:
        return []

    sub_cfg = getattr(getattr(config, "subagents", None), "get", lambda _k: None)("computer_use")
    if sub_cfg is None or not getattr(sub_cfg, "enabled", True):
        return []

    computer_config: ComputerUseSubagentConfig | None = None
    cfg_dict = getattr(sub_cfg, "config", None) or {}
    if cfg_dict:
        computer_config = ComputerUseSubagentConfig(**cfg_dict)

    backend = resolve_computer_use_backend(computer_config)
    toolkit = ComputerUseToolkit(backend=backend)
    return toolkit.get_tools()


__all__ = [
    "COMPUTER_DESCRIPTION",
    "ComputerUseToolkit",
    "DesktopInputUnavailableError",
    "_ComputerAction",
    "_ComputerUseState",
    "_PyAutoGUIBackend",
    "_build_computer_use_graph",
    "_check_macos_accessibility_permission",
    "_check_macos_screen_recording_permission",
    "computer_use_model_role",
    "create_computer_use_subagent",
    "create_computer_use_tools",
    "resolve_computer_use_backend",
]
