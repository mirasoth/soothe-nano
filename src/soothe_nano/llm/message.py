"""Pydantic message models for direct (non-langchain) LLM callers.

Provides a pydantic message abstraction for cron extraction, image
understanding, and embed/rerank services. `lc_to_litellm_messages` /
`lc_from_litellm_message` bridge between langchain `BaseMessage` and these
models at the provider boundary.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
)
from pydantic import BaseModel, Field

# ============================================================================
# Pydantic message system (interop / direct-caller model)
# ============================================================================

SupportedImageMediaType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]

# Map OpenAI/litellm role aliases that appear in hand-built dict messages to the
# canonical litellm role names. LangChain ``BaseMessage`` aliases ("human"/"ai")
# are handled separately in :func:`lc_to_litellm_messages` via ``m.type``.
_LITELLM_ROLE_ALIAS: dict[str, str] = {
    "human": "user",
    "ai": "assistant",
}


def _truncate(text: str, max_length: int = 50) -> str:
    """Truncate text to max_length characters, adding ellipsis if truncated."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


class ContentPartTextParam(BaseModel):
    text: str
    type: Literal["text"] = "text"


class ContentPartRefusalParam(BaseModel):
    refusal: str
    type: Literal["refusal"] = "refusal"


class ImageURL(BaseModel):
    url: str
    detail: Literal["auto", "low", "high"] = "auto"
    media_type: SupportedImageMediaType = "image/png"


class ContentPartImageParam(BaseModel):
    image_url: ImageURL
    type: Literal["image_url"] = "image_url"


class Function(BaseModel):
    arguments: str
    name: str


class ToolCall(BaseModel):
    id: str
    function: Function
    type: Literal["function"] = "function"


class _MessageBase(BaseModel):
    """Base class for all pydantic message types."""

    role: Literal["user", "system", "assistant"]
    cache: bool = False


class UserMessage(_MessageBase):
    role: Literal["user"] = "user"
    content: str | list[ContentPartTextParam | ContentPartImageParam]
    name: str | None = None

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "\n".join(p.text for p in self.content if getattr(p, "type", None) == "text")
        return ""


class SystemMessage(_MessageBase):
    role: Literal["system"] = "system"
    content: str | list[ContentPartTextParam]
    name: str | None = None

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "\n".join(p.text for p in self.content if getattr(p, "type", None) == "text")
        return ""


class AssistantMessage(_MessageBase):
    role: Literal["assistant"] = "assistant"
    content: str | list[ContentPartTextParam | ContentPartRefusalParam] | None = None
    name: str | None = None
    refusal: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "\n".join(p.text for p in self.content if getattr(p, "type", None) == "text")
        return ""


BasePydanticMessage = UserMessage | SystemMessage | AssistantMessage


# ============================================================================
# langchain <-> litellm bridges
# ============================================================================


def _normalize_tool_calls_entry(tcs: Any) -> list[dict[str, Any]]:
    """Coerce a raw `tool_calls` list to OpenAI/litellm shape, dropping malformed entries.

    Each entry must carry a non-empty `function.name`: providers reject
    `tool_calls[i].function missing required field "name"` with a 400
    `invalid_request_error` that is not retriable. Malformed entries — a
    missing or empty `name` — are dropped rather than emitted, so the
    request never reaches the provider in a shape it would reject.
    """
    if not tcs:
        return []
    normalized: list[dict[str, Any]] = []
    for tc in tcs:
        if not isinstance(tc, dict):
            continue
        name = tc.get("name")
        if not name:
            # Dict already in OpenAI shape: {id, type, function: {name, arguments}}.
            fn = tc.get("function")
            if isinstance(fn, dict):
                name = fn.get("name")
            if not name:
                continue  # Drop tool_call with missing/empty name (avoid 400).
            normalized.append(tc)
            continue
        normalized.append(
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": (
                        tc.get("args", "{}")
                        if isinstance(tc.get("args"), str)
                        else _json_dumps(tc.get("args", {}))
                    ),
                },
            }
        )
    return normalized


def lc_to_litellm_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Convert langchain messages to the `[{role, content}]` dict list litellm expects.

    Preserves `tool_calls` and `tool_call_id` (for `ToolMessage`) so the
    litellm `messages` payload carries the full agent-turn context.

    Also accepts plain `{"role", "content"}` dicts: callers like the planner
    engine build message lists directly as dicts rather than `BaseMessage`
    objects, and LangChain's structured-output runnable passes them through to
    `_agenerate` uncoerced. Without this dict path the converter raised
    `AttributeError: 'dict' object has no attribute 'type'` (deployed
    `soothe_nano.subagents.plan.engine` structured-output draft).

    Malformed `tool_calls` entries (a missing or empty `function.name`) are
    dropped: providers return a non-retriable 400 `invalid_request_error` for
    `tool_calls[i].function missing required field "name"`. Dropping the bad
    entry keeps a long resumed thread runnable instead of failing the whole
    request on one corrupt historical assistant turn.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, dict):
            # Already in litellm/OpenAI shape; normalize role aliases and pass
            # through, preserving any tool_calls / tool_call_id / name fields.
            entry: dict[str, Any] = dict(m)
            role = entry.get("role", "user")
            entry["role"] = _LITELLM_ROLE_ALIAS.get(role, role)
            content = entry.get("content")
            if not isinstance(content, str):
                entry["content"] = "" if content is None else str(content)
            if "tool_calls" in entry:
                tcs = _normalize_tool_calls_entry(entry["tool_calls"])
                if tcs:
                    entry["tool_calls"] = tcs
                else:
                    # All tool_calls were malformed; drop the field entirely so
                    # the provider doesn't see an empty list.
                    del entry["tool_calls"]
            out.append(entry)
            continue

        role = m.type  # "human" | "ai" | "system" | "tool"
        content = m.content if isinstance(m.content, str) else str(m.content)
        entry = {"role": role, "content": content}
        # AI tool_calls
        tcs = getattr(m, "tool_calls", None)
        if tcs:
            normalized = _normalize_tool_calls_entry(tcs)
            if normalized:
                entry["tool_calls"] = normalized
        # ToolMessage correlation id
        tcid = getattr(m, "tool_call_id", None)
        if tcid:
            entry["role"] = "tool"
            entry["tool_call_id"] = tcid
        # Map langchain role names to litellm/OpenAI roles.
        if role == "human":
            entry["role"] = "user"
        elif role == "ai":
            entry["role"] = "assistant"
        elif role == "system":
            entry["role"] = "system"
        out.append(entry)
    return out


def lc_from_litellm_message(message: Any) -> AIMessage:
    """Build a langchain `AIMessage` from a litellm/OpenAI chat-completion message.

    Maps native `tool_calls` (`Function(name, arguments)`) to the langchain
    `tool_calls` list-of-dicts shape the agent graph and executor read.
    """
    content = getattr(message, "content", "") or ""
    tcs = getattr(message, "tool_calls", None) or []
    tool_calls: list[dict[str, Any]] = []
    for tc in tcs:
        fn = (
            getattr(tc, "function", None) or tc.get("function")
            if isinstance(tc, dict)
            else getattr(tc, "function", None)
        )
        if isinstance(fn, dict):
            name = fn.get("name", "")
            args_raw = fn.get("arguments", "{}")
        else:
            name = getattr(fn, "name", "") or ""
            args_raw = getattr(fn, "arguments", "{}")
        try:
            args: Any = _json_loads(args_raw) if isinstance(args_raw, str) else args_raw
        except Exception:
            args = {}
        tc_id = getattr(tc, "id", "") or (tc.get("id", "") if isinstance(tc, dict) else "")
        tool_calls.append({"name": name, "args": args, "id": tc_id, "type": "tool_call"})
    return AIMessage(content=content, tool_calls=tool_calls)


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, default=str)


def _json_loads(s: str) -> Any:
    import json

    return json.loads(s)


__all__ = [
    "BasePydanticMessage",
    "ContentPartImageParam",
    "ContentPartRefusalParam",
    "ContentPartTextParam",
    "Function",
    "ImageURL",
    "AssistantMessage",
    "SystemMessage",
    "UserMessage",
    "ToolCall",
    "lc_from_litellm_message",
    "lc_to_litellm_messages",
]
