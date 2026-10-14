"""Thinking-token filter for local-model LLM output.

Strips inline thinking blocks so reasoning tokens never surface to the
agent/UI as visible content, while capturing stripped content so it can be
forwarded to the TUI reasoning branch. ``strip_thinking`` handles complete
blocks in a fully-assembled string; ``ThinkingStreamFilter`` handles
streaming chunks with partial-tag buffering.

Captured reasoning is available via :attr:`ThinkingStreamFilter.captured_reasoning`
and :func:`strip_thinking` returns it via the optional ``capture_sink`` callback.

The core regex work and stream-filter state machine are delegated to the
Rust extension (``soothe-nano-utils``) via PyO3.
"""

from __future__ import annotations

from logging import Logger

from soothe_nano._rust_compat import (
    rust_thinking_stream_filter_new,
    strip_thinking_rust,
)

__all__ = ["strip_thinking", "ThinkingStreamFilter"]


def strip_thinking(
    text: str,
    *,
    logger: Logger | None = None,  # noqa: ARG001 — kept for API compatibility
    capture_sink: list[str] | None = None,
) -> str:
    """Remove complete thinking blocks from *text*.

    Matches ``<think>``, ``<thinking>``, and ``<reasoning>`` variants
    (case-insensitive; content may span newlines). When *capture_sink* is a
    list, each stripped block's inner text (without tags) is appended so
    callers can forward reasoning to the TUI.

    Only complete blocks (open + matching close) are removed; an unterminated
    opening tag is left untouched here -- streaming truncation is handled by
    :class:`ThinkingStreamFilter.finalize`.
    """
    if not text:
        return text

    stripped, captured = strip_thinking_rust(text)

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

    The core state machine is delegated to the Rust extension.
    """

    def __init__(self, logger: Logger | None = None) -> None:  # noqa: ARG002
        # Logger is accepted for API compatibility but unused — the Rust filter
        # handles all buffering and capture natively.
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
