"""Tool binding and tool-call extraction for the litellm adapter.

This is where the tool-calling regression is fixed by construction. The old
``OpenAICompatModelWrapper`` called ``self._model._agenerate(...)`` directly on
a langchain ``RunnableBinding``, bypassing the kwargs merge that delivers the
bound ``tools=`` to the provider — so the model never received tools and
emitted tool-call intent as JSON-as-text.

The litellm adapter avoids this entirely: :func:`bind_tools_litellm` stores the
tool schemas on the adapter instance, and :meth:`ChatLitellmModel._generate`
passes them directly to ``litellm.completion(tools=...)``. litellm returns
native structured ``tool_calls`` (verified for DashScope), which
:func:`extract_tool_calls_from_litellm` maps to the langchain
``AIMessage.tool_calls`` shape the agent graph reads.

A safety-net text recovery (:func:`recover_text_tool_calls`) catches the
provider regression mode where a model emits tool calls as text (````` json
fences, ``NAME(args)`` syntax, ``<function=X>{}</function>`` tags) and lifts
them into structured ``tool_calls`` so the pipeline still functions.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from soothe_nano.llm.message import lc_from_litellm_message


def _tool_to_litellm_schema(tool: Any) -> dict[str, Any]:
    """Convert a langchain tool (BaseTool or @tool function) to litellm ``tools`` wire format.

    litellm accepts the OpenAI tool schema: ``{"type": "function", "function":
    {"name", "description", "parameters"}}``. langchain tools expose
    ``.name``, ``.description``, and ``.args_schema`` (a pydantic model whose
    ``model_json_schema()`` is the parameters schema).
    """
    # Already in wire dict form.
    if isinstance(tool, dict) and "type" in tool:
        return tool
    # langchain BaseTool / @tool function.
    if isinstance(tool, BaseTool) or hasattr(tool, "args_schema"):
        name = getattr(tool, "name", None) or getattr(tool, "__name__", "tool")
        description = getattr(tool, "description", None) or ""
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            parameters = args_schema.model_json_schema()
        else:
            parameters = _parameters_from_signature(tool)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
    # Pydantic model class (structured-output-as-tool pattern).
    if hasattr(tool, "model_json_schema"):
        name = getattr(tool, "__name__", "tool")
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": (tool.__doc__ or "").strip(),
                "parameters": tool.model_json_schema(),
            },
        }
    # Bare callable / plain function: inspect the signature.
    if callable(tool):
        name = getattr(tool, "__name__", "tool")
        description = (tool.__doc__ or "").strip()
        parameters = _parameters_from_signature(tool)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
    raise TypeError(f"Cannot convert {type(tool)!r} to a litellm tool schema")


def _parameters_from_signature(func: Any) -> dict[str, Any]:
    """Build a JSON-Schema ``parameters`` object from a callable's signature.

    Used when a tool is a plain function (no ``args_schema``). Each parameter
    becomes a ``string`` property (the most permissive type — litellm/OpenAI
    tool schemas require a ``parameters`` object but are lenient on types;
    the model fills the actual values).
    """
    import inspect

    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return {"type": "object", "properties": {}}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        properties[pname] = {"type": "string"}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def bind_tools_litellm(tools: list[Any]) -> list[dict[str, Any]]:
    """Build the litellm ``tools=`` argument from a list of langchain tools.

    Args:
        tools: langchain ``BaseTool`` instances, ``@tool`` functions, pydantic
            schema classes, or pre-formed wire dicts.

    Returns:
        OpenAI-compatible ``tools`` list for ``litellm.completion``.
    """
    return [_tool_to_litellm_schema(t) for t in tools]


def extract_tool_calls_from_litellm(message: Any) -> AIMessage:
    """Map a litellm chat-completion message to a langchain ``AIMessage``.

    litellm returns native ``tool_calls`` (``Function(name, arguments)``) which
    this maps to the langchain ``tool_calls`` list-of-dicts shape. When the
    model emitted tool calls **as text** instead (the provider regression mode),
    :func:`recover_text_tool_calls` lifts them back into structured form.
    """
    ai_msg = lc_from_litellm_message(message)
    # Native tool_calls came through → done.
    if ai_msg.tool_calls:
        return ai_msg
    # No native tool_calls: try to recover from text-embedded tool calls.
    text = ai_msg.content if isinstance(ai_msg.content, str) else ""
    if text:
        recovered = recover_text_tool_calls(text)
        if recovered:
            # Preserve the original text as a stripped/empty content so the
            # agent graph routes to the tool node rather than END.
            return AIMessage(content="", tool_calls=recovered)
    return ai_msg


# --- text-embedded tool-call recovery (safety net) ---------------------------
#
# Some providers/models, when the OpenAI ``tools=`` parameter is not honored or
# dropped, emit tool-call intent as text in one of these formats:
#
#   ```json
#   {"name": "get_weather", "arguments": {"city": "Paris"}}
#   ```
#
#   get_weather(city="Paris")
#
#   <function=get_weather>{"location": "Paris"}</function>
#
# The recovery is best-effort: if args don't match the tool schema, litellm
# will surface the error on execution, which is still better than silently
# answering from no evidence.

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)
_FUNCTION_TAG_RE = re.compile(r"<function=([A-Za-z0-9_]+)>(.*?)</function>", re.DOTALL)
_CALL_SYNTAX_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", re.DOTALL)


def _parse_args_dict(raw: str) -> dict[str, Any]:
    """Parse a JSON object or ``k="v"`` arg list into a dict."""
    raw = raw.strip()
    if not raw:
        return {}
    # JSON object.
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    # ``k="v", k2=42`` syntax.
    args: dict[str, Any] = {}
    for part in re.split(r",(?![^()]*\))", raw):
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", part, re.DOTALL)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip().rstrip(",")
        # Strip quotes.
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        else:
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                pass
        args[key] = val
    return args


def recover_text_tool_calls(text: str) -> list[dict[str, Any]]:
    """Best-effort recovery of tool calls emitted as text.

    Returns a list of langchain-shaped tool-call dicts
    (``{"name","args","id","type":"tool_call"}``) when a recognized format is
    found; empty list otherwise.
    """
    calls: list[dict[str, Any]] = []

    # 1. <function=NAME>{...args json...}</function>
    for m in _FUNCTION_TAG_RE.finditer(text):
        name, args_raw = m.group(1), m.group(2).strip()
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            args = _parse_args_dict(args_raw)
        calls.append({"name": name, "args": args, "id": f"text_{name}", "type": "tool_call"})

    # 2. ```json fences with {"name":..., "arguments":...}
    if not calls:
        for m in _JSON_FENCE_RE.finditer(text):
            body = m.group(1).strip()
            try:
                obj = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and ("name" in obj or "tool" in obj):
                name = obj.get("name") or obj.get("tool") or ""
                args = obj.get("arguments") or obj.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        pass
                if name:
                    calls.append(
                        {
                            "name": name,
                            "args": args if isinstance(args, dict) else {},
                            "id": f"text_{name}",
                            "type": "tool_call",
                        }
                    )

    # 3. NAME(args) call syntax (last — most ambiguous).
    if not calls:
        for m in _CALL_SYNTAX_RE.finditer(text):
            name, args_raw = m.group(1), m.group(2)
            # Heuristic: only treat as a tool call if the name is not a common
            # prose word and the parens contain key=value or json.
            if name.lower() in {"function", "def", "if", "for", "while"}:
                continue
            args = _parse_args_dict(args_raw)
            if args:
                calls.append(
                    {
                        "name": name,
                        "args": args,
                        "id": f"text_{name}",
                        "type": "tool_call",
                    }
                )

    return calls


__all__ = [
    "bind_tools_litellm",
    "extract_tool_calls_from_litellm",
    "recover_text_tool_calls",
]
