"""Muse-Glimmer response adapter for OpenAI-compatible servers.

The ``Muse-Glimmer-30B-4bit`` model (served by vLLM-Metal on
``http://localhost:9543/v1`` — see ``deploy-llm-inference/docs/vllm_deployment.md``
— and historically by the oMLX endpoint on ``:9642``) emits two distinct wire
shapes that this module normalizes into clean content + structured
``tool_calls``:

1. **Native self-talk protocol** (engaged when the model is given a strong
   tool-use system prompt). The server passes the raw protocol through in the
   OpenAI ``content`` field — vLLM-Metal does **not** separate the stages
   (``vllm_deployment.md`` caveat 2) and does **not** emit structured
   ``tool_calls`` (``tool_calls: null`` even with ``tool_choice: required``)::

       to=self<|message|>…internal reasoning…<|eom|>      — hidden chain-of-thought
       <|start|>assistant to=user<|message|>ACTUAL REPLY  — the user-facing text
       <|start|>assistant to=<toolname><|message|>         — a tool-call block follows

   Tool calls are XML-in-content, in (at least) four dialects::

       <atem:function_calls>
       <atem:invoke name="calculator">
       <atem:parameter name="expression">2+2</atem:parameter>
       </atem:invoke>
       </atem:function_calls>

       <function name="read_file"><arg name="file_path">/x</arg></function>

       <read_file file_path="/x"></read_file>            # self-named, attribute args

       <atem:run_command>{"args": "ls -la"}</atem:run_command>   # atem:NAME + JSON body

2. **Repetition loop** (the vLLM-Metal chat-template artifact, caveat 1). When
   the model answers a question that does not engage tool use, vLLM-Metal's
   simple ``System:/User:/Assistant:`` chat template (instead of the model's
   native template) causes the model to answer once, then hallucinate further
   ``User: …\\nAssistant: …`` turns and loop until ``max_tokens``. There are
   **no** protocol markers in this case — just the trailing echo::

       2+2 equals 4.

       User: What is 2+2? Answer in one sentence.
       Assistant: 2+2 equals 4.

       User: What is 2+2? Answer in one sentence.
       Assistant: …

This module converts either shape into:

1. the clean user-facing text (self-talk, tool XML, and repetition echoes
   stripped), and
2. a list of structured tool calls compatible with LangChain's
   ``AIMessage.tool_calls`` contract.

It is pure and re-importable from tests; the wire-up into
:class:`~soothe_nano.utils.llm.wrappers.OpenAICompatModelWrapper` lives in
``wrappers.py`` / ``factory.py``.

Markers are documented here in one place so the adapter and its tests stay
in sync with the live protocol.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "detect_muse_glimmer_protocol",
    "detect_muse_glimmer_repetition",
    "extract_user_reply",
    "parse_atem_tool_calls",
    "strip_repetition_loop",
    "transform_muse_glimmer_message",
    "build_tool_calls_for_message",
]

# --- protocol markers (single source of truth) -----------------------------

# A self-directed reasoning segment begins with this and ends at ``<|eom|>``.
_SELF_MARKER = "to=self<|message|>"
# The actual user-facing reply follows this marker (may be preceded by a
# ``<|start|>assistant `` prefix emitted by the model).
_USER_MARKER = "to=user<|message|>"
# A tool-directed turn begins with ``to=<toolname><|message|>`` and is
# followed by an ``<atem:function_calls>`` block.
_TOOL_TURN_RE = re.compile(r"to=(?P<tool>[^\s<|]+)<\|message\|>")
# The segment-end / new-segment markers the model uses to delimit turns.
_EOM_MARKER = "<|eom|>"
_START_MARKER = "<|start|>"

# --- tool-call XML parsing -------------------------------------------------
#
# Muse-Glimmer emits tool calls in (at least) four XML dialects depending on
# how tools were offered (native API ``tools`` param vs. agent ``bind_tools``):
#
# 1. ``<atem:function_calls>`` envelope (seen with OpenAI ``tools`` param):
#    <atem:function_calls>
#    <atem:invoke name="calculator">
#    <atem:parameter name="expression">2+2</atem:parameter>
#    </atem:invoke>
#    </atem:function_calls>
#
# 2. ``<function name="…">`` with ``<arg name="…">VALUE</arg>`` children
#    (seen with langchain ``bind_tools``):
#    <function name="read_file">
#    <arg name="file_path">/path/to/file</arg>
#    </function>
#    ... terminated by a stray ``</atem:assistant>``.
#
# 3. Self-named element with args as attributes (also seen with bind_tools):
#    <read_file file_path="/path/to/file"></read_file>
#    or self-closing <read_file file_path="/path/to/file"/>
#
# 4. ``<atem:TOOLNAME>{...json args...}</atem:TOOLNAME>`` — the tool name is
#    the element local-name after ``atem:`` and the body is a JSON object of
#    args (often ``{"args": "shell command"}`` for run_command).
#
# The model precedes a tool-call turn with ``to=<toolname><|message|>`` and a
# prose turn with ``to=user<|message|>``. We parse all dialects.

# One ``<atem:invoke name="...">…</atem:invoke>`` block. ``DOTALL`` so the
# block (parameters) can span newlines. Non-greedy so multiple invokes in a
# single ``<atem:function_calls>`` block each match independently.
_INVOKE_RE = re.compile(
    r"<atem:invoke\s+name=\"(?P<name>[^\"]+)\"[^>]*>(?P<body>.*?)</atem:invoke>",
    re.DOTALL,
)
# A ``<atem:parameter name="...">VALUE</atem:parameter>`` child. Non-greedy
# on the value so adjacent parameters don't bleed into each other.
_PARAM_RE = re.compile(
    r"<atem:parameter\s+name=\"(?P<key>[^\"]+)\"[^>]*>(?P<value>.*?)</atem:parameter>",
    re.DOTALL,
)
# Dialect 2: ``<function name="..."><arg name="...">VALUE</arg>...</function>``.
# Also matches ``<tool_call name="...">…</tool>`` / ``<tool name="...">…</tool>``
# — the model sometimes uses these interchangeable tag names.
_FUNCTION_BLOCK_RE = re.compile(
    r"<(?:function(?:_call)?|tool_call|tool)\s+name=\"(?P<name>[^\"]+)\"[^>]*>(?P<body>.*?)</(?:function(?:_call)?|tool_call|tool)>",
    re.DOTALL,
)
# A ``<arg name="...">VALUE</arg>`` child (also ``<parameter>`` / ``<argument>``).
_ARG_RE = re.compile(
    r"<(?:arg|parameter|argument)\s+name=\"(?P<key>[^\"]+)\"[^>]*>(?P<value>.*?)</(?:arg|parameter|argument)>",
    re.DOTALL,
)
# Dialect 2b: self-closing ``<function_call name="TOOL" k="v" …/>`` (or
# paired) where args are attributes, not ``<arg>`` children. The model
# sometimes uses this instead of the child-arg form.
_FUNCTION_ATTR_RE = re.compile(
    r"<(?:function(?:_call)?|tool_call|tool)\s+name=\"(?P<name>[^\"]+)\"(?P<attrs>(?:\s+[a-zA-Z_][\w-]*=\"[^\"]*\")*)\s*/?>(?:</(?:function(?:_call)?|tool_call|tool)>)?",
)
# Dialect 4: ``<atem:TOOLNAME>{...json args...}</atem:TOOLNAME>`` — the tool
# name is the element local-name after ``atem:`` and the body is a JSON object
# of args (often ``{"args": "shell command"}`` for run_command). Also matches
# when the body is ``<arg>`` children for robustness.
_ATEM_TOOL_BLOCK_RE = re.compile(
    r"<atem:(?P<name>[a-zA-Z_][\w-]*)\b[^>]*>(?P<body>.*?)</atem:\1>",
    re.DOTALL,
)
# Dialect 5: ``to=<toolname><|message|><args>[json_array]</args>`` — the tool
# name comes from the ``to=`` header and args are a positional JSON array
# (e.g. ``<args>["/path/to/dir"]</args>``) or XML key-value elements
# (e.g. ``<args><file_path>/x</file_path></args>``). The adapter maps
# positional args to keyword names using the bound tool's parameter schema
# when available. The optional ``assistant`` prefix is consumed so it does
# not leak as visible content.
_TO_ARGS_RE = re.compile(
    r"(?:assistant\s+)?to=(?P<tool>[^\s<|]+)<\|message\|>\s*<args>(?P<body>.*?)</args>",
    re.DOTALL,
)
# Dialect 5b: ``to=<toolname><|message|><atem:parameter name="…">…</atem:parameter>…``
# — bare ``<atem:parameter>`` elements follow the ``to=<tool>`` header
# without an enclosing ``<atem:invoke>`` or ``<args>`` tag.
_TO_BARE_PARAMS_RE = re.compile(
    r"(?:assistant\s+)?to=(?P<tool>[^\s<|]+)<\|message\|>\s*"
    r"(?P<body>(?:<atem:parameter\s+name=\"[^\"]+\"[^>]*>.*?</atem:parameter>\s*)+)",
    re.DOTALL,
)
# Dialect 3: self-named element with args as attributes, either self-closing
# (``<read_file file_path="..."/>``) or paired (``<read_file ...></read_file>``).
# Tag name must be a plausible tool name (letters/digits/_/-) to avoid
# matching arbitrary HTML-like tags. Args are ``key="value"`` pairs inside.
_SELF_NAMED_RE = re.compile(
    r"<(?P<name>[a-zA-Z_][\w-]*)\b(?P<attrs>(?:\s+[a-zA-Z_][\w-]*=\"[^\"]*\")+)\s*/?>(?:</(?P=name)\s*>)?",
)
_ATTR_RE = re.compile(r'([a-zA-Z_][\w-]*)="([^"]*)"')
# The whole ``<atem:function_calls>…</atem:function_calls>`` envelope (used to
# strip it from visible content after parsing).
_FUNC_CALLS_BLOCK_RE = re.compile(
    r"<atem:function_calls>.*?</atem:function_calls>",
    re.DOTALL,
)
# A stray ``</atem:assistant>`` terminator the model emits after bind_tools
# tool calls; stripped from visible content.
_ATEM_ASSISTANT_CLOSE_RE = re.compile(r"</atem:assistant\s*>")

# --- repetition-loop markers (vLLM-Metal chat-template artifact) ------------
#
# When the native protocol is NOT engaged, vLLM-Metal's simple
# ``System:/User:/Assistant:`` chat template makes the model answer once and
# then hallucinate further ``User: …`` / ``Assistant: …`` turns. The first
# ``User:`` (or ``Assistant:``) appearing at the start of a line after the
# real answer marks the start of the echo loop. We cut there.
#
# A hallucinated turn boundary is a ``User:`` or ``Assistant:`` token that
# begins a line (optionally preceded by whitespace). It must come AFTER any
# real content — a leading ``User:`` (e.g. the server echoing the prompt) is
# not a loop, so we only cut on occurrences after position 0.
_REPETITION_TURN_RE = re.compile(r"(?:^|\n)\s*(?:User|Assistant)\s*:", re.MULTILINE)


def detect_muse_glimmer_protocol(text: str) -> bool:
    """Return ``True`` when *text* looks like Muse-Glimmer protocol output.

    Cheap marker check — we look for any of the distinctive tokens
    (``<|message|>``, ``<|eom|>``, ``<atem:`` tag, ``to=self``, ``to=user``).
    Used so non-Muse-Glimmer providers skip the protocol transform entirely.
    """
    if not text:
        return False
    return (
        "<|message|>" in text
        or "<|eom|>" in text
        or "<atem:" in text
        or "to=self" in text
        or "to=user" in text
    )


def detect_muse_glimmer_repetition(text: str) -> int:
    """Return the index where a vLLM-Metal repetition loop begins, or ``-1``.

    The model answers once, then hallucinates further ``User:``/``Assistant:``
    turns (the chat-template artifact from ``vllm_deployment.md`` caveat 1).
    The first such turn boundary *after the start of the text* marks the loop.
    A leading ``User:``/``Assistant:`` (the server echoing the prompt) is not
    a loop, so position 0 is ignored.
    """
    if not text:
        return -1
    for match in _REPETITION_TURN_RE.finditer(text):
        if match.start() == 0:
            continue
        # Only count it as a loop boundary if there is real content before it.
        # (A bare ``User:`` immediately after a newline with only whitespace
        # before it is the artifact; we already skipped start-of-text.)
        return match.start()
    return -1


def strip_repetition_loop(text: str) -> str:
    """Cut a vLLM-Metal repetition loop, keeping only the first answer.

    If the text contains a hallucinated ``User:``/``Assistant:`` turn boundary
    after the real answer (see :func:`detect_muse_glimmer_repetition`), return
    the text up to that boundary (trailing whitespace stripped). Otherwise
    return *text* unchanged.
    """
    if not text:
        return text
    idx = detect_muse_glimmer_repetition(text)
    if idx < 0:
        return text
    return text[:idx].rstrip()


def extract_user_reply(text: str) -> str:
    """Return only the user-facing reply portion of *text*.

    The real answer is whatever follows the **final** ``to=user<|message|>``
    marker (self-talk ``to=self`` segments and tool-XML are discarded). If no
    ``to=user`` marker is present, the original text is returned unchanged —
    this is the safe fallback for truncated/edge responses where the model
    never reached the reply segment (the caller still sees something rather
    than an empty string).
    """
    if not text:
        return text
    idx = text.rfind(_USER_MARKER)
    if idx < 0:
        return text
    reply = text[idx + len(_USER_MARKER) :]
    # Strip a possible leading ``<|start|>assistant `` prefix that the model
    # sometimes emits immediately before ``to=user`` — already excluded by
    # slicing past the marker, but guard against trailing remnants.
    return reply


def _map_positional_args(
    tool_name: str, args_list: list[Any], tool_param_order: dict[str, list[str]] | None
) -> dict[str, Any]:
    """Map positional args from a JSON array to keyword names.

    When *tool_param_order* carries the bound tool's parameter list (e.g.
    ``{"ls": ["path", "include_info"]}``), positional args are assigned by
    index. Without a schema, a single string arg maps to ``path`` (the most
    common first parameter for filesystem tools) and multi-element arrays use
    ``arg_0``, ``arg_1``, … as a last-resort fallback.
    """
    if not args_list:
        return {}
    # Schema-based mapping (preferred).
    if tool_param_order:
        params = tool_param_order.get(tool_name)
        if params:
            return {params[i]: val for i, val in enumerate(args_list) if i < len(params)}
    # Heuristic fallback for when no schema is available.
    if len(args_list) == 1 and isinstance(args_list[0], str):
        return {"path": args_list[0]}
    if len(args_list) == 1 and isinstance(args_list[0], dict):
        return args_list[0]
    return {f"arg_{i}": val for i, val in enumerate(args_list)}


def parse_atem_tool_calls(
    text: str, tool_param_order: dict[str, list[str]] | None = None
) -> list[dict[str, Any]]:
    """Parse Muse-Glimmer tool-call blocks from *text*.

    Handles the five dialects the model emits (see the parsing section
    above): ``<atem:invoke>`` with ``<atem:parameter>``, ``<function name>``
    with ``<arg>``, ``<atem:TOOLNAME>`` JSON bodies, and self-named elements
    with attribute args (``<read_file file_path="…"/>``). Returns a list of
    ``{"name": str, "args": dict, "raw_text": str}`` dicts in document
    order. Malformed blocks (missing name, unparseable parameters) are
    skipped with a ``DEBUG`` log rather than raising — a single bad tool call
    must not poison the whole turn.

    ``raw_text`` is the full matched block so the wrapper can strip exactly
    that span from visible content after parsing. Deduplicates across
    dialects when the same call matches two regexes.
    """
    if not text:
        return []
    calls: list[dict[str, Any]] = []
    seen_spans: list[tuple[int, int]] = []

    def _add(name: str, args: dict[str, Any], raw: str, span: tuple[int, int]) -> None:
        # Skip if this exact span was already captured by another dialect.
        for s in seen_spans:
            if span[0] == s[0] or (span[0] >= s[0] and span[1] <= s[1]):
                return
        seen_spans.append(span)
        calls.append({"name": name, "args": args, "raw_text": raw})

    # Dialect 1: <atem:invoke name="…">…<atem:parameter …>…</atem:invoke>
    for match in _INVOKE_RE.finditer(text):
        name = match.group("name").strip()
        if not name:
            logger.debug("muse_glimmer_skip_invoke reason=empty_name block=%r", match.group(0))
            continue
        body = match.group("body") or ""
        args = _parse_params(body)
        _add(name, args, match.group(0), match.span())

    # Dialect 2: <function name="…">…<arg name="…">VALUE</arg>…</function>
    for match in _FUNCTION_BLOCK_RE.finditer(text):
        name = match.group("name").strip()
        if not name:
            continue
        body = match.group("body") or ""
        args = _parse_args(body)
        _add(name, args, match.group(0), match.span())

    # Dialect 4: <atem:TOOLNAME>{...}</atem:TOOLNAME>
    for match in _ATEM_TOOL_BLOCK_RE.finditer(text):
        name = match.group("name").strip()
        if not name or name in {"function_calls", "invoke", "parameter", "assistant"}:
            continue
        body = (match.group("body") or "").strip()
        args = _parse_body_args(body)
        _add(name, args, match.group(0), match.span())

    # Dialect 2b: self-closing <function_call name="TOOL" k="v" …/>
    for match in _FUNCTION_ATTR_RE.finditer(text):
        name = match.group("name").strip()
        if not name:
            continue
        attrs = match.group("attrs") or ""
        args: dict[str, Any] = {}
        for amatch in _ATTR_RE.finditer(attrs):
            key = amatch.group(1).strip()
            if key:
                args[key] = html.unescape(amatch.group(2))
        _add(name, _normalize_args(args), match.group(0), match.span())

    # Dialect 3: self-named element <toolname k="v" …/> (or paired).
    # Only match when the element name is not a known structural tag.
    for match in _SELF_NAMED_RE.finditer(text):
        name = match.group("name").strip()
        if not name or _is_structural_tag(name):
            continue
        attrs = match.group("attrs") or ""
        args: dict[str, Any] = {}
        for amatch in _ATTR_RE.finditer(attrs):
            key = amatch.group(1).strip()
            if key:
                args[key] = html.unescape(amatch.group(2))
        _add(name, _normalize_args(args), match.group(0), match.span())

    # Dialect 5: to=<toolname><|message|><args>...</args>
    # The body may be a JSON array (positional) or XML key-value elements
    # like <file_path>/path</file_path>.
    for match in _TO_ARGS_RE.finditer(text):
        name = match.group("tool").strip()
        if not name:
            continue
        body = (match.group("body") or "").strip()
        args_list = _parse_json_array(body)
        if args_list is not None:
            args = _map_positional_args(name, args_list, tool_param_order)
        else:
            # Try XML key-value elements: <key>value</key>.
            args = _parse_args_xml_elements(body)
            if not args:
                logger.debug("muse_glimmer_skip_to_args reason=unparseable tool=%s", name)
                continue
        _add(name, args, match.group(0), match.span())

    # Dialect 5b: to=<toolname><|message|><atem:parameter name="…">…</atem:parameter>
    for match in _TO_BARE_PARAMS_RE.finditer(text):
        name = match.group("tool").strip()
        if not name:
            continue
        body = match.group("body") or ""
        args = _parse_params(body)
        if not args:
            continue
        _add(name, args, match.group(0), match.span())

    return calls


def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Normalize a dict of parsed args.

    Handles the ``args="{'k': 'v'}"`` dialect where the whole arg dict is
    serialized into a single ``args`` attribute (a Python-dict-repr string).
    When we see a single ``args`` key whose value looks like a dict, parse it
    (JSON first, then a lenient key:value scan) and use that as the tool's
    args. Otherwise return *args* unchanged.
    """
    if not args:
        return args
    raw = args.get("args")
    if isinstance(raw, str) and len(args) == 1:
        parsed = _parse_dict_repr(raw)
        if parsed:
            return parsed
    return args


def _parse_dict_repr(text: str) -> dict[str, Any]:
    """Parse a Python-dict-repr or JSON string into a dict (lenient)."""
    import json

    s = html.unescape(text or "").strip()
    if not s:
        return {}
    # JSON first (double-quoted keys/values).
    try:
        loaded = json.loads(s)
        if isinstance(loaded, dict):
            return loaded
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    # Lenient scan for ``'key': 'value'`` or ``'key': value`` pairs.
    out: dict[str, Any] = {}
    for m in re.finditer(r"""['"](?P<key>[^'"]+)['"]\s*:\s*(?P<val>'[^']*'|"[^"]*"|[^,}\s]+)""", s):
        val = m.group("val").strip()
        if (val.startswith("'") and val.endswith("'")) or (
            val.startswith('"') and val.endswith('"')
        ):
            val = val[1:-1]
        out[m.group("key")] = val
    return out


def _parse_params(body: str) -> dict[str, Any]:
    """Parse ``<atem:parameter name="…">VALUE</atem:parameter>`` children."""
    args: dict[str, Any] = {}
    for pmatch in _PARAM_RE.finditer(body):
        key = pmatch.group("key").strip()
        value = pmatch.group("value")
        if key:
            args[key] = value
    return args


def _parse_json_array(text: str) -> list[Any] | None:
    """Parse a JSON or Python-style array from *text*, returning ``None`` on failure.

    The model sometimes emits single-quoted Python repr strings
    (``['/path']``) instead of valid JSON (``["/path"]``); ``ast.literal_eval``
    handles that as a fallback.
    """
    import ast
    import json

    s = html.unescape((text or "").strip())
    if not s:
        return None
    # JSON first (double-quoted).
    try:
        loaded = json.loads(s)
        if isinstance(loaded, list):
            return loaded
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    # Python-style single-quoted fallback.
    try:
        loaded = ast.literal_eval(s)
        if isinstance(loaded, list):
            return loaded
    except (ValueError, SyntaxError):
        pass
    return None


def _parse_args_xml_elements(text: str) -> dict[str, Any]:
    """Parse ``<key>value</key>`` elements from *text* into a dict.

    The model sometimes emits XML key-value pairs inside the ``<args>``
    body instead of a JSON array::

        <args>
        <file_path>/path/to/file</file_path>
        </args>
    """
    if not text:
        return {}
    args: dict[str, Any] = {}
    for m in re.finditer(
        r"<(?P<key>[a-zA-Z_][\w-]*)\s*>(?P<value>.*?)</(?P=key)\s*>",
        text,
        re.DOTALL,
    ):
        key = m.group("key").strip()
        if key:
            args[key] = m.group("value").strip()
    return args


def _parse_args(body: str) -> dict[str, Any]:
    """Parse ``<arg name="…">VALUE</arg>`` children."""
    args: dict[str, Any] = {}
    for amatch in _ARG_RE.finditer(body):
        key = amatch.group("key").strip()
        value = amatch.group("value")
        if key:
            args[key] = value
    return args


def _parse_body_args(body: str) -> dict[str, Any]:
    """Parse a tool block body that is JSON or ``<arg>`` children.

    The ``<atem:TOOLNAME>`` dialect puts a JSON object (often
    ``{"args": "shell command"}``) as the element body. Try JSON first, then
    the ``args``-dict-repr fallback, then ``<arg>`` children.
    """
    if not body:
        return {}
    import json

    stripped = body.strip()
    # JSON object body.
    try:
        loaded = json.loads(stripped)
        if isinstance(loaded, dict):
            return _normalize_args(loaded) if set(loaded) == {"args"} else loaded
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    # args-dict-repr fallback (single 'args' key with dict-repr value).
    parsed_repr = _parse_dict_repr(stripped)
    if parsed_repr:
        return parsed_repr
    # <arg name="...">VALUE</arg> children.
    arg_children = _parse_args(stripped)
    if arg_children:
        return arg_children
    return {}


# Structural XML tags the model emits that are not tool calls — never parse
# these as self-named tools (dialect 3 would otherwise grab ``<function>`` etc.).
_STRUCTURAL_TAGS = frozenset(
    {
        "function",
        "function_call",
        "tool_call",
        "tool",
        "arg",
        "parameter",
        "argument",
        "atem:function_calls",
        "atem:invoke",
        "atem:parameter",
        "atem:assistant",
    }
)


def _is_structural_tag(name: str) -> bool:
    """Return True for structural XML tags that are not tool calls."""
    return name in _STRUCTURAL_TAGS or name.startswith("atem:")


def _stable_tool_call_id(index: int, name: str, args: dict[str, Any]) -> str:
    """Deterministic tool-call id so langgraph can pair ToolMessages across retries.

    ``hash()`` is salted per-process in Python 3.12+ (PYTHONHASHSEED), so use
    a simple FNV-1a 32-bit over the ``name`` + JSON-sorted ``args`` instead.
    Random/time APIs are intentionally avoided so ids are reproducible in tests
    and stable across agent retries within one run.
    """
    import json

    payload = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
    h = 0x811C9DC5
    for ch in payload:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"musegl_{index}_{h:08x}"


def build_tool_calls_for_message(
    text: str, tool_param_order: dict[str, list[str]] | None = None
) -> list[dict[str, Any]]:
    """Build LangChain-style ``tool_calls`` dicts from Muse-Glimmer *text*.

    Each entry is ``{"name": str, "args": dict, "id": str}`` (matching the
    shape LangChain assigns to ``AIMessage.tool_calls``). Ids are
    deterministic (see :func:`_stable_tool_call_id`).

    *tool_param_order* (when provided by the wrapper from the bound tool
    schemas) lets the ``to=<tool><|message|><args>[…]`` dialect map
    positional JSON-array args to the correct keyword names.
    """
    parsed = parse_atem_tool_calls(text, tool_param_order=tool_param_order)
    out: list[dict[str, Any]] = []
    for idx, call in enumerate(parsed):
        out.append(
            {
                "name": call["name"],
                "args": call["args"],
                "id": _stable_tool_call_id(idx, call["name"], call["args"]),
            }
        )
    return out


def _strip_tool_xml_and_self_talk(text: str) -> str:
    """Remove all tool-call XML and self-talk from *text*.

    Strips the four tool-call dialects (``<atem:function_calls>`` envelopes,
    ``<function>`` blocks, ``<atem:TOOLNAME>`` blocks, and self-named tool
    elements) plus self-talk segments (``to=self<|message|>…<|eom|>``) and
    the turn-delimiter scaffolding (``<|start|>``, ``<|eom|>``,
    ``to=…<|message|>``, ``</atem:assistant>``). What remains is the
    ``to=user`` reply text (or any stray literal text the model emitted
    outside the protocol).
    """
    if not text:
        return text
    # Drop tool-call XML envelopes entirely, in all dialects.
    cleaned = _FUNC_CALLS_BLOCK_RE.sub("", text)
    cleaned = _FUNCTION_BLOCK_RE.sub("", cleaned)
    # Drop <atem:TOOLNAME>…</atem:TOOLNAME> blocks (dialect 4), but leave the
    # structural atem: envelope tags for the FUNC_CALLS sub above to handle.
    cleaned = _ATEM_TOOL_BLOCK_RE.sub("", cleaned)
    # Drop to=<tool><|message|><args>…</args> blocks (dialect 5).
    cleaned = _TO_ARGS_RE.sub("", cleaned)
    # Drop to=<tool><|message|><atem:parameter>… blocks (dialect 5b).
    cleaned = _TO_BARE_PARAMS_RE.sub("", cleaned)
    cleaned = _ATEM_ASSISTANT_CLOSE_RE.sub("", cleaned)
    # Drop self-named tool elements (dialect 3): any ``<toolname …/>`` or
    # ``<toolname …></toolname>`` whose name is not a structural tag. Run
    # repeatedly so adjacent/overlapping blocks all clear.
    prev = None
    while prev != cleaned:
        prev = cleaned
        for match in list(_SELF_NAMED_RE.finditer(cleaned)):
            name = match.group("name")
            if name and not _is_structural_tag(name):
                cleaned = cleaned[: match.start()] + cleaned[match.end() :]
                break
    # Drop self-talk segments: ``to=self<|message|>…<|eom|>`` (greedy across
    # the segment; a self segment never legitimately contains ``<|eom|>``
    # except as its terminator).
    cleaned = re.sub(
        r"to=self<\|message\|>.*?<\|eom\|>",
        "",
        cleaned,
        flags=re.DOTALL,
    )
    # Remove any leftover turn-delimiter scaffolding. ``<|start|>assistant``
    # precedes a ``to=…<|message|>`` turn marker; drop both the marker and the
    # ``assistant`` keyword so no scaffolding word surfaces to the user.
    cleaned = cleaned.replace(_START_MARKER, "")
    cleaned = cleaned.replace(_EOM_MARKER, "")
    # ``to=user<|message|>`` / ``to=<tool><|message|>`` remnants — strip the
    # ``assistant`` keyword that precedes them plus the marker itself.
    cleaned = re.sub(r"assistant\s*to=[^\s<|]*<\|message\|>", "", cleaned)
    cleaned = re.sub(r"to=[^\s<|]*<\|message\|>", "", cleaned)
    # A stray leading ``assistant `` (left when only ``<|start|>`` was removed
    # above) is never meaningful user content here.
    cleaned = re.sub(r"^\s*assistant\s+", "", cleaned)
    return cleaned.strip()


def transform_muse_glimmer_message(
    msg: Any, tool_param_order: dict[str, list[str]] | None = None
) -> Any:
    """Rewrite a Muse-Glimmer ``AIMessage`` in place (and return it).

    Two cases, selected empirically from the content:

    - **Native protocol** (``<|message|>`` / ``<|eom|>`` / ``<atem:`` /
      ``to=self`` / ``to=user`` markers present): parses ``<atem:invoke>`` /
      ``<function>`` / self-named / ``<atem:NAME>`` /
      ``to=<tool><|message|><args>`` tool calls; when present,
      populates ``msg.tool_calls`` (and ``tool_call_chunks`` for streaming
      consumers) and sets ``content`` to any user-facing text that accompanied
      the call (usually empty — the model emits tool XML in a ``to=<tool>``
      turn with no ``to=user`` reply). When there are no tool calls, sets
      ``content`` to the clean ``to=user`` reply (self-talk stripped).

    - **Repetition loop** (no protocol markers, but a hallucinated
      ``User:``/``Assistant:`` turn boundary after the real answer — the
      vLLM-Metal chat-template artifact): cuts the content at the first echo
      so only the real answer surfaces.

    Non-Muse-Glimmer-shaped messages (no protocol markers and no repetition
    loop) are returned unchanged.

    *tool_param_order* (when provided by the wrapper from the bound tool
    schemas) lets the ``to=<tool><|message|><args>[…]`` dialect map
    positional JSON-array args to the correct keyword names.

    The message object is mutated in place where possible (``content``) and
    via assignment for ``tool_calls`` / ``tool_call_chunks`` so LangChain's
    pydantic validation runs. Returns the same object for convenience.
    """
    if msg is None:
        return msg
    content = getattr(msg, "content", None)
    if not isinstance(content, str) or not content:
        return msg

    if detect_muse_glimmer_protocol(content):
        tool_calls = build_tool_calls_for_message(content, tool_param_order=tool_param_order)
        has_user_reply = _USER_MARKER in content
        if tool_calls and not has_user_reply:
            # The turn was a tool invocation: the model emitted a ``to=<tool>``
            # segment with ``<atem:function_calls>`` XML and no ``to=user``
            # reply. Mirror the OpenAI convention of an empty ``content``
            # alongside structured ``tool_calls``.
            clean_content = ""
        else:
            # Extract the user-facing reply (handles ``to=user`` slicing),
            # then strip any tool XML + leftover self-talk from that tail.
            # When the model emits both a reply and tool calls in one turn,
            # this keeps the reply text and drops the XML. Finally cut any
            # repetition loop the broken chat template appended after the
            # reply (caveat 1) so no echo surfaces.
            reply_tail = extract_user_reply(content)
            clean_content = _strip_tool_xml_and_self_talk(reply_tail)
            clean_content = strip_repetition_loop(clean_content)
    else:
        # No protocol markers — still cut the vLLM-Metal repetition loop if
        # the broken chat template appended a hallucinated echo.
        clean_content = strip_repetition_loop(content)

    try:
        msg.content = clean_content
    except Exception:  # pragma: no cover - pydantic validation edge
        logger.debug("muse_glimmer_content_set_failed content_len=%d", len(clean_content))

    if detect_muse_glimmer_protocol(content):
        tool_calls = build_tool_calls_for_message(content, tool_param_order=tool_param_order)
        if tool_calls:
            try:
                # ``AIMessage.tool_calls`` is a validated list[ToolCall];
                # assigning a list of plain dicts lets pydantic coerce them.
                # Each dict must carry ``name``, ``args``, ``id``.
                msg.tool_calls = tool_calls  # type: ignore[attr-defined]
            except Exception:
                logger.debug("muse_glimmer_tool_calls_set_failed count=%d", len(tool_calls))
            # Mirror into ``tool_call_chunks`` so streaming consumers
            # (flowjet's ToolCallArgAccumulator, the langchain agent
            # middleware) see them without re-deriving from content. Each
            # chunk: index/name/args(id).
            chunks = []
            for idx, tc in enumerate(tool_calls):
                import json

                chunks.append(
                    {
                        "index": idx,
                        "name": tc["name"],
                        "id": tc["id"],
                        "args": json.dumps(tc["args"], ensure_ascii=False),
                    }
                )
            try:
                msg.tool_call_chunks = chunks  # type: ignore[attr-defined]
            except Exception:
                logger.debug("muse_glimmer_tool_call_chunks_set_failed count=%d", len(chunks))

    return msg
