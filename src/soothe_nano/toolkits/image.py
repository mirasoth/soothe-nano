"""Image analysis toolkit using the ``image`` model role.

Accepts local image paths, enforces a MIME allowlist and 20 MiB size cap,
and builds OpenAI-compatible ``image_url`` data URIs for the vision model.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import Field
from soothe_sdk.plugin import plugin

from soothe_nano.toolkits._internal.local_path_resolution import resolve_toolkit_local_path

logger = logging.getLogger(__name__)

# 20 MiB cap on image payload size.
_MAX_IMAGE_BYTES = 20 * 1024 * 1024

_ALLOWED_MIME: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/bmp",
    }
)
_MIME_ALIASES: dict[str, str] = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
}

# Align with soothe_daemon.services.intent_hint_turn._DEFAULT_VISION_INSTRUCTION.
_DEFAULT_VISION_INSTRUCTION = "Describe the attached image(s) and answer any implied questions."

_EMPTY_REPLY_FALLBACK = "(Image model returned empty content.)"

_SUFFIX_TO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def normalize_mime_type(mime: str) -> str | None:
    """Return canonical image MIME or None if unsupported."""
    cleaned = mime.strip().lower()
    if cleaned in _MIME_ALIASES:
        cleaned = _MIME_ALIASES[cleaned]
    return cleaned if cleaned in _ALLOWED_MIME else None


def mime_for_path(path: Path) -> str | None:
    """Guess and normalize MIME type from a filesystem path."""
    suffix = path.suffix.lower()
    if suffix in _SUFFIX_TO_MIME:
        return _SUFFIX_TO_MIME[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    if not guessed:
        return None
    return normalize_mime_type(guessed)


def _local_path_or_error(image_path: str, config: Any) -> Path | str:
    """Resolve local path for image tools; return error string on failure."""
    try:
        return resolve_toolkit_local_path(image_path, config=config)
    except ValueError as e:
        return f"Error: {e}"


def _build_multimodal_message(*, instruction: str, mime: str, b64: str) -> HumanMessage:
    """Build daemon-compatible multimodal HumanMessage."""
    return HumanMessage(
        content=[
            {"type": "text", "text": instruction},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            },
        ]
    )


def _prepare_image(
    image_path: str,
    question: str,
    config: Any,
) -> tuple[str, str, str] | str:
    """Resolve and validate image; return (mime, b64, instruction) or error."""
    secured = _local_path_or_error(image_path, config)
    if isinstance(secured, str):
        return secured

    if not secured.is_file():
        return f"Error: Image not found: {secured}"

    mime = mime_for_path(secured)
    if mime is None:
        return (
            f"Error: Unsupported image format '{secured.suffix}'. "
            f"Supported: {', '.join(sorted(_SUFFIX_TO_MIME))}"
        )

    try:
        raw = secured.read_bytes()
    except OSError as exc:
        return f"Error: Failed to read image: {exc}"

    if len(raw) > _MAX_IMAGE_BYTES:
        return f"Error: Image exceeds maximum size ({_MAX_IMAGE_BYTES} bytes)"

    if config is None:
        return "Error: SootheConfig is required to analyze images."

    instruction = (question or "").strip() or _DEFAULT_VISION_INSTRUCTION
    b64 = base64.b64encode(raw).decode("ascii")
    return mime, b64, instruction


async def _invoke_image_model(
    *,
    mime: str,
    b64: str,
    instruction: str,
    config: Any,
) -> str:
    """Call the image-role model under LLM call policy."""
    from soothe_nano.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )

    try:
        model = config.create_chat_model("image")
    except Exception as exc:
        logger.exception("Failed to create image-role model")
        return f"Error: Failed to create image model: {exc}"

    msg = _build_multimodal_message(instruction=instruction, mime=mime, b64=b64)

    async def _call() -> Any:
        return await model.ainvoke([msg])

    try:
        response = await await_with_llm_call_policy(
            _call,
            config=llm_rate_limit_config_from(config),
        )
    except Exception as exc:
        logger.exception("Image analysis failed")
        return f"Error: Image analysis failed: {exc}"

    summary = str(getattr(response, "content", response) or "").strip()
    return summary if summary else _EMPTY_REPLY_FALLBACK


class AnalyzeImageTool(BaseTool):
    """Analyze an image file with the configured ``image`` model role."""

    name: str = "analyze_image"
    description: str = (
        "Analyze an image with a vision model. "
        "Use for: describing screenshots, reading charts/diagrams, answering "
        "questions about image content. "
        "Parameters: image_path (required), question (optional). "
        "Returns: text description or answer from the image model."
    )

    config: Any = Field(default=None, exclude=True)

    def _run(self, image_path: str, question: str = "") -> str:
        """Sync analyze (drives async path when no event loop is running)."""
        prepared = _prepare_image(image_path, question, self.config)
        if isinstance(prepared, str):
            return prepared
        mime, b64, instruction = prepared

        async def _call() -> str:
            return await _invoke_image_model(
                mime=mime,
                b64=b64,
                instruction=instruction,
                config=self.config,
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_call())

        msg = "AnalyzeImageTool._run cannot be called from a running event loop; use _arun"
        raise RuntimeError(msg)

    async def _arun(self, image_path: str, question: str = "") -> str:
        """Async analyze using the image-role model."""
        prepared = _prepare_image(image_path, question, self.config)
        if isinstance(prepared, str):
            return prepared
        mime, b64, instruction = prepared
        return await _invoke_image_model(
            mime=mime,
            b64=b64,
            instruction=instruction,
            config=self.config,
        )


class ImageToolkit:
    """Toolkit for image understanding via the ``image`` model role."""

    def __init__(self, *, config: Any = None) -> None:
        """Initialize the toolkit.

        Args:
            config: Optional SootheConfig for path sandboxing and model creation.
        """
        self._config = config

    def get_tools(self) -> list[BaseTool]:
        """Return analyze_image tool instances."""
        return [AnalyzeImageTool(config=self._config)]


@plugin(
    name="image",
    version="1.0.0",
    description="Image understanding via the image model role",
    trust_level="built-in",
)
class ImagePlugin:
    """Image analysis tools plugin."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools with config.

        Args:
            context: Plugin context with config and logger.
        """
        toolkit = ImageToolkit(config=context.soothe_config)
        self._tools = toolkit.get_tools()
        context.logger.info("Loaded %d image tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools."""
        return self._tools
