"""JSON parsing utilities for LLM responses.

Delegates to the Rust ``repair_json`` implementation which handles:
- Markdown fences
- Trailing commas
- Truncated output
- String-aware bracket matching
- BOM stripping
"""

from __future__ import annotations

import logging
from typing import Any

from soothe_nano._rust_compat import repair_json

logger = logging.getLogger(__name__)


def _load_llm_json_dict(response: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response string.

    Delegates to the Rust ``repair_json`` implementation which tolerates
    markdown fences, leading prose, trailing commas, and truncated output.

    Args:
        response: Raw LLM response string.

    Returns:
        Parsed JSON object as a dict.

    Raises:
        ValueError: If the response is empty or contains no parseable JSON.
        TypeError: If the JSON root is not an object.
    """
    result = repair_json(response)
    if isinstance(result, dict):
        return result
    if result is None:
        stripped = response.strip()
        if not stripped:
            raise ValueError("Empty LLM response — cannot parse JSON")
        raise TypeError("LLM JSON root must be an object")
    raise TypeError("LLM JSON root must be an object")
