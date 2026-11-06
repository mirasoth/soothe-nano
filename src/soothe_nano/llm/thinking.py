"""Thinking-token filter for local-model LLM output.

Strips inline thinking blocks so reasoning tokens never surface to the
agent/UI as visible content, while capturing stripped content so it can be
forwarded to the TUI reasoning branch. ``strip_thinking`` handles complete
blocks in a fully-assembled string; ``ThinkingStreamFilter`` handles
streaming chunks with partial-tag buffering.

Captured reasoning is available via :attr:`ThinkingStreamFilter.captured_reasoning`
and :func:`strip_thinking` returns it via the optional ``capture_sink`` callback.

Opening tags may carry a ``:suffix`` or whitespace-separated attributes
(e.g. Hunyuan hy3/hy4's ``<think:232e4rfa0123>``), and the matching close tag
may be bare (``</think>``) or suffixed (``</think:232e4rfa0123>``).
"""

from __future__ import annotations

import logging
import re
from logging import Logger

__all__ = ["strip_thinking", "ThinkingStreamFilter"]

logger = logging.getLogger(__name__)


# --- compiled tag regexes -----------------------------------------------------
#
# ``_TAG`` names the three recognized thinking variants. After the variant an
# opening/closing tag may carry ``:suffix`` or whitespace-separated attributes
# up to the closing ``>``. A boundary (``:``/whitespace/``>``) is required so
# ``<thinkx>`` is not mistaken for ``<think>``.

_TAG = r"thinking|reasoning|think"
# Suffix/attributes fragment shared by open and close tags (non-capturing).
# Lazy ``[^>]*?`` leaves the final ``>`` for the literal; a ``:`` or whitespace
# boundary is required so ``<thinkx>`` is not mistaken for ``<think>``.
_ATTRS = r"(?::[^>]*?|\s+[^>]*?)?"

# Opening tag: <think>, <think:ID>, <think foo="bar">, <THINKING:abc>, ...
# Group 1 = variant (lowercased by the caller).
_THINK_OPEN_RE = re.compile(rf"<({_TAG}){_ATTRS}>", re.IGNORECASE)

# Complete block (open + content + matching close) for stateless stripping.
# Group 1 = tag variant, group 2 = inner content (for capture_sink). The close
# tag repeats the variant via \1 and tolerates the same optional suffix.
_THINK_BLOCK_RE = re.compile(
    rf"<({_TAG}){_ATTRS}>(.*?)</\1{_ATTRS}>",
    re.IGNORECASE | re.DOTALL,
)

# Close-tag regexes keyed by lowercased variant.
_THINK_CLOSE_RES: dict[str, re.Pattern[str]] = {
    variant: re.compile(rf"</{variant}{_ATTRS}>", re.IGNORECASE)
    for variant in ("think", "thinking", "reasoning")
}

_VARIANTS: tuple[str, ...] = ("thinking", "reasoning", "think")


def _resolve_logger(log: Logger | None) -> Logger:
    """Return *log* or the module logger when *log* is ``None``."""
    return log if log is not None else logger


def strip_thinking(
    text: str,
    *,
    logger: Logger | None = None,
    capture_sink: list[str] | None = None,
) -> str:
    """Remove complete ``<think>...</think>`` blocks from *text*.

    Matches ``<think>``, ``<thinking>``, and ``<reasoning>`` variants
    (case-insensitive; content may span newlines). Opening and closing tags
    may carry a ``:suffix`` or attributes (e.g. ``<think:232e4rfa0123>``).
    Each extracted thinking block is logged at ``DEBUG`` via *logger* (or the
    module logger) **before** removal, so the hidden reasoning remains
    recoverable from debug logs.

    When *capture_sink* is a list, each stripped block's inner text (without
    tags) is appended so callers can forward reasoning to the TUI.

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
        if capture_sink is not None:
            inner = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
            capture_sink.append(inner)
        return ""

    return _THINK_BLOCK_RE.sub(_record, text)


class ThinkingStreamFilter:
    """Stateful filter that strips thinking tags from a stream of text chunks.

    Feed each arriving content chunk through :meth:`feed` and emit the returned
    text to the consumer. Partial ``<think`` / ``</think`` (and ``<thinking>``,
    ``<reasoning>``, plus suffixed/attribute variants such as
    ``<think:232e4rfa0123>``) fragments that arrive split across chunk
    boundaries are buffered until the tag completes or is ruled out, so no tag
    fragments leak into visible output.

    Captured reasoning content (the text inside thinking blocks) is accumulated
    in :attr:`captured_reasoning` so callers can forward it to the TUI reasoning
    branch instead of discarding it.
    """

    def __init__(self, logger: Logger | None = None) -> None:
        self._log = _resolve_logger(logger)
        self._buffer: str = ""
        self._inside: bool = False
        self._variant: str | None = None
        self._reasoning_parts: list[str] = []

    @property
    def captured_reasoning(self) -> str:
        """Concatenated reasoning text captured from all completed thinking blocks."""
        return "".join(self._reasoning_parts)

    def feed(self, chunk: str) -> str:
        """Filter *chunk* and return text safe to emit to the consumer."""
        if not chunk:
            return ""
        self._buffer += chunk
        return self._drain()

    def finalize(self) -> str:
        """Flush remaining safe text at end-of-stream."""
        if self._inside:
            variant = self._variant
            segment = self._buffer
            self._log.debug(
                "thinking_tokens_unterminated variant=%s length=%d content=%r",
                variant,
                len(segment),
                segment,
            )
            # Capture unterminated reasoning too (the model was cut off mid-think).
            if segment:
                self._reasoning_parts.append(segment)
            self._buffer = ""
            self._inside = False
            self._variant = None
            return ""
        remaining = self._buffer
        self._buffer = ""
        return remaining

    # -- internals --------------------------------------------------------

    def _drain(self) -> str:
        out: list[str] = []
        while self._buffer:
            if self._inside:
                variant = self._variant
                assert variant is not None
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
                    # Capture the reasoning content inside the thinking block.
                    if segment:
                        self._reasoning_parts.append(segment)
                    self._buffer = self._buffer[match.end() :]
                    self._inside = False
                    self._variant = None
                    continue
                # No complete close tag yet: keep the whole buffer (reasoning
                # content + any partial close tag) until the next chunk arrives.
                # Nothing inside a thinking block is ever emitted as visible.
                return "".join(out)

            match = _THINK_OPEN_RE.search(self._buffer)
            if match:
                out.append(self._buffer[: match.start()])
                self._variant = match.group(1).lower()
                self._buffer = self._buffer[match.end() :]
                self._inside = True
                continue

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
        """Length of a trailing buffer slice that could still become an opening tag.

        Holds back fragments like ``<think``, ``<think:232``, or ``<think foo=``
        that may complete on the next chunk. Because an opening tag can carry an
        arbitrary suffix/attributes up to ``>``, any trailing ``<think...`` with
        no ``>`` yet is a potential prefix.
        """
        idx = self._buffer.rfind("<")
        if idx < 0:
            return 0
        tail = self._buffer[idx:].lower()
        # A '>' means either a complete tag (would have matched above) or an
        # invalid one; neither is a partial opening tag worth buffering.
        if ">" in tail:
            return 0
        rest = tail[1:]  # after '<'
        # A valid partial opening tag either is a prefix of a variant name
        # (e.g. "<thi") or starts with a full variant name followed by a
        # suffix/attributes (e.g. "<think:232", "<think foo=").
        return (
            len(self._buffer) - idx
            if any(v.startswith(rest) or rest.startswith(v) for v in _VARIANTS)
            else 0
        )
