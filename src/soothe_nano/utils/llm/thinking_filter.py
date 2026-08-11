"""Thinking-token filter for local-model LLM output.

Local reasoning models (DeepSeek-R1, QwQ, GLM with thinking enabled, ...)
emit their chain-of-thought inline as ``<think>...</think>`` blocks (some
variants use ``<thinking>`` or ``<reasoning>``). This module strips those
blocks from model text so reasoning tokens never surface to the agent/UI,
while recording the stripped content at ``DEBUG`` level first so it stays
inspectable during debugging (the "record before strip" design rule).

Two entry points:

- :func:`strip_thinking` -- stateless removal of *complete* thinking blocks
  from a fully-assembled response string.
- :class:`ThinkingStreamFilter` -- stateful filter for streaming chunks that
  buffers partial ``<think`` / ``</think`` tag fragments split across chunk
  boundaries so no tag fragments leak into visible output.

The filter is provider-agnostic: it handles the inline XML-tag style used by
DeepSeek-R1-style models. API-level ``reasoning_content`` fields are captured
in the wrapper layer (see ``wrappers.py``) and routed through here as text.
"""

from __future__ import annotations

import logging
import re
from logging import Logger

__all__ = ["strip_thinking", "ThinkingStreamFilter"]

logger = logging.getLogger(__name__)


# --- compiled tag regexes -----------------------------------------------------

# Complete opening tag, capturing the variant so it can be paired with the
# matching close tag. ``think`` is listed last; the trailing ``>`` makes
# ``<think>`` and ``<thinking>`` unambiguous regardless.
_THINK_OPEN_RE = re.compile(r"<(thinking|reasoning|think)>", re.IGNORECASE)

# Any complete closing tag (used for general detection).
_THINK_CLOSE_RE = re.compile(r"</(?:thinking|reasoning|think)>", re.IGNORECASE)

# Complete block (open + content + matching close) for stateless stripping.
# The backreference (``\1``) pairs ``<thinking>`` with ``</thinking>`` so a
# stray ``</think>`` fragment inside the reasoning text cannot close the block
# prematurely. ``re.DOTALL`` lets the content span newlines.
_THINK_BLOCK_RE = re.compile(
    r"<(thinking|reasoning|think)>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

# Per-variant close-tag matchers used by the streaming filter so an open
# ``<thinking>`` only closes on ``</thinking>`` (not ``</think>``).
_THINK_CLOSE_RES: dict[str, re.Pattern[str]] = {
    "think": re.compile(r"</think>", re.IGNORECASE),
    "thinking": re.compile(r"</thinking>", re.IGNORECASE),
    "reasoning": re.compile(r"</reasoning>", re.IGNORECASE),
}

# Lowercase complete opening tags, used for partial-prefix detection at chunk
# boundaries by the streaming filter.
_OPEN_TAGS_LOWER: tuple[str, ...] = ("<think>", "<thinking>", "<reasoning>")


def _resolve_logger(log: Logger | None) -> Logger:
    """Return *log* or the module logger when *log* is ``None``."""
    return log if log is not None else logger


def strip_thinking(text: str, *, logger: Logger | None = None) -> str:
    """Remove complete ``<think>...</think>`` blocks from *text*.

    Matches ``<think>``, ``<thinking>``, and ``<reasoning>`` variants
    (case-insensitive; content may span newlines). Each extracted thinking
    block is logged at ``DEBUG`` via *logger* (or the module logger) **before**
    removal, so the hidden reasoning remains recoverable from debug logs.

    Only complete blocks (open + matching close) are removed; an unterminated
    opening tag is left untouched here -- streaming truncation is handled by
    :class:`ThinkingStreamFilter.finalize`.
    """
    if not text:
        return text
    rec_logger = _resolve_logger(logger)

    def _record(match: re.Match[str]) -> str:
        variant = match.group(1)
        block = match.group(0)
        rec_logger.debug(
            "thinking_tokens_stripped variant=%s length=%d content=%r",
            variant,
            len(block),
            block,
        )
        return ""

    return _THINK_BLOCK_RE.sub(_record, text)


class ThinkingStreamFilter:
    """Stateful filter that strips thinking tags from a stream of text chunks.

    Feed each arriving content chunk through :meth:`feed` and emit the returned
    text to the consumer. Partial ``<think`` / ``</think`` (and ``<thinking>``,
    ``<reasoning>``) fragments that arrive split across chunk boundaries are
    buffered until the tag completes or is ruled out, so no tag fragments leak
    into visible output.

    Each completed thinking segment is logged at ``DEBUG`` as it closes. Call
    :meth:`finalize` at end-of-stream to flush any remaining safe literal text
    and log unterminated thinking fragments.
    """

    def __init__(self, logger: Logger | None = None) -> None:
        self._log = _resolve_logger(logger)
        self._buffer: str = ""
        self._inside: bool = False
        # Open-tag variant ("think" | "thinking" | "reasoning") when inside.
        self._variant: str | None = None

    def feed(self, chunk: str) -> str:
        """Filter *chunk* and return text safe to emit to the consumer."""
        if not chunk:
            return ""
        self._buffer += chunk
        return self._drain()

    def finalize(self) -> str:
        """Flush remaining safe text at end-of-stream.

        Any buffered literal text (e.g. a trailing partial open-tag prefix that
        never completed into a real tag) is returned. If a thinking block was
        left unterminated, its buffered fragment is logged at ``DEBUG`` with an
        ``unterminated`` note and suppressed from the returned text.
        """
        if self._inside:
            variant = self._variant
            segment = self._buffer
            self._log.debug(
                "thinking_tokens_unterminated variant=%s length=%d content=%r",
                variant,
                len(segment),
                segment,
            )
            self._buffer = ""
            self._inside = False
            self._variant = None
            return ""
        # Outside a thinking block: any held partial open-tag prefix is just
        # literal text now that the stream has ended, so it is safe to emit.
        remaining = self._buffer
        self._buffer = ""
        return remaining

    # -- internals --------------------------------------------------------

    def _drain(self) -> str:
        out: list[str] = []
        while self._buffer:
            if self._inside:
                variant = self._variant
                assert variant is not None  # set when entering the inside state
                close_re = _THINK_CLOSE_RES[variant]
                match = close_re.search(self._buffer)
                if match:
                    segment = self._buffer[: match.start()]
                    self._log.debug(
                        "thinking_tokens_streamed variant=%s length=%d content=%r",
                        variant,
                        len(segment),
                        segment,
                    )
                    self._buffer = self._buffer[match.end() :]
                    self._inside = False
                    self._variant = None
                    continue
                # No close tag yet: hold all buffered reasoning content and
                # emit only the literal text accumulated before this block.
                return "".join(out)

            match = _THINK_OPEN_RE.search(self._buffer)
            if match:
                # Emit literal text preceding the opening tag.
                out.append(self._buffer[: match.start()])
                self._variant = match.group(1).lower()
                self._buffer = self._buffer[match.end() :]
                self._inside = True
                continue

            # No complete opening tag: hold back a trailing partial-tag prefix
            # (e.g. buffer ends with "<thi") that may still complete into a tag
            # on the next chunk; emit the rest as safe literal text.
            held = self._trailing_open_prefix_len()
            if held:
                out.append(self._buffer[:-held])
                self._buffer = self._buffer[-held:]
            else:
                out.append(self._buffer)
                self._buffer = ""
            break
        return "".join(out)

    def _trailing_open_prefix_len(self) -> int:
        """Length of the trailing buffer slice that could still become an opening tag.

        Returns 0 when the buffer does not end with a prefix of any opening
        tag, so the whole buffer is safe to emit.
        """
        idx = self._buffer.rfind("<")
        if idx < 0:
            return 0
        tail = self._buffer[idx:].lower()
        if any(tag.startswith(tail) for tag in _OPEN_TAGS_LOWER):
            return len(self._buffer) - idx
        return 0
