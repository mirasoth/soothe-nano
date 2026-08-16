"""Exceptions for the unified LLM module.

A single exception hierarchy shared by both the langchain adapter path and the
direct ``BaseLLMClient`` path: ``StructuredOutputError`` covers the structured
output fallback chain, and ``ContentPolicyError`` surfaces provider refusals.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for unified-LLM-layer errors."""


class StructuredOutputError(LLMError):
    """Raised when structured output cannot be produced after the fallback chain.

    The fallback chain (json_schema → function_calling → json_mode → instructor)
    in :mod:`soothe_nano.llm.structured` raises this when every method fails,
    so callers (planner, pass1/pass2 classifiers, step-deliverable LLM) can
    retry or fail-safe rather than receiving a bare ``Exception``.
    """


class ContentPolicyError(LLMError):
    """Raised when the provider refused the request due to a content policy.

    Non-retryable. Surfaced on the direct-client path so provider refusals are
    distinct from transient network/timeout errors.
    """


__all__ = [
    "ContentPolicyError",
    "LLMError",
    "StructuredOutputError",
]
