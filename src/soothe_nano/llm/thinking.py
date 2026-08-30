"""Thinking-token filter for local-model LLM output.

Strips inline thinking blocks so reasoning tokens never surface to the
agent/UI, while logging stripped content at `DEBUG` first so it stays
inspectable. `strip_thinking` handles complete blocks in a fully-assembled
string; `ThinkingStreamFilter` handles streaming chunks with partial-tag
buffering.
"""

from __future__ import annotations

import logging
import re
from logging import Logger

__all__ = ["strip_thinking", "ThinkingStreamFilter"]

logger = logging.getLogger(__name__)


# --- compiled tag regexes -----------------------------------------------------

_THINK_OPEN_RE = re.compile(r"<(thinking|reasoning|think)>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</(?:thinking|reasoning|think)>", re.IGNORECASE)

# Complete block (open + content + matching close) for stateless stripping.
_THINK_BLOCK_RE = re.compile(
    r"<(thinking|reasoning|think)>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

_THINK_CLOSE_RES: dict[str, re.Pattern[str]] = {
    "think": re.compile(r"</think>", re.IGNORECASE),
    "thinking": re.compile(r"</thinking>", re.IGNORECASE),
    "reasoning": re.compile(r"</reasoning>", re.IGNORECASE),
}

_OPEN_TAGS_LOWER: tuple[str, ...] = ("<think>", "<thinking>", "<reasoning>")


def _resolve_logger(log: Logger | None) -> Logger:
    """Return *log* or the module logger when *log* is `None`."""
    return log if log is not None else logger


def strip_thinking(text: str, *, logger: Logger | None = None) -> str:
    """Remove complete `<think>...</think>` blocks from *text*.

    Matches `<think>`, `<thinking>`, and `<reasoning>` variants
    (case-insensitive; content may span newlines). Each extracted thinking
    block is logged at `DEBUG` via *logger* (or the module logger) **before**
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
    text to the consumer. Partial `<think` / `</think` (and `<thinking>`,
    `<reasoning>`) fragments that arrive split across chunk boundaries are
    buffered until the tag completes or is ruled out, so no tag fragments leak
    into visible output.
    """

    def __init__(self, logger: Logger | None = None) -> None:
        self._log = _resolve_logger(logger)
        self._buffer: str = ""
        self._inside: bool = False
        self._variant: str | None = None

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
                    self._buffer = self._buffer[match.end() :]
                    self._inside = False
                    self._variant = None
                    continue
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
        """Length of the trailing buffer slice that could still become an opening tag."""
        idx = self._buffer.rfind("<")
        if idx < 0:
            return 0
        tail = self._buffer[idx:].lower()
        if any(tag.startswith(tail) for tag in _OPEN_TAGS_LOWER):
            return len(self._buffer) - idx
        return 0
