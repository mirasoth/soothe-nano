"""Tests for multimodal message construction."""

from __future__ import annotations

import base64

import pytest
from langchain_core.messages import HumanMessage

from soothe_nano.llm.multimodal import (
    ImageBytes,
    build_image_message,
    sniff_image_mime,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 8
GIF_BYTES = b"GIF89a" + b"\x00" * 8
BMP_BYTES = b"BM" + b"\x00" * 8
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG_BYTES, "image/png"),
        (JPEG_BYTES, "image/jpeg"),
        (GIF_BYTES, "image/gif"),
        (b"GIF87a" + b"\x00" * 8, "image/gif"),
        (BMP_BYTES, "image/bmp"),
        (WEBP_BYTES, "image/webp"),
        (b"NOTIMAGE" * 4, None),
        (b"", None),
    ],
)
def test_sniff_image_mime(data: bytes, expected: str | None) -> None:
    assert sniff_image_mime(data) == expected


def test_build_image_message_with_image_bytes() -> None:
    message = build_image_message("hello", [ImageBytes("image/png", PNG_BYTES)])
    assert isinstance(message, HumanMessage)
    blocks = message.content
    assert isinstance(blocks, list)
    assert blocks[0] == "hello"
    image_block = blocks[1]
    assert isinstance(image_block, dict)
    assert image_block["type"] == "image_url"
    expected_url = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
    assert image_block["image_url"]["url"] == expected_url


def test_build_image_message_with_multiple_images() -> None:
    message = build_image_message(
        "",
        [ImageBytes("image/png", PNG_BYTES), ImageBytes("image/jpeg", JPEG_BYTES)],
    )
    blocks = message.content
    assert len(blocks) == 2
    assert all(isinstance(block, dict) for block in blocks)
    assert blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert blocks[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_image_message_with_path_sniffs_mime(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(PNG_BYTES)
    monkeypatch.chdir(tmp_path)

    message = build_image_message("describe", [Path("photo.png")])
    blocks = message.content
    assert blocks[0] == "describe"
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_build_image_message_with_unknown_magic_raises(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"NOTIMAGE" * 4)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="cannot determine image type"):
        build_image_message("describe", [Path("photo.png")])


def test_build_image_message_empty_text_omits_text_block() -> None:
    message = build_image_message("   ", [ImageBytes("image/bmp", BMP_BYTES)])
    blocks = message.content
    assert len(blocks) == 1
    assert isinstance(blocks[0], dict)
