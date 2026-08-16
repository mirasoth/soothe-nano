"""Extract parseable text and JSON objects from provider AIMessage responses.

Ported from the former ``soothe_nano.utils.llm.response_text``. Depends on
:mod:`soothe_nano.llm.thinking` (the ported thinking filter).
"""

from __future__ import annotations

import json
import re
from typing import Any

from soothe_nano.llm.thinking import strip_thinking

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def text_from_message_content(content: Any) -> str:
    """Flatten AIMessage ``content`` (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type in ("text", "output_text"):
                    parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content)


def llm_response_text(response: Any) -> str:
    """Return parseable text from an AIMessage-like response.

    Thinking models may put JSON in ``additional_kwargs["reasoning_content"]``
    or list-style ``content`` blocks while leaving primary ``content`` empty.
    ``strip_thinking`` is applied so inline thinking blocks never surface.
    """
    if hasattr(response, "content") and response.content:
        return strip_thinking(text_from_message_content(response.content))
    kwargs = getattr(response, "additional_kwargs", None) or {}
    if isinstance(kwargs, dict):
        reasoning = kwargs.get("reasoning_content")
        if reasoning:
            return strip_thinking(str(reasoning))
    return str(response)


def parse_json_object(content: str) -> dict[str, Any] | None:
    """Parse a JSON object from model output (raw or markdown-fenced)."""
    text = (content or "").strip()
    if not text:
        return None

    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
    return None


__all__ = [
    "llm_response_text",
    "parse_json_object",
    "text_from_message_content",
    "_extract_json_str_from_response",
    "_strip_json_text",
]


# Back-compat alias: the old ``soothe_nano.utils.llm.wrappers._extract_json_str_from_response``
# extracted JSON text (content → reasoning_content → fence-stripped string). ``llm_response_text``
# does the same (content / reasoning_content, with thinking stripping); alias it so the planner
# and any other caller can import the same behavior from the unified module.
_extract_json_str_from_response = llm_response_text


def _strip_json_text(raw: str) -> str:
    """Normalize model output to a JSON-parseable string.

    Ported from the former ``soothe_nano.utils.llm.wrappers._strip_json_text``.
    Local OpenAI-compatible providers (oMLX/GLM/gemma) sometimes wrap
    ``json_schema`` output in a markdown fence (````` ```json ... ``` `````)
    or prefix it with prose even though ``response_format`` requested strict
    JSON. Strip the fence and, if prose remains, slice to the first ``{`` so
    ``json.loads`` succeeds. Returns a string (the caller parses it).
    """
    text = (raw or "").strip()
    if not text:
        return text
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start > 0:
        # Leading prose before the first object — slice it off.
        text = text[start:]
    return text
