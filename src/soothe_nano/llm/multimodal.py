"""Multimodal message construction for image-bearing LLM calls."""

from __future__ import annotations

import base64
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


class ImageBytes(NamedTuple):
    """A decoded image payload paired with its MIME type."""

    mime_type: str
    data: bytes


def sniff_image_mime(data: bytes) -> str | None:
    """Return the image MIME type detected from magic bytes, or None."""
    for signature, mime_type in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return mime_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _image_bytes_from_path(path: Path) -> ImageBytes:
    """Read a file and sniff its MIME from magic bytes (extensions not trusted)."""
    data = path.read_bytes()
    mime_type = sniff_image_mime(data)
    if mime_type is None:
        raise ValueError(f"cannot determine image type from file contents: {path}")
    return ImageBytes(mime_type=mime_type, data=data)


def build_image_message(text: str, images: Sequence[ImageBytes | Path]) -> HumanMessage:
    """Build a multimodal `HumanMessage` with text and base64 data-URL image blocks.

    Args:
        text: Text prompt; omitted from the content when empty.
        images: Decoded `ImageBytes` payloads or paths to image files
            (paths sniff MIME from magic bytes, not from extensions).

    Returns:
        A `HumanMessage` whose content is a list of text and `image_url` blocks.

    Raises:
        ValueError: When a `Path` input is not a sniffable image.
    """
    blocks: list[dict[str, str] | str] = []
    if text.strip():
        blocks.append(text)
    for image in images:
        if isinstance(image, Path):
            image = _image_bytes_from_path(image)
        encoded = base64.b64encode(image.data).decode("ascii")
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image.mime_type};base64,{encoded}"},
            }
        )
    return HumanMessage(content=blocks)
