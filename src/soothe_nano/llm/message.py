"""Pydantic message model for non-langchain LLM callers.

Langchain ``BaseMessage`` types (``AIMessage``, ``HumanMessage``, ...) remain
canonical across the agent graph and the ``ChatLitellmModel`` adapter. This
module provides a pydantic message abstraction for callers that talk to the
LLM layer directly (cron extraction, image understanding, embed/rerank) without
the langchain ``BaseChatModel`` ceremony.

:func:`lc_to_litellm_messages` / :func:`lc_from_litellm_message` bridge between
the two at the provider boundary.
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


def lc_to_litellm_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Convert langchain messages to the ``[{role, content}]`` dict list litellm expects.

    Preserves ``tool_calls`` and ``tool_call_id`` (for ``ToolMessage``) so the
    litellm ``messages`` payload carries the full agent-turn context.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.type  # "human" | "ai" | "system" | "tool"
        content = m.content if isinstance(m.content, str) else str(m.content)
        entry: dict[str, Any] = {"role": role, "content": content}
        # AI tool_calls
        tcs = getattr(m, "tool_calls", None)
        if tcs:
            entry["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": (
                            tc.get("args", "{}")
                            if isinstance(tc.get("args"), str)
                            else _json_dumps(tc.get("args", {}))
                        ),
                    },
                }
                for tc in tcs
                if isinstance(tc, dict)
            ]
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
    """Build a langchain ``AIMessage`` from a litellm/OpenAI chat-completion message.

    Maps native ``tool_calls`` (``Function(name, arguments)``) to the langchain
    ``tool_calls`` list-of-dicts shape the agent graph and executor read.
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
