"""Shared types and constants for the unified LLM module.

Re-exports the canonical model-role and provider-type definitions used across
the unified LLM layer. ``ModelRole`` is re-exported from :mod:`soothe_nano.config`
so config-driven router profiles and the factory share a single source of truth.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

# Re-exported from config for API convenience. Maps to router.* fields:
# - ``default``: Main orchestrator reasoning (CoreAgent, failure analysis).
# - ``fast``: Cheap/fast operations (intent classification, routing, memory extraction).
# - ``think``: Stronger reasoning (planning, consensus validation, backoff reasoning).
# - ``image``: Vision-capable model (image analysis, daemon vision preflight).
# - ``ocr``: Dedicated OCR / document text extraction model.
# - ``embedding``: Embedding model (MemU vector search, semantic memory).
ModelRole = Literal["default", "fast", "think", "image", "ocr", "embedding"]


class ProviderType(Enum):
    """Provider type for capability detection.

    Maps to ``ModelProviderConfig.provider_type`` in config YAML. Determines
    which capability flags (:meth:`ProviderRegistry.provider_capabilities`)
    are applied by :class:`~soothe_nano.llm.provider.ChatLitellmModel`.
    """

    OPENAI = "openai"
    """Standard OpenAI API with full compatibility.

    Supports all structured output methods (function_calling, json_schema,
    json_mode). Native ``tool_calls`` support. When ``api_base_url`` points at
    a non-standard endpoint (local oMLX, LMStudio, vLLM, DashScope), capability
    flags downgrade structured output to instructor fallback as needed.
    """

    ANTHROPIC = "anthropic"
    """Anthropic Claude API via litellm. Native tool_calls; json_schema via tools."""

    OLLAMA = "ollama"
    """Ollama local inference. OpenAI-compatible via litellm ``ollama/`` prefix."""

    CUSTOM = "custom"
    """Custom/unknown provider type. Treated as standard OpenAI-compatible."""


__all__ = [
    "ModelRole",
    "ProviderType",
]
