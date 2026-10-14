"""Thinking-token filter for local-model LLM output.

Strips inline thinking blocks so reasoning tokens never surface to the
agent/UI as visible content, while capturing stripped content so it can be
forwarded to the TUI reasoning branch. ``strip_thinking`` handles complete
blocks in a fully-assembled string; ``ThinkingStreamFilter`` handles
streaming chunks with partial-tag buffering.

Captured reasoning is available via :attr:`ThinkingStreamFilter.captured_reasoning`
and :func:`strip_thinking` returns it via the optional ``capture_sink`` callback.

The core regex work and stream-filter state machine are delegated to the
Rust extension (``soothe-nano-utils``) via PyO3. Debug logging of stripped
blocks stays Python-side so log records carry the full Python logger context.
"""

from __future__ import annotations

import logging
import re
from logging import Logger

from soothe_nano._rust_compat import (
    rust_thinking_stream_filter_new,
    strip_thinking_rust,
)

__all__ = ["strip_thinking", "ThinkingStreamFilter"]

logger = logging.getLogger(__name__)

# Reused for debug-logging fidelity only -- the actual stripping is done in Rust.
_THINK_BLOCK_RE = re.compile(
    r"<(thinking|reasoning|think)>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL,
)


def _resolve_logger(log: Logger | None) -> Logger:
    """Return *log* or the module logger when *log* is ``None``."""
    return log if log is not None else logger


def strip_thinking(
    text: str,
    *,
    logger: Logger | None = None,
    capture_sink: list[str] | None = None,
) -> str:
    """Remove complete thinking blocks from *text*.

    Matches ``<think>``, ``<thinking>``, and ``<reasoning>`` variants
    (case-insensitive; content may span newlines). Each extracted thinking
    block is logged at ``DEBUG`` via *logger* (or the module logger) **before**
    removal, so the hidden reasoning remains recoverable from debug logs.

    When *capture_sink* is a list, each stripped block's inner text (without
    tags) is appended so callers can forward reasoning to the TUI.

    Only complete blocks (open + matching close) are removed; an unterminated
    opening tag is left untouched here -- streaming truncation is handled by
    :class:`ThinkingStreamFilter.finalize`.
    """
    if not text:
        return text
    rec_logger = _resolve_logger(logger)

    # Rust does the regex work and returns captured inner contents.
    stripped, captured = strip_thinking_rust(text)

    # Python-side debug logging (Rust skips logging by design).
    if captured and rec_logger.isEnabledFor(logging.DEBUG):
        for match in _THINK_BLOCK_RE.finditer(text):
            variant = match.group(1)
            block = match.group(0)
            rec_logger.debug(
                "thinking_tokens_stripped variant=%s length=%d content=%r",
                variant,
                len(block),
                block,
            )

    if capture_sink is not None:
        capture_sink.extend(captured)

    return stripped


class ThinkingStreamFilter:
    """Stateful filter that strips thinking tags from a stream of text chunks.

    Feed each arriving content chunk through :meth:`feed` and emit the returned
    text to the consumer. Partial ``<think`` / ``</think`` (and ``<thinking>``,
    ``<reasoning>``) fragments that arrive split across chunk boundaries are
    buffered until the tag completes or is ruled out, so no tag fragments leak
    into visible output.

    Captured reasoning content (the text inside thinking blocks) is accumulated
    in :attr:`captured_reasoning` so callers can forward it to the TUI reasoning
    branch instead of discarding it.

    The core state machine is delegated to the Rust extension; the *logger*
    parameter is accepted for API compatibility but debug logging is a no-op
    (the Rust filter handles buffering and capture natively).
    """

    def __init__(self, logger: Logger | None = None) -> None:
        # Logger is kept for API compatibility; the Rust filter handles all
        # buffering/capture natively without Python-side debug logging.
        self._log = _resolve_logger(logger)
        self._inner = rust_thinking_stream_filter_new()

    @property
    def captured_reasoning(self) -> str:
        """Concatenated reasoning text captured from all completed thinking blocks."""
        return self._inner.captured_reasoning

    def feed(self, chunk: str) -> str:
        """Filter *chunk* and return text safe to emit to the consumer."""
        if not chunk:
            return ""
        return self._inner.feed(chunk)

    def finalize(self) -> str:
        """Flush remaining safe text at end-of-stream."""
        return self._inner.finalize()
