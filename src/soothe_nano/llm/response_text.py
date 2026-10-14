"""Extract parseable text and JSON objects from provider AIMessage responses."""

from __future__ import annotations

from typing import Any

from soothe_nano._rust_compat import parse_json_object_rust, strip_json_text_rust
from soothe_nano.llm.thinking import strip_thinking

__all__ = [
    "llm_response_text",
    "parse_json_object",
    "text_from_message_content",
    "_strip_json_text",
]


def text_from_message_content(content: Any) -> str:
    """Flatten AIMessage `content` (str or block list) to plain text."""
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

    Thinking models may put JSON in `additional_kwargs["reasoning_content"]`
    or list-style `content` blocks while leaving primary `content` empty.
    `strip_thinking` is applied so inline thinking blocks never surface.
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
    """Parse a JSON object from model output (raw or markdown-fenced).

    Delegates to the Rust implementation which handles fence extraction,
    direct parsing, and brace-depth fallback matching.
    """
    return parse_json_object_rust(content)


def _strip_json_text(raw: str) -> str:
    """Normalize model output to a JSON-parseable string.

    Local OpenAI-compatible providers sometimes wrap `json_schema` output in
    a markdown fence or prefix it with prose even though `response_format`
    requested strict JSON. Strip the fence and, if prose remains, slice to
    the first `{` so downstream `json.loads` succeeds. Returns a string
    (the caller parses it).
    """
    return strip_json_text_rust(raw)
