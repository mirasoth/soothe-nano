"""`LLMFactory` — create and cache `ChatLitellmModel` instances by router role or explicit spec."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel

from soothe_nano.llm.provider import ChatLitellmModel, MultiModelChatModel
from soothe_nano.llm.registry import ProviderRegistry
from soothe_nano.llm.types import ModelRole

if TYPE_CHECKING:
    from soothe_nano.config.settings import SootheConfig

logger = logging.getLogger(__name__)

_model_cache_lock = threading.Lock()


class LLMFactory:
    """Create and cache :class:`ChatLitellmModel` instances by role or spec.

    Args:
        config: `SootheConfig` carrying `providers` and `router_profiles`.
    """

    def __init__(self, config: SootheConfig) -> None:
        """Initialize the factory with a resolved config.

        Args:
            config: `SootheConfig` with `providers` and `router_profiles`.
        """
        self._config = config
        self._registry = ProviderRegistry(config.providers)
        self._cache: dict[str, BaseChatModel] = {}

    @property
    def registry(self) -> ProviderRegistry:
        """Expose the provider registry (for capability lookups)."""
        return self._registry

    def create_chat_model(
        self,
        role: ModelRole = "default",
        *,
        fallback_role: ModelRole | None = None,
    ) -> BaseChatModel:
        """Create a chat model for a router role with caching.

        Single-spec roles return a ``ChatLitellmModel``; multi-spec roles
        (``;``-separated) return a ``MultiModelChatModel`` with random
        selection and per-call failover.
        """
        specs = self._config.resolve_model_specs(role)
        if not specs:
            if fallback_role is not None:
                specs = self._config.resolve_model_specs(fallback_role)
            elif role != "default":
                specs = self._config.resolve_model_specs("default")
            if not specs:
                msg = f"No model spec for role '{role}' in active router profile"
                raise ValueError(msg)

        try:
            return self._create_from_specs(specs)
        except Exception:
            if fallback_role is not None:
                fb_specs = self._config.resolve_model_specs(fallback_role)
                if fb_specs and fb_specs != specs:
                    return self._create_from_specs(fb_specs)
            if role != "default":
                fb_specs = self._config.resolve_model_specs("default")
                if fb_specs and fb_specs != specs:
                    logger.warning(
                        "Failed to create model for role '%s'; falling back to default",
                        role,
                        exc_info=True,
                    )
                    return self._create_from_specs(fb_specs)
            raise

    def _create_from_specs(self, specs: list[str]) -> BaseChatModel:
        """Build a model from specs — single returns ``ChatLitellmModel``,
        multi returns a cached ``MultiModelChatModel``.
        """
        if len(specs) == 1:
            return self._create_from_spec(specs[0], {})
        # Multi-spec: cache the wrapper under the joined spec string.
        cache_key = self._cache_key(";".join(specs), {})
        with _model_cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
            models = [self._create_from_spec(spec, {}) for spec in specs]
            wrapper = MultiModelChatModel(models=models)
            self._cache[cache_key] = wrapper
            logger.debug("Created and cached MultiModelChatModel for %d specs", len(specs))
        return wrapper

    def create_chat_model_for_spec(
        self,
        model_spec: str,
        model_params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create a model from an explicit `provider:model` string."""
        spec_str = (model_spec or "").strip()
        if not spec_str:
            msg = "model_spec is required for create_chat_model_for_spec"
            raise ValueError(msg)
        return self._create_from_spec(spec_str, model_params or {})

    def _parse_spec(self, spec: str) -> tuple[str, str]:
        """Split a `provider:model` spec into `(provider_name, model_name)`."""
        if ":" not in spec:
            msg = f"model spec '{spec}' must be 'provider:model'"
            raise ValueError(msg)
        provider_name, model_name = spec.split(":", 1)
        return provider_name.strip(), model_name.strip()

    def _cache_key(self, spec: str, params: dict[str, Any]) -> str:
        import json

        return f"{spec}:{json.dumps(params, sort_keys=True, default=str)}"

    def _create_from_spec(
        self,
        spec: str,
        params: dict[str, Any],
    ) -> BaseChatModel:
        """Parse spec, resolve provider, build (and cache) a `ChatLitellmModel`.

        Args:
            spec: `provider:model` string.
            params: Extra kwargs (temperature, etc.).

        Returns:
            A configured `ChatLitellmModel`.

        Raises:
            ValueError: If spec is empty.
        """
        spec_str = (spec or "").strip()
        if not spec_str:
            msg = "model_spec is required for create_chat_model_for_spec"
            raise ValueError(msg)
        cache_key = self._cache_key(spec_str, params)
        with _model_cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

            provider_name, model_name = self._parse_spec(spec_str)
            resolved = self._registry.resolve(provider_name, model_name)
            streaming = resolved.capabilities.streaming and params.pop("streaming", True)
            model = ChatLitellmModel(
                model=resolved.litellm_model,
                api_base=resolved.api_base,
                api_key=resolved.api_key,
                capabilities=resolved.capabilities,
                temperature=params.pop("temperature", 0.7),
                streaming=streaming,
                model_kwargs=dict(params),
            )
            self._cache[cache_key] = model
            logger.debug("Created and cached litellm model for spec '%s'", spec_str)
        return model


__all__ = ["LLMFactory"]
