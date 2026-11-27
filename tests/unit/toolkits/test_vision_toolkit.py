"""Tests for the vision toolkit (gating, validation, model call shape)."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from soothe_nano.toolkits.vision import (
    AnalyzeImageTool,
    ExtractTextFromImageTool,
    VisionToolkit,
    _resolve_image_file,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16

DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_FORMATS = ("png", "jpeg", "webp", "gif", "bmp")


def _make_config(
    *,
    enabled: bool = True,
    image_spec: str | None = "openai:vlm",
    ocr_spec: str | None = "openai:ocr",
    max_image_bytes: int = DEFAULT_MAX_BYTES,
    allowed_formats: tuple[str, ...] = DEFAULT_FORMATS,
) -> SimpleNamespace:
    """Build a duck-typed SootheConfig with vision gating and a model factory."""
    roles: list[str] = []

    def create_chat_model(role: str) -> SimpleNamespace:
        roles.append(role)
        return SimpleNamespace(role=role)

    return SimpleNamespace(
        tools=SimpleNamespace(
            vision=SimpleNamespace(
                enabled=enabled,
                image_role="image",
                ocr_role="ocr",
                max_image_bytes=max_image_bytes,
                allowed_formats=allowed_formats,
            )
        ),
        router=SimpleNamespace(image=image_spec, ocr=ocr_spec),
        create_chat_model=create_chat_model,
        _roles=roles,
    )


class _Recorder:
    """Capture ainvoke_traced calls and return a canned response."""

    def __init__(self, response_text: str = "model answer") -> None:
        self.response_text = response_text
        self.calls: list[dict] = []

    async def __call__(self, model: object, messages: list, **kwargs: object) -> object:
        self.calls.append({"model": model, "messages": messages, **kwargs})
        return SimpleNamespace(content=self.response_text)


def _write_image(tmp_path, rel_path: str, data: bytes) -> None:
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


class TestVisionToolkitGating:
    """Verify toolkit respects config and role gates."""

    def test_no_config_returns_empty(self) -> None:
        assert VisionToolkit(config=None).get_tools() == []

    def test_disabled_returns_empty(self) -> None:
        toolkit = VisionToolkit(config=_make_config(enabled=False))
        assert toolkit.get_tools() == []

    def test_both_roles_registers_both_tools(self) -> None:
        names = {t.name for t in VisionToolkit(config=_make_config()).get_tools()}
        assert names == {"analyze_image", "extract_text_from_image"}

    def test_missing_image_role_registers_only_ocr(self) -> None:
        config = _make_config(image_spec=None)
        names = {t.name for t in VisionToolkit(config=config).get_tools()}
        assert names == {"extract_text_from_image"}

    def test_missing_ocr_role_registers_only_analyze(self) -> None:
        config = _make_config(ocr_spec=None)
        names = {t.name for t in VisionToolkit(config=config).get_tools()}
        assert names == {"analyze_image"}

    def test_no_roles_returns_empty(self) -> None:
        config = _make_config(image_spec=None, ocr_spec=None)
        assert VisionToolkit(config=config).get_tools() == []


class TestImagePathValidation:
    """Verify workspace anchoring — path policy lives in the operation middleware."""

    def test_relative_path_anchors_to_workspace(self, tmp_path) -> None:
        _write_image(tmp_path, "input/attachments/a.png", PNG_BYTES)
        resolved = _resolve_image_file("input/attachments/a.png", tmp_path)
        assert resolved == (tmp_path / "input/attachments/a.png").resolve()

    def test_absolute_path_inside_workspace_resolves(self, tmp_path) -> None:
        _write_image(tmp_path, "a.png", PNG_BYTES)
        resolved = _resolve_image_file(str(tmp_path / "a.png"), tmp_path)
        assert resolved == (tmp_path / "a.png").resolve()

    def test_absolute_path_outside_workspace_resolves(self, tmp_path) -> None:
        """No toolkit-level boundary check — the middleware owns that policy."""
        outside = tmp_path.parent / "outside.png"
        outside.write_bytes(PNG_BYTES)
        resolved = _resolve_image_file(str(outside), tmp_path)
        assert resolved == outside.resolve()

    def test_missing_file_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="not a file"):
            _resolve_image_file("missing.png", tmp_path)


def _make_analyze_tool(config: SimpleNamespace, tmp_path, **fields) -> AnalyzeImageTool:
    return AnalyzeImageTool(config=config, workspace_root=str(tmp_path), **fields)


class TestAnalyzeImageExecution:
    """Verify analyze_image validation and model-call shape."""

    async def test_success_returns_model_text(self, tmp_path, monkeypatch) -> None:
        config = _make_config()
        _write_image(tmp_path, "input/attachments/a.png", PNG_BYTES)
        recorder = _Recorder("the answer")
        monkeypatch.setattr("soothe_nano.toolkits.vision.ainvoke_traced", recorder)

        tool = _make_analyze_tool(config, tmp_path)
        result = await tool.ainvoke({"image_path": "input/attachments/a.png", "question": "what?"})
        assert result == "the answer"
        assert config._roles == ["image"]

    async def test_message_shape_and_tracing_args(self, tmp_path, monkeypatch) -> None:
        config = _make_config()
        _write_image(tmp_path, "a.png", PNG_BYTES)
        recorder = _Recorder()
        monkeypatch.setattr("soothe_nano.toolkits.vision.ainvoke_traced", recorder)

        tool = _make_analyze_tool(config, tmp_path)
        await tool.ainvoke({"image_path": "a.png", "question": "read the gauge"})

        assert len(recorder.calls) == 1
        call = recorder.calls[0]
        assert call["purpose"] == "vision_tool"
        assert call["component"] == "toolkit.vision"
        assert call["soothe_config"] is config
        message = call["messages"][0]
        blocks = message.content
        assert blocks[0] == {"type": "text", "text": "read the gauge"}
        expected_url = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
        assert blocks[1]["image_url"]["url"] == expected_url

    async def test_default_prompt_without_question(self, tmp_path, monkeypatch) -> None:
        config = _make_config()
        _write_image(tmp_path, "a.png", PNG_BYTES)
        recorder = _Recorder()
        monkeypatch.setattr("soothe_nano.toolkits.vision.ainvoke_traced", recorder)

        tool = _make_analyze_tool(config, tmp_path)
        await tool.ainvoke({"image_path": "a.png"})
        assert (
            "Describe this image in detail" in recorder.calls[0]["messages"][0].content[0]["text"]
        )

    async def test_outside_path_processed_without_tool_level_boundary(
        self, tmp_path, monkeypatch
    ) -> None:
        """The toolkit does not boundary-check; policy is the middleware's job."""
        outside = tmp_path.parent / "outside.png"
        outside.write_bytes(PNG_BYTES)
        recorder = _Recorder("outside answer")
        monkeypatch.setattr("soothe_nano.toolkits.vision.ainvoke_traced", recorder)

        tool = _make_analyze_tool(_make_config(), tmp_path)
        result = await tool.ainvoke({"image_path": str(outside)})
        assert result == "outside answer"

    async def test_oversize_rejected(self, tmp_path) -> None:
        config = _make_config(max_image_bytes=8)
        _write_image(tmp_path, "big.png", PNG_BYTES)
        tool = _make_analyze_tool(config, tmp_path, max_image_bytes=8)
        result = await tool.ainvoke({"image_path": "big.png"})
        assert result.startswith("Error:")
        assert "exceeds maximum size" in result

    async def test_unknown_magic_rejected(self, tmp_path) -> None:
        _write_image(tmp_path, "fake.png", b"NOTIMAGE" * 4)
        tool = _make_analyze_tool(_make_config(), tmp_path)
        result = await tool.ainvoke({"image_path": "fake.png"})
        assert result.startswith("Error:")
        assert "cannot determine image type" in result

    async def test_disallowed_format_rejected(self, tmp_path) -> None:
        config = _make_config(allowed_formats=("png",))
        _write_image(tmp_path, "a.jpg", JPEG_BYTES)
        tool = _make_analyze_tool(config, tmp_path, allowed_formats=("png",))
        result = await tool.ainvoke({"image_path": "a.jpg"})
        assert result.startswith("Error:")
        assert "not allowed" in result

    async def test_extension_lies_magic_wins(self, tmp_path, monkeypatch) -> None:
        config = _make_config()
        _write_image(tmp_path, "a.png", JPEG_BYTES)
        recorder = _Recorder()
        monkeypatch.setattr("soothe_nano.toolkits.vision.ainvoke_traced", recorder)

        tool = _make_analyze_tool(config, tmp_path)
        await tool.ainvoke({"image_path": "a.png"})
        url = recorder.calls[0]["messages"][0].content[1]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")


class TestExtractTextExecution:
    """Verify extract_text_from_image routing and prompt."""

    async def test_ocr_role_and_prompt(self, tmp_path, monkeypatch) -> None:
        config = _make_config()
        _write_image(tmp_path, "a.png", PNG_BYTES)
        recorder = _Recorder("extracted text")
        monkeypatch.setattr("soothe_nano.toolkits.vision.ainvoke_traced", recorder)

        tool = ExtractTextFromImageTool(config=config, workspace_root=str(tmp_path))
        result = await tool.ainvoke({"image_path": "a.png", "language": "German"})
        assert result == "extracted text"
        assert config._roles == ["ocr"]
        text_block = recorder.calls[0]["messages"][0].content[0]
        assert "Extract all text" in text_block["text"]
        assert "German" in text_block["text"]


class TestResolverRegistration:
    """Verify the vision group is registered and Ask-mode safe."""

    def test_resolve_tools_includes_vision_group(self) -> None:
        from soothe_nano.utils.resolver import resolve_tools

        config = _make_config()
        tools = resolve_tools(config.tools, config=config)
        names = {t.name for t in tools}
        assert {"analyze_image", "extract_text_from_image"} <= names

    def test_resolver_dispatches_vision_group(self) -> None:
        from soothe_nano.utils.resolver import _resolve_single_tool_group_uncached

        tools = _resolve_single_tool_group_uncached("vision", _make_config())
        assert {t.name for t in tools} == {"analyze_image", "extract_text_from_image"}

    def test_vision_not_ask_mutating(self) -> None:
        from soothe_nano.agent.interaction_mode import ASK_MUTATING_TOOL_GROUPS

        assert "vision" not in ASK_MUTATING_TOOL_GROUPS

    def test_vision_not_sandbox_excluded(self) -> None:
        from soothe_nano.agent.interaction_mode import SANDBOX_EXCLUDED_TOOL_GROUPS

        assert "vision" not in SANDBOX_EXCLUDED_TOOL_GROUPS
