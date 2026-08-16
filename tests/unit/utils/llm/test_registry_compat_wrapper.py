"""Tests for provider-capability resolution (replaces old compat-wrapper detection).

The old ``ProviderRegistry.requires_openai_compat_wrapper`` decided whether a
custom OpenAI-compatible endpoint (DashScope, oMLX, vLLM, LMStudio) needed the
``OpenAICompatModelWrapper`` adapter. The unified litellm adapter folds those
quirks into :class:`ProviderCapabilities` flags instead. The surviving decision
is ``supports_json_schema``: standard OpenAI honors ``response_format:
json_schema``; custom OpenAI-compatible endpoints do not, so structured output
falls back to ``function_calling`` / instructor.
"""

from __future__ import annotations

import pytest

from soothe_nano.config.models import ModelProviderConfig
from soothe_nano.config.settings import SootheConfig
from soothe_nano.llm.registry import ProviderRegistry


@pytest.mark.parametrize(
    ("api_base_url", "supports_json_schema"),
    [
        (None, True),
        ("https://api.openai.com/v1", True),
        ("http://100.75.70.86:9642/v1", False),
        ("http://localhost:1234/v1", False),
    ],
)
def test_supports_json_schema_for_openai_endpoints(
    api_base_url: str | None, supports_json_schema: bool
) -> None:
    """Custom (non-api.openai.com) OpenAI-compatible endpoints reject json_schema."""
    registry = ProviderRegistry(
        [
            ModelProviderConfig(
                name="local",
                provider_type="openai",
                api_base_url=api_base_url,
                api_key="test",
            )
        ]
    )
    caps = registry.provider_capabilities("local")
    assert caps.supports_json_schema is supports_json_schema


def test_supports_json_schema_anthropic_never_rejects() -> None:
    """Non-openai providers route structured output through their own path."""
    registry = ProviderRegistry(
        [
            ModelProviderConfig(
                name="anthropic",
                provider_type="anthropic",
                api_base_url="http://localhost:9999/v1",
                api_key="test",
            )
        ]
    )
    caps = registry.provider_capabilities("anthropic")
    assert caps.supports_json_schema is True


def test_factory_builds_chat_litellm_model_for_custom_openai_endpoint() -> None:
    """A custom OpenAI-compatible endpoint yields a single ``ChatLitellmModel``.

    Replaces the old assertion that ``model._model`` was an
    ``OpenAICompatModelWrapper``: the unified adapter IS the model, so the
    capabilities (json_schema fallback, thinking strip) are read directly.
    """
    from soothe_nano.llm.factory import LLMFactory
    from soothe_nano.llm.provider import ChatLitellmModel

    config = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="omlx",
                provider_type="openai",
                api_base_url="http://127.0.0.1:9642/v1",
                api_key="test",
            )
        ],
        router_profiles=[
            {
                "name": "test",
                "router": {"default": "omlx:test-model"},
            }
        ],
        active_router_profile="test",
    )

    factory = LLMFactory(config)
    # Patch the litellm call path (not init_chat_model, which no longer exists).
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "soothe_nano.llm.provider.litellm"
    ) as _mock_litellm:
        model = factory.create_chat_model("default")

    assert isinstance(model, ChatLitellmModel)
    # Custom endpoint -> json_schema not supported; streaming flag from config.
    assert model.capabilities.supports_json_schema is False
