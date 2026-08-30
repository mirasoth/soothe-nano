"""Token usage helpers for CoreAgent and direct LLM calls."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import LLMResult


class _TokenTotalTarget(Protocol):
    total_tokens_used: int


@dataclass
class DirectLLMTokenTarget:
    """Mutable token sink for direct (non-CoreAgent-graph) LLM invocations."""

    total_tokens_used: int = 0


_token_target: ContextVar[_TokenTotalTarget | None] = ContextVar(
    "token_target",
    default=None,
)
_direct_llm_token_accumulation: ContextVar[bool] = ContextVar(
    "direct_llm_token_accumulation",
    default=False,
)


@contextmanager
def loop_token_accumulation_scope(target: _TokenTotalTarget):
    """Bind token accumulation to `target` for the current async context."""
    token = _token_target.set(target)
    try:
        yield
    finally:
        _token_target.reset(token)


@contextmanager
def direct_llm_token_call_scope():
    """Mark the current call as a direct (non-CoreAgent) LLM invocation."""
    token = _direct_llm_token_accumulation.set(True)
    try:
        yield
    finally:
        _direct_llm_token_accumulation.reset(token)


def merge_direct_llm_tokens_into_state(
    state: _TokenTotalTarget,
    source: _TokenTotalTarget,
) -> int:
    """Fold tokens accumulated before state existed into `state`."""
    delta = max(0, int(getattr(source, "total_tokens_used", 0) or 0))
    if delta > 0:
        state.total_tokens_used += delta
    return delta


def accumulate_loop_tokens_from_llm_result(response: LLMResult) -> int:
    """Add direct LLM usage into the active token target when scoped."""
    if not _direct_llm_token_accumulation.get():
        return 0
    target = _token_target.get()
    if target is None:
        return 0
    from soothe_nano.llm.observability import extract_token_counts_from_llm_result

    counts = extract_token_counts_from_llm_result(response)
    if not counts:
        return 0
    delta = int(counts.get("total_tokens") or 0)
    if delta <= 0:
        delta = int(counts.get("input_tokens") or 0) + int(counts.get("output_tokens") or 0)
    if delta <= 0:
        return 0
    target.total_tokens_used += delta
    return delta


def _token_counts_from_ai_message(msg: BaseMessage) -> dict[str, int] | None:
    """Return prompt/completion/total for one AI message when usage metadata is present."""
    usage = getattr(msg, "usage_metadata", None)
    if isinstance(usage, dict) and usage:
        prompt = int(usage.get("input_tokens") or 0)
        completion = int(usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or 0) or prompt + completion
        if total > 0:
            return {"prompt": prompt, "completion": completion, "total": total}
    metadata = getattr(msg, "response_metadata", None) or {}
    if isinstance(metadata, dict):
        token_usage = metadata.get("token_usage")
        if isinstance(token_usage, dict) and token_usage:
            prompt = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
            completion = int(
                token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
            )
            total = int(token_usage.get("total_tokens") or 0) or prompt + completion
            if total > 0:
                return {"prompt": prompt, "completion": completion, "total": total}
    return None


def _sum_token_usage_from_messages(
    messages: list[BaseMessage],
    *,
    include_chunks: bool,
) -> dict[str, int]:
    """Sum usage across AI messages (optionally including stream chunks)."""
    from langchain_core.messages import AIMessage, AIMessageChunk

    prompt = completion = total = 0
    for msg in messages:
        if isinstance(msg, AIMessage):
            counts = _token_counts_from_ai_message(msg)
        elif include_chunks and isinstance(msg, AIMessageChunk):
            counts = _token_counts_from_ai_message(msg)
        else:
            continue
        if counts is None:
            continue
        prompt += counts["prompt"]
        completion += counts["completion"]
        total += counts["total"]
    if total <= 0:
        return {}
    return {"prompt": prompt, "completion": completion, "total": total}


def extract_token_usage_from_messages(messages: list[BaseMessage]) -> dict[str, int]:
    """Sum prompt/completion/total across all CoreAgent AI turns in `messages`."""
    usage = _sum_token_usage_from_messages(messages, include_chunks=False)
    if usage:
        return usage
    return _sum_token_usage_from_messages(messages, include_chunks=True)


def coerce_total_tokens_used(value: Any) -> int:
    """Parse a non-negative `total_tokens_used` field from event payloads."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


# IG-761: Per-message structural token overhead for role tags + separators.
# This is a documented approximation for the tokens a provider adds around
# each message (role tag, message boundary) that are not in ``.content``.
# It is intentionally a small constant rather than a magic number inlined at
# each call site, and it is applied only on the estimation path (never added
# to actual usage returned by providers).
_STRUCTURAL_TOKENS_PER_MESSAGE = 3


def estimate_token_usage(
    messages: list[BaseMessage],
    *,
    model: str | None = None,
) -> dict[str, int]:
    """Return `{input_tokens, output_tokens, total_tokens}` for a message list.

    Unified token estimation. Actual-first, estimate-on-demand:

    1. If any AI message carries `usage_metadata`, sum actual usage across
       all AI turns (via :func:`extract_token_usage_from_messages`) and return
       it. No estimated counts are added on this path — no double-counting.
    2. Otherwise, estimate:
       - `input_tokens`  = model-aware `count_tokens` over prompt messages
         (Human / System / Tool messages) plus structural overhead per message.
       - `output_tokens` = model-aware `count_tokens` over AI message
         content plus structural overhead per AI message.
       - `total_tokens`  = `input_tokens + output_tokens`.

    Args:
        messages: Full message list (prompt + response) for one or more turns.
        model: Optional model name hint for tokenizer selection. `None`
            preserves the default (`cl100k_base`) encoding.

    Returns:
        Dict with `input_tokens`, `output_tokens`, `total_tokens`.
        A `source` key (`"actual"` or `"estimated"`) is included for
        observability so callers can distinguish the two paths.
    """
    # Path 1: actual usage from provider responses (actual-first).
    actual = extract_token_usage_from_messages(messages)
    if actual and actual.get("total", 0) > 0:
        return {
            "input_tokens": int(actual.get("prompt", 0)),
            "output_tokens": int(actual.get("completion", 0)),
            "total_tokens": int(actual.get("total", 0)),
            "source": "actual",
        }

    # Path 2: estimation over the full message structure (input + output).
    from langchain_core.messages import AIMessage, AIMessageChunk

    input_tokens = 0
    output_tokens = 0
    message_count = 0

    for msg in messages:
        is_ai = isinstance(msg, (AIMessage, AIMessageChunk))
        content = getattr(msg, "content", "")
        text_tokens = _count_content_tokens(content, model=model)
        if is_ai:
            output_tokens += text_tokens
        else:
            input_tokens += text_tokens
        message_count += 1

    # Structural overhead: role tags + separators per message.
    input_tokens += _STRUCTURAL_TOKENS_PER_MESSAGE * message_count

    total = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "source": "estimated",
    }


def _count_content_tokens(content: Any, *, model: str | None) -> int:
    """Count tokens in a message content (string or block list)."""
    from soothe_nano.utils.token_counting import count_tokens

    if content is None:
        return 0
    if isinstance(content, str):
        return count_tokens(content, model=model)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, str):
                total += count_tokens(block, model=model)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    total += count_tokens(text, model=model)
                else:
                    total += count_tokens(str(block), model=model)
            else:
                total += count_tokens(str(block), model=model)
        return total
    return count_tokens(str(content), model=model)


__all__ = [
    "DirectLLMTokenTarget",
    "accumulate_loop_tokens_from_llm_result",
    "coerce_total_tokens_used",
    "direct_llm_token_call_scope",
    "estimate_token_usage",
    "extract_token_usage_from_messages",
    "loop_token_accumulation_scope",
    "merge_direct_llm_tokens_into_state",
]
