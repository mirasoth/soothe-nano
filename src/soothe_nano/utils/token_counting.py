"""Token counting utilities with model-aware tokenizer selection.

`count_tokens` delegates to the Rust tiktoken-rs extension via PyO3.
When ``use_tiktoken=False``, returns ``len(text) // 4`` estimation.
"""

from __future__ import annotations

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


def count_tokens(
    text: str,
    *,
    model: str | None = None,
    use_tiktoken: bool = True,
) -> int:
    """Count tokens using the Rust tiktoken-rs extension.

    Args:
        text: Text to count tokens for.
        model: Optional model name hint for encoding selection. GPT-4o/o1/o3
            models use ``o200k_base``; all others use ``cl100k_base`` as a
            documented approximation for Claude/Gemini/local models.
        use_tiktoken: When ``False``, returns ``len(text) // 4`` estimation.

    Returns:
        Token count.
    """
    from soothe_nano._rust_compat import count_tokens_rust

    return count_tokens_rust(text, model, use_tiktoken)
