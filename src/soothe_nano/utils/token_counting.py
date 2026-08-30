"""Token counting utilities with model-aware tokenizer selection.

`count_tokens` accepts an optional `model` hint and selects the encoding via
`tiktoken.encoding_for_model` for OpenAI models, falls back to `cl100k_base`
for Claude/Gemini/local models whose native tokenizers aren't in tiktoken,
and uses `len // 4` only behind a genuine import failure.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

ComplexityLevel = Literal["simple", "medium", "complex"]  # Simplified: merged trivial into simple


def estimate_content_chars(content: Any) -> int:
    """Best-effort character count for message content (string or blocks)."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, str):
                total += len(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    total += len(text)
                else:
                    total += len(str(block))
            else:
                total += len(str(block))
        return total
    return len(str(content))


@lru_cache(maxsize=32)
def _get_encoding_for_model(model: str | None) -> Any:
    """Return a cached tiktoken encoding for the given model hint.

    Selection order:
    1. `tiktoken.encoding_for_model(model)` for OpenAI-family models
       (gpt-4*, gpt-3.5-turbo, o1*, etc.).
    2. `cl100k_base` as a documented approximation for Claude / Gemini /
       local models whose native tokenizers are not available via tiktoken.
    3. `cl100k_base` when no model hint is provided (preserves the prior
       default behavior).
    """
    import tiktoken

    if model:
        try:
            return tiktoken.encoding_for_model(model)
        except Exception:
            # Unknown / non-OpenAI model (Claude, Gemini, local). Their
            # native tokenizers are not in tiktoken; cl100k_base is the
            # best-available approximation. This is a documented caveat,
            # not false precision.
            return tiktoken.get_encoding("cl100k_base")
    return tiktoken.get_encoding("cl100k_base")


@lru_cache(maxsize=8)
def _get_default_encoding() -> Any:
    """Return the cached default (cl100k_base) tiktoken encoding."""
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def count_tokens(
    text: str,
    *,
    model: str | None = None,
    use_tiktoken: bool = True,
) -> int:
    """Count tokens using offline tokenizers.

    Priority:
    1. tiktoken with model-aware encoding selection (most accurate)
    2. Estimation (len // 4) as fallback - zero dependency

    Args:
        text: Text to count tokens for.
        model: Optional model name hint for encoding selection. When provided
            and the model is in the OpenAI family, `tiktoken.encoding_for_model`
            selects the exact encoding. For Claude / Gemini / local models
            whose native tokenizers are not in tiktoken, `cl100k_base` is
            used as a documented approximation. `None` preserves the prior
            default (`cl100k_base`).
        use_tiktoken: Try to use tiktoken if available (default: True).

    Returns:
        Estimated token count.

    Examples:
        >>> count_tokens("Hello world")  # With tiktoken
        2
        >>> count_tokens("Hello world", use_tiktoken=False)
        3  # Estimation: len("Hello world") // 4
    """
    # Try tiktoken first (most accurate offline)
    if use_tiktoken:
        try:
            encoding = _get_encoding_for_model(model)
            return len(encoding.encode(text))
        except ImportError:
            pass  # Fall through to estimation

    # Fallback: simple estimation (very fast)
    return len(text) // 4
