"""Exception hierarchy shared by the langchain adapter and direct LLM client paths."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for unified-LLM-layer errors."""


class StructuredOutputError(LLMError):
    """Raised when structured output cannot be produced after the fallback chain."""


class ContentPolicyError(LLMError):
    """Raised when the provider refused the request due to a content policy (non-retryable)."""


__all__ = [
    "ContentPolicyError",
    "LLMError",
    "StructuredOutputError",
]
