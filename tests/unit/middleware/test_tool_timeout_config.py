"""Per-tool timeout defaults for the vision tools.

``analyze_image`` / ``extract_text_from_image`` wrap a full multimodal model
call that routinely exceeds the 60s middleware default on large images; the
config ships 180s overrides so the calls are not killed mid-loop.
"""

from soothe_deepagents.middleware.tool_timeout import ToolTimeoutMiddleware

from soothe_nano.config.models import ToolTimeoutConfig

_VISION_TOOLS = ("analyze_image", "extract_text_from_image")
_VISION_TIMEOUT_SECONDS = 180.0


def test_vision_tools_have_per_tool_timeout_defaults() -> None:
    config = ToolTimeoutConfig()

    for tool in _VISION_TOOLS:
        assert config.per_tool.get(tool) == _VISION_TIMEOUT_SECONDS


def test_vision_per_tool_overrides_beat_the_default() -> None:
    config = ToolTimeoutConfig()
    middleware = ToolTimeoutMiddleware(
        default_timeout_seconds=config.default_seconds,
        per_tool_timeout_seconds=dict(config.per_tool),
        max_timeout_seconds=18000.0,
    )

    for tool in _VISION_TOOLS:
        assert middleware._resolve_timeout(tool, {}) == _VISION_TIMEOUT_SECONDS


def test_unlisted_tools_still_use_the_default() -> None:
    config = ToolTimeoutConfig()
    middleware = ToolTimeoutMiddleware(
        default_timeout_seconds=config.default_seconds,
        per_tool_timeout_seconds=dict(config.per_tool),
    )

    assert middleware._resolve_timeout("some_other_tool", {}) == config.default_seconds == 60.0
