"""Unit tests for analyze_image toolkit (daemon-aligned vision)."""

from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_nano.toolkits.image import (
    AnalyzeImageTool,
    ImageToolkit,
    _DEFAULT_VISION_INSTRUCTION,
    _EMPTY_REPLY_FALLBACK,
    mime_for_path,
    normalize_mime_type,
)


def _tiny_png(path: Path) -> Path:
    # Minimal 1x1 PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    path.write_bytes(png)
    return path


class TestMimeHelpers:
    def test_normalize_aliases(self) -> None:
        assert normalize_mime_type("image/jpg") == "image/jpeg"
        assert normalize_mime_type("image/pjpeg") == "image/jpeg"
        assert normalize_mime_type("image/png") == "image/png"
        assert normalize_mime_type("image/heic") is None

    def test_mime_for_path_by_suffix(self) -> None:
        assert mime_for_path(Path("x.PNG")) == "image/png"
        assert mime_for_path(Path("x.jpg")) == "image/jpeg"
        assert mime_for_path(Path("x.txt")) is None


class TestAnalyzeImageValidation:
    @pytest.fixture
    def tool(self) -> AnalyzeImageTool:
        return AnalyzeImageTool(config=None)

    def test_missing_file(self, tool: AnalyzeImageTool) -> None:
        result = tool._run("/nonexistent/path/image.png")
        assert result.startswith("Error:")
        assert "not found" in result.lower() or "Image not found" in result

    def test_unsupported_format(self, tool: AnalyzeImageTool) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notes.txt"
            path.write_text("hello")
            result = tool._run(str(path))
            assert "Unsupported image format" in result

    def test_oversized_file(self, tool: AnalyzeImageTool) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _tiny_png(Path(tmpdir) / "big.png")
            with patch("soothe_nano.toolkits.image._MAX_IMAGE_BYTES", 1):
                # config None fails after size check? size is checked before config
                result = tool._run(str(path))
            assert "exceeds maximum size" in result

    def test_requires_config_for_valid_image(self, tool: AnalyzeImageTool) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _tiny_png(Path(tmpdir) / "ok.png")
            result = tool._run(str(path))
            assert "SootheConfig is required" in result


class TestAnalyzeImageInvoke:
    def test_invokes_image_role_with_image_url_and_default_instruction(self) -> None:
        response = MagicMock()
        response.content = "A red pixel"

        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=response)

        config = MagicMock()
        config.create_chat_model = MagicMock(return_value=model)

        tool = AnalyzeImageTool(config=config)

        async def _passthrough(factory: Any, **_kwargs: Any) -> Any:
            return await factory()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = _tiny_png(Path(tmpdir) / "ok.png")
            with patch(
                "soothe_nano.utils.llm.invoke_policy.await_with_llm_call_policy",
                side_effect=_passthrough,
            ):
                result = asyncio.run(tool._arun(str(path), question=""))

        assert result == "A red pixel"
        config.create_chat_model.assert_called_once_with("image")
        model.ainvoke.assert_awaited_once()
        messages = model.ainvoke.await_args.args[0]
        assert len(messages) == 1
        content = messages[0].content
        assert content[0] == {"type": "text", "text": _DEFAULT_VISION_INSTRUCTION}
        assert content[1]["type"] == "image_url"
        url = content[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    def test_uses_custom_question(self) -> None:
        response = MagicMock()
        response.content = "answer"
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=response)
        config = MagicMock()
        config.create_chat_model = MagicMock(return_value=model)
        tool = AnalyzeImageTool(config=config)

        async def _passthrough(factory: Any, **_kwargs: Any) -> Any:
            return await factory()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = _tiny_png(Path(tmpdir) / "ok.png")
            with patch(
                "soothe_nano.utils.llm.invoke_policy.await_with_llm_call_policy",
                side_effect=_passthrough,
            ):
                asyncio.run(tool._arun(str(path), question="What color?"))

        content = model.ainvoke.await_args.args[0][0].content
        assert content[0]["text"] == "What color?"

    def test_empty_model_content_fallback(self) -> None:
        response = MagicMock()
        response.content = "   "
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=response)
        config = MagicMock()
        config.create_chat_model = MagicMock(return_value=model)
        tool = AnalyzeImageTool(config=config)

        async def _passthrough(factory: Any, **_kwargs: Any) -> Any:
            return await factory()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = _tiny_png(Path(tmpdir) / "ok.png")
            with patch(
                "soothe_nano.utils.llm.invoke_policy.await_with_llm_call_policy",
                side_effect=_passthrough,
            ):
                result = asyncio.run(tool._arun(str(path), question="q"))

        assert result == _EMPTY_REPLY_FALLBACK


class TestImageToolkitResolve:
    def test_toolkit_exposes_analyze_image(self) -> None:
        tools = ImageToolkit(config=MagicMock()).get_tools()
        assert [t.name for t in tools] == ["analyze_image"]

    def test_resolver_dispatches_image_group(self) -> None:
        from soothe_nano.resolve._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("image", config=MagicMock())
        assert [t.name for t in tools] == ["analyze_image"]

    def test_resolver_dispatches_analyze_image_name(self) -> None:
        from soothe_nano.resolve._resolver_tools import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("analyze_image", config=MagicMock())
        assert [t.name for t in tools] == ["analyze_image"]
