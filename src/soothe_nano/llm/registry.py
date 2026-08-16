"""Provider configuration lookup and litellm model-string resolution.

``ProviderRegistry`` holds provider configs from :class:`SootheConfig` and
resolves them to the ``(litellm_model, api_base, api_key, capabilities)``
tuple :class:`~soothe_nano.llm.provider.ChatLitellmModel` needs. Unlike the
old nano registry, there is no ``requires_openai_compat_wrapper`` — the
compatibility quirks (structured-output fallback, streaming self-heal,
thinking-token strip) become per-provider capability flags consumed directly
inside the litellm adapter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from soothe_nano.config.env import _resolve_provider_env
from soothe_nano.config.models import ModelProviderConfig
from soothe_nano.llm.types import ProviderType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderCapabilities:
    """Per-provider capability flags consumed by the litellm adapter.

    These replace the old wrapper-chain decisions: rather than stacking
    wrappers that intercept calls, the single ``ChatLitellmModel`` reads these
    flags and adjusts its litellm invocation accordingly.
    """

    supports_json_schema: bool = True
    """Provider honors ``response_format: json_schema`` natively. When False
    (DashScope GLM/Kimi thinking models), structured output falls back to
    instructor or ``function_calling``."""

    streaming: bool = True
    """Enable litellm streaming. False for servers whose streaming endpoint
    is broken (vLLM-Metal returns non-SSE JSON); routes through
    ``acompletion(stream=False)`` and the runtime auto-fallback still catches
    ``No generations found in stream`` and retries non-streaming."""

    hide_thinking_tokens: bool = True
    """Strip inline ``imd...</think>`` / ``<thinking>`` blocks from text."""

    max_tokens: int | None = None
    """Model-agnostic default generation cap for this provider."""


@dataclass(frozen=True)
class ResolvedProvider:
    """A fully resolved provider: litellm model string + endpoint + creds + caps."""

    litellm_model: str
    """litellm model string, e.g. ``openai/qwen3.6-flash`` or ``anthropic/claude-...``."""

    api_base: str | None = None
    api_key: str | None = None
    capabilities: ProviderCapabilities = ProviderCapabilities()


class ProviderRegistry:
    """Provider configuration lookup and litellm resolution.

    Holds provider configs and resolves credentials with ``${ENV_VAR}``
    expansion. Used by :class:`~soothe_nano.llm.factory.LLMFactory` to build
    ``ChatLitellmModel`` instances.
    """

    def __init__(self, providers: list[ModelProviderConfig]) -> None:
        """Initialize registry with provider configs.

        Args:
            providers: List of ModelProviderConfig from SootheConfig.
        """
        self._providers: dict[str, ModelProviderConfig] = {p.name: p for p in providers}

    def get_provider(self, name: str) -> ModelProviderConfig | None:
        """Lookup provider config by name."""
        return self._providers.get(name)

    def resolve_provider_type(self, name: str) -> ProviderType:
        """Detect provider type from config.

        Returns:
            ProviderType enum. ``CUSTOM`` if provider not found or type unknown.
        """
        provider = self.get_provider(name)
        if provider is None:
            return ProviderType.CUSTOM
        try:
            return ProviderType(provider.provider_type)
        except ValueError:
            logger.warning(
                "Unknown provider_type '%s' for provider '%s', treating as CUSTOM",
                provider.provider_type,
                name,
            )
            return ProviderType.CUSTOM

    @staticmethod
    def _litellm_prefix(provider_type: str, provider_name: str) -> str:
        """Map a config provider_type to a litellm model prefix.

        litellm routes providers via the model-string prefix (``openai/...``,
        ``anthropic/...``, ``ollama/...``, ``gemini/...``, ``groq/...``).
        Custom OpenAI-compatible endpoints (DashScope, oMLX, vLLM, agnes) use
        ``openai/`` + ``api_base`` override.
        """
        # Known native providers: the provider_type IS the litellm prefix.
        if provider_type in (
            "anthropic",
            "ollama",
            "gemini",
            "groq",
            "vertex_ai",
            "cohere",
            "mistral",
            "azure",
            "bedrock",
        ):
            return provider_type
        # openai / custom OpenAI-compatible — litellm uses ``openai/`` prefix
        # plus ``api_base`` for custom endpoints.
        return "openai"

    def provider_capabilities(self, name: str) -> ProviderCapabilities:
        """Compute capability flags for a provider.

        DashScope/oMLX/vLLM (non-standard OpenAI-compatible endpoints) often
        reject ``json_schema`` structured output and emit thinking tokens; this
        surfaces those constraints as flags rather than wrapper decisions.
        """
        provider = self.get_provider(name)
        if provider is None:
            return ProviderCapabilities()
        # ``json_schema`` is only safe on providers that explicitly honor it.
        # Custom OpenAI-compatible endpoints (non-api.openai.com base) default
        # to NOT supporting it — they return BadRequestError, so we fall back
        # to function_calling / instructor instead of failing.
        supports_json_schema = self._supports_json_schema(provider)
        return ProviderCapabilities(
            supports_json_schema=supports_json_schema,
            streaming=provider.streaming,
            hide_thinking_tokens=True,
            max_tokens=provider.max_tokens,
        )

    @staticmethod
    def _supports_json_schema(provider: ModelProviderConfig) -> bool:
        """Whether the provider honors ``response_format: json_schema``.

        Standard OpenAI: yes. Custom OpenAI-compatible endpoints (DashScope,
        oMLX, vLLM, LMStudio): no by default — they typically reject the
        ``json_schema`` response format, so structured output uses
        ``function_calling`` or instructor instead.
        """
        if provider.provider_type != "openai":
            # anthropic / ollama: handle via their own structured-output path.
            return True
        base = provider.api_base_url
        if not base:
            return True  # standard OpenAI
        resolved = _resolve_provider_env(
            base, provider_name=provider.name, field_name="api_base_url"
        )
        if not resolved:
            return True
        normalized = resolved.rstrip("/")
        return normalized.startswith("https://api.openai.com")

    def resolve(self, name: str, model_name: str) -> ResolvedProvider:
        """Resolve a ``provider:model`` spec to litellm call args.

        Args:
            name: Provider name from config.
            model_name: Model name (the part after ``:`` in a spec).

        Returns:
            :class:`ResolvedProvider` with litellm model string, endpoint,
            credentials, and capability flags.
        """
        provider = self.get_provider(name)
        provider_type_str = provider.provider_type if provider else "openai"
        prefix = self._litellm_prefix(provider_type_str, name)
        litellm_model = (
            f"{prefix}/{model_name}" if not model_name.startswith(prefix) else model_name
        )

        api_base: str | None = None
        api_key: str | None = None
        if provider:
            if provider.api_base_url:
                api_base = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
            if provider.api_key:
                api_key = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
        caps = self.provider_capabilities(name)
        return ResolvedProvider(
            litellm_model=litellm_model,
            api_base=api_base,
            api_key=api_key,
            capabilities=caps,
        )

    # ------------------------------------------------------------------
    # Back-compat shims used during the migration window.
    # ------------------------------------------------------------------

    def get_provider_kwargs(self, name: str) -> tuple[str, dict[str, Any]]:
        """Back-compat: build ``init_chat_model``-style kwargs for a provider.

        Kept so any consumer still calling the old factory path resolves
        credentials identically. Returns ``(provider_type_str, kwargs_dict)``
        where kwargs carries ``base_url``/``api_key``/``max_tokens``.
        """
        provider = self.get_provider(name)
        kwargs: dict[str, Any] = {}
        provider_type_str = name
        if provider:
            provider_type_str = provider.provider_type
            if provider.api_base_url:
                resolved = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                if resolved:
                    kwargs["base_url"] = resolved
            if provider.api_key:
                resolved = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
                if resolved:
                    kwargs["api_key"] = resolved
            if provider.max_tokens is not None:
                kwargs["max_tokens"] = provider.max_tokens
        return provider_type_str, kwargs

    def get_provider_streaming(self, name: str) -> bool:
        """Back-compat: return whether streaming is enabled for a provider."""
        provider = self.get_provider(name)
        if provider is None:
            return True
        return provider.streaming


__all__ = [
    "ProviderCapabilities",
    "ProviderRegistry",
    "ResolvedProvider",
]
