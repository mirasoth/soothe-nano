"""Muse-Glimmer response adapter for the oMLX OpenAI-compatible server.

The ``Muse-Glimmer-30B-4bit`` model served by the oMLX endpoint
(``http://…:9642/v1``) emits an internal self-talk protocol as raw text in
the OpenAI ``content`` field — the server passes it through unmodified:

- ``to=self<|message|>…internal reasoning…<|eom|>`` — hidden chain-of-thought
- ``<|start|>assistant to=user<|message|>ACTUAL REPLY`` — the user-facing text
- ``<|start|>assistant to=<toolname><|message|>`` — a tool-call block follows
- Tool calls are **not** structured ``tool_calls``. They are XML-in-content::

      <atem:function_calls>
      <atem:invoke name="calculator">
      <atem:parameter name="expression">2+2</atem:parameter>
      </atem:invoke>
      </atem:function_calls>

  with ``finish_reason: "stop"`` and ``tool_calls: null`` (even when
  ``tool_choice: "required"`` is sent).

This module converts a Muse-Glimmer raw ``content`` string into:

1. the clean user-facing text (self-talk and tool XML stripped), and
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
    "extract_user_reply",
    "parse_atem_tool_calls",
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
# Muse-Glimmer emits tool calls in (at least) two XML dialects depending on how
# tools were offered (native API ``tools`` param vs. agent ``bind_tools``):
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
# The model precedes a tool-call turn with ``to=<toolname><|message|>`` and a
# prose turn with ``to=user<|message|>``. We parse all three dialects.

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
_FUNCTION_BLOCK_RE = re.compile(
    r"<function(?:_call)?\s+name=\"(?P<name>[^\"]+)\"[^>]*>(?P<body>.*?)</function(?:_call)?>",
    re.DOTALL,
)
_ARG_RE = re.compile(
    r"<arg\s+name=\"(?P<key>[^\"]+)\"[^>]*>(?P<value>.*?)</arg>",
    re.DOTALL,
)
# Dialect 2b: self-closing ``<function_call name="TOOL" k="v" …/>`` (or
# paired) where args are attributes, not ``<arg>`` children. The model
# sometimes uses this instead of the child-arg form.
_FUNCTION_ATTR_RE = re.compile(
    r"<function(?:_call)?\s+name=\"(?P<name>[^\"]+)\"(?P<attrs>(?:\s+[a-zA-Z_][\w-]*=\"[^\"]*\")*)\s*/?>(?:</function(?:_call)?>)?",
)
# Dialect 4: ``<atem:TOOLNAME>{...json args...}</atem:TOOLNAME>`` — the tool
# name is the element local-name after ``atem:`` and the body is a JSON object
# of args (often ``{"args": "shell command"}`` for run_command). Also matches
# when the body is ``<arg>`` children for robustness.
_ATEM_TOOL_BLOCK_RE = re.compile(
    r"<atem:(?P<name>[a-zA-Z_][\w-]*)\b[^>]*>(?P<body>.*?)</atem:\1>",
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


def detect_muse_glimmer_protocol(text: str) -> bool:
    """Return ``True`` when *text* looks like Muse-Glimmer protocol output.

    Cheap marker check — we look for any of the distinctive tokens
    (``<|message|>``, ``<|eom|>``, ``to=self``, ``to=user``, or an
    ``<atem:`` tag). Used so non-Muse-Glimmer providers skip the transform
    entirely.
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


def parse_atem_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse Muse-Glimmer tool-call blocks from *text*.

    Handles the three dialects the model emits (see the parsing section
    above): ``<atem:invoke>`` with ``<atem:parameter>``, ``<function name>``
    with ``<arg>``, and self-named elements with attribute args
    (``<read_file file_path="…"/>``). Returns a list of
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
        "arg",
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


def build_tool_calls_for_message(text: str) -> list[dict[str, Any]]:
    """Build LangChain-style ``tool_calls`` dicts from Muse-Glimmer *text*.

    Each entry is ``{"name": str, "args": dict, "id": str}`` (matching the
    shape LangChain assigns to ``AIMessage.tool_calls``). Ids are
    deterministic (see :func:`_stable_tool_call_id`).
    """
    parsed = parse_atem_tool_calls(text)
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

    Strips the three tool-call dialects (``<atem:function_calls>`` envelopes,
    ``<function>`` blocks, and self-named tool elements) plus self-talk
    segments (``to=self<|message|>…<|eom|>``) and the turn-delimiter
    scaffolding (``<|start|>``, ``<|eom|>``, ``to=…<|message|>``,
    ``</atem:assistant>``). What remains is the ``to=user`` reply text (or
    any stray literal text the model emitted outside the protocol).
    """
    if not text:
        return text
    # Drop tool-call XML envelopes entirely, in all dialects.
    cleaned = _FUNC_CALLS_BLOCK_RE.sub("", text)
    cleaned = _FUNCTION_BLOCK_RE.sub("", cleaned)
    # Drop <atem:TOOLNAME>…</atem:TOOLNAME> blocks (dialect 4), but leave the
    # structural atem: envelope tags for the FUNC_CALLS sub above to handle.
    cleaned = _ATEM_TOOL_BLOCK_RE.sub("", cleaned)
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


def transform_muse_glimmer_message(msg: Any) -> Any:
    """Rewrite a Muse-Glimmer ``AIMessage`` in place (and return it).

    - Parses ``<atem:invoke>`` tool calls; when present, populates
      ``msg.tool_calls`` (and ``tool_call_chunks`` for streaming consumers)
      and sets ``content`` to any user-facing text that accompanied the call
      (usually empty — the model emits tool XML in a ``to=<tool>`` turn with
      no ``to=user`` reply).
    - When there are no tool calls, sets ``content`` to the clean
      ``to=user`` reply (self-talk stripped).
    - Non-Muse-Glimmer messages (no protocol markers) are returned unchanged.

    The message object is mutated in place where possible (``content``) and
    via ``add_messages``-style assignment for ``tool_calls`` /
    ``tool_call_chunks`` so LangChain's pydantic validation runs. Returns the
    same object for convenience.
    """
    if msg is None:
        return msg
    content = getattr(msg, "content", None)
    if not isinstance(content, str) or not content:
        return msg
    if not detect_muse_glimmer_protocol(content):
        return msg

    tool_calls = build_tool_calls_for_message(content)
    has_user_reply = _USER_MARKER in content
    if tool_calls and not has_user_reply:
        # The turn was a tool invocation: the model emitted a ``to=<tool>``
        # segment with ``<atem:function_calls>`` XML and no ``to=user`` reply.
        # Mirror the OpenAI convention of an empty ``content`` alongside
        # structured ``tool_calls``.
        clean_content = ""
    else:
        # Extract the user-facing reply (handles ``to=user`` slicing), then
        # strip any tool XML + leftover self-talk from that tail. When the
        # model emits both a reply and tool calls in one turn, this keeps the
        # reply text and drops the XML.
        reply_tail = extract_user_reply(content)
        clean_content = _strip_tool_xml_and_self_talk(reply_tail)

    try:
        msg.content = clean_content
    except Exception:  # pragma: no cover - pydantic validation edge
        logger.debug("muse_glimmer_content_set_failed content_len=%d", len(clean_content))

    if tool_calls:
        try:
            # ``AIMessage.tool_calls`` is a validated list[ToolCall]; assigning
            # a list of plain dicts lets pydantic coerce them. Each dict must
            # carry ``name``, ``args``, ``id``.
            msg.tool_calls = tool_calls  # type: ignore[attr-defined]
        except Exception:
            logger.debug("muse_glimmer_tool_calls_set_failed count=%d", len(tool_calls))
        # Mirror into ``tool_call_chunks`` so streaming consumers (flowjet's
        # ToolCallArgAccumulator, the langchain agent middleware) see them
        # without re-deriving from content. Each chunk: index/name/args(id).
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
