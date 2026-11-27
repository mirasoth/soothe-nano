"""Vision toolkit: targeted image understanding and OCR as agent tools."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

from langchain_core.tools import BaseTool
from langchain_core.tools.base import InjectedToolArg
from pydantic import BaseModel, Field

from soothe_nano.config.models import (
    DEFAULT_VISION_ALLOWED_FORMATS,
    DEFAULT_VISION_MAX_IMAGE_BYTES,
)
from soothe_nano.llm import ainvoke_traced, llm_response_text
from soothe_nano.llm.multimodal import ImageBytes, build_image_message, sniff_image_mime
from soothe_nano.plugin import plugin
from soothe_nano.utils.tool_error_handler import tool_error_handler

try:
    from langchain.tools import ToolRuntime
except ImportError:  # pragma: no cover - optional at static analysis time
    ToolRuntime = Any  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_ANALYZE_PROMPT = (
    "Describe this image in detail: visible objects, text content, "
    "charts/diagrams, and spatial layout."
)

_DEFAULT_OCR_PROMPT = (
    "Extract all text visible in this image. Reproduce the text exactly, "
    "preserving reading order and line breaks."
)

_FORMAT_TO_MIME: dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}
_MIME_TO_FORMAT = {mime: fmt for fmt, mime in _FORMAT_TO_MIME.items()}


def _run_coro(coro: Awaitable[T]) -> T:
    """Run an async coroutine from a synchronous tool entrypoint."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if loop.is_running():
        logger.error("[Vision] sync tool invoked inside running event loop")
        raise RuntimeError(
            "Cannot run synchronous tool method inside an active asyncio event loop. "
            "Use async invocation instead."
        )
    return loop.run_until_complete(coro)


def _role_spec(config: Any, role: str) -> str | None:
    """Return the router model spec for *role*, or None when the role is unset."""
    resolve_router = getattr(config, "_resolve_router", None)
    router = resolve_router() if callable(resolve_router) else getattr(config, "router", None)
    return getattr(router, role, None) if router is not None else None


def _resolve_workspace(workspace_root: str, tool_runtime: Any = None) -> Path | None:
    """Resolve the effective workspace for vision tools."""
    from soothe_nano.workspace.workspace_policy import WorkspaceResolver

    resolved = WorkspaceResolver.resolve_tool_execution(
        runtime=tool_runtime,
        fallback=workspace_root or None,
    )
    return resolved


def _resolve_image_file(image_path: str, workspace: Path) -> Path:
    """Anchor *image_path* to *workspace* and require an existing file.

    Relative paths anchor to the workspace root. Path policy (workspace
    boundary, `security.allow_paths_outside_workspace`, denied/allowed paths)
    is enforced by the operation-security middleware like every other read
    tool; the toolkit itself only anchors and sniffs.
    """
    candidate = Path(image_path)
    full = candidate.resolve() if candidate.is_absolute() else (workspace / candidate).resolve()
    if not full.is_file():
        raise ValueError(f"image path is not a file: {image_path}")
    return full


def _read_image_bytes(path: Path, max_bytes: int) -> bytes:
    """Read image bytes, rejecting files larger than *max_bytes*."""
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"image exceeds maximum size ({size} bytes > {max_bytes} bytes): {path}")
    return path.read_bytes()


def _validate_image_payload(data: bytes, allowed_formats: tuple[str, ...]) -> ImageBytes:
    """Sniff the MIME from magic bytes and check it against the allowed formats."""
    mime_type = sniff_image_mime(data)
    if mime_type is None:
        raise ValueError("cannot determine image type from file contents (magic bytes)")
    fmt = _MIME_TO_FORMAT.get(mime_type)
    if fmt is None or fmt not in allowed_formats:
        raise ValueError(f"image format not allowed: {mime_type}")
    return ImageBytes(mime_type=mime_type, data=data)


def _create_chat_model(config: Any, role: str) -> Any:
    """Create the chat model for *role* via the config factory."""
    factory: Callable[..., Any] | None = getattr(config, "create_chat_model", None)
    if not callable(factory):
        raise RuntimeError(f"no create_chat_model available for vision role '{role}'")
    return factory(role)


async def _invoke_image_model(
    *,
    config: Any,
    image_path: str,
    prompt: str,
    role: str,
    workspace_root: str,
    max_image_bytes: int,
    allowed_formats: tuple[str, ...],
    runtime: Any = None,
) -> str:
    """Validate the image, build the multimodal message, and call the role model."""
    workspace = _resolve_workspace(workspace_root, runtime)
    if workspace is None:
        raise RuntimeError("no workspace available to resolve the image path")
    path = _resolve_image_file(image_path, workspace)
    payload = _validate_image_payload(_read_image_bytes(path, max_image_bytes), allowed_formats)
    message = build_image_message(prompt, [payload])
    model = _create_chat_model(config, role)
    response = await ainvoke_traced(
        model,
        [message],
        soothe_config=config,
        purpose="vision_tool",
        component="toolkit.vision",
        phase="tool-call",
    )
    return llm_response_text(response)


# Input schemas


class AnalyzeImageInput(BaseModel):
    """Arguments for `analyze_image`."""

    image_path: str = Field(..., description="Path to the image, relative to the workspace.")
    question: str | None = Field(
        None,
        description="Targeted question about the image (recommended).",
    )


class ExtractTextFromImageInput(BaseModel):
    """Arguments for `extract_text_from_image`."""

    image_path: str = Field(..., description="Path to the image, relative to the workspace.")
    language: str | None = Field(
        None,
        description="Expected language of the text in the image (hint for OCR).",
    )


# Tool classes


class AnalyzeImageTool(BaseTool):
    """Targeted image understanding via the ``image`` role model."""

    name: str = "analyze_image"
    description: str = (
        "Analyze an image file and answer a question about its contents "
        "(objects, text, charts, layout, or any visual detail). "
        "Inputs: `image_path` (required, workspace-relative path, or any path when security.allow_paths_outside_workspace=true); "
        "`question` (recommended — the specific detail to answer). "
        "Read-only; does not modify the workspace. "
        "Cost: one targeted vision model call."
    )
    args_schema: type[BaseModel] = AnalyzeImageInput

    config: Any = Field(default=None, exclude=True)
    image_role: str = "image"
    workspace_root: str = Field(default="", description="Workspace path fallback")
    max_image_bytes: int = Field(default=DEFAULT_VISION_MAX_IMAGE_BYTES, gt=0)
    allowed_formats: tuple[str, ...] = Field(
        default_factory=lambda: tuple(DEFAULT_VISION_ALLOWED_FORMATS)
    )

    @tool_error_handler("analyze_image", return_type="str")
    async def _arun(
        self,
        image_path: str,
        question: str | None = None,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        """Answer a targeted question about an image file."""
        prompt = question.strip() if question and question.strip() else _DEFAULT_ANALYZE_PROMPT
        return await _invoke_image_model(
            config=self.config,
            image_path=image_path,
            prompt=prompt,
            role=self.image_role,
            workspace_root=self.workspace_root,
            max_image_bytes=self.max_image_bytes,
            allowed_formats=self.allowed_formats,
            runtime=runtime,
        )

    def _run(
        self,
        image_path: str,
        question: str | None = None,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        """Synchronous entrypoint; the model call runs on a fresh loop."""
        return _run_coro(
            self._arun(image_path, question, runtime=runtime)  # type: ignore[call-arg]
        )


class ExtractTextFromImageTool(BaseTool):
    """OCR text extraction from images via the ``ocr`` role model."""

    name: str = "extract_text_from_image"
    description: str = (
        "Extract all text visible in an image (OCR) and return it verbatim, "
        "preserving reading order and line breaks. "
        "Inputs: `image_path` (required, workspace-relative path, or any path when security.allow_paths_outside_workspace=true); "
        "`language` (optional hint for the expected text language). "
        "Read-only; does not modify the workspace. "
        "Cost: one OCR model call."
    )
    args_schema: type[BaseModel] = ExtractTextFromImageInput

    config: Any = Field(default=None, exclude=True)
    ocr_role: str = "ocr"
    workspace_root: str = Field(default="", description="Workspace path fallback")
    max_image_bytes: int = Field(default=DEFAULT_VISION_MAX_IMAGE_BYTES, gt=0)
    allowed_formats: tuple[str, ...] = Field(
        default_factory=lambda: tuple(DEFAULT_VISION_ALLOWED_FORMATS)
    )

    @tool_error_handler("extract_text_from_image", return_type="str")
    async def _arun(
        self,
        image_path: str,
        language: str | None = None,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        """Extract text from an image file."""
        prompt = _DEFAULT_OCR_PROMPT
        if language and language.strip():
            prompt = f"{prompt}\n\nThe text is expected to be in this language: {language.strip()}."
        return await _invoke_image_model(
            config=self.config,
            image_path=image_path,
            prompt=prompt,
            role=self.ocr_role,
            workspace_root=self.workspace_root,
            max_image_bytes=self.max_image_bytes,
            allowed_formats=self.allowed_formats,
            runtime=runtime,
        )

    def _run(
        self,
        image_path: str,
        language: str | None = None,
        *,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg()] = None,
    ) -> str:
        """Synchronous entrypoint; the model call runs on a fresh loop."""
        return _run_coro(
            self._arun(image_path, language, runtime=runtime)  # type: ignore[call-arg]
        )


# Toolkit + plugin


class VisionToolkit:
    """Build vision tools from Soothe config with role-based gating."""

    def __init__(self, *, config: Any | None = None) -> None:
        """Initialize with optional full Soothe config.

        Args:
            config: Loaded `SootheConfig`; when None, returns no tools.
        """
        self._config = config

    def get_tools(self) -> list[BaseTool]:
        """Return vision tools, or an empty list when disabled or roles are unset.

        Each tool registers only when its model role is configured on the
        router; the group degrades gracefully when no roles are set.
        """
        if self._config is None:
            logger.debug("VisionToolkit: no Soothe config; skipping vision tools")
            return []

        tools_cfg = getattr(getattr(self._config, "tools", None), "vision", None)
        if tools_cfg is None or not getattr(tools_cfg, "enabled", False):
            logger.debug("VisionToolkit: tools.vision.enabled is false")
            return []

        tools: list[BaseTool] = []
        if _role_spec(self._config, tools_cfg.image_role):
            tools.append(
                AnalyzeImageTool(
                    config=self._config,
                    image_role=tools_cfg.image_role,
                    max_image_bytes=tools_cfg.max_image_bytes,
                    allowed_formats=tuple(tools_cfg.allowed_formats),
                )
            )
        else:
            logger.debug(
                "VisionToolkit: router role '%s' unset; analyze_image not registered",
                tools_cfg.image_role,
            )
        if _role_spec(self._config, tools_cfg.ocr_role):
            tools.append(
                ExtractTextFromImageTool(
                    config=self._config,
                    ocr_role=tools_cfg.ocr_role,
                    max_image_bytes=tools_cfg.max_image_bytes,
                    allowed_formats=tuple(tools_cfg.allowed_formats),
                )
            )
        else:
            logger.debug(
                "VisionToolkit: router role '%s' unset; extract_text_from_image not registered",
                tools_cfg.ocr_role,
            )
        logger.info("VisionToolkit: registered %d vision tools", len(tools))
        return tools


@plugin(
    name="vision",
    version="1.0.0",
    description="Image understanding and OCR tools (image/ocr model roles)",
    trust_level="built-in",
)
class VisionPlugin:
    """Vision tools plugin."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Load tools from `soothe_config`."""
        soothe_config = getattr(context, "soothe_config", None)
        toolkit = VisionToolkit(config=soothe_config)
        self._tools = toolkit.get_tools()
        context.logger.info("Loaded %d vision tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Return tools loaded during `on_load`."""
        return self._tools
