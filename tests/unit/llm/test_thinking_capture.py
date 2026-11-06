"""Tests for thinking-token capture in strip_thinking and ThinkingStreamFilter.

Verifies that stripped thinking content is captured via the capture_sink /
captured_reasoning API so it can be forwarded to the TUI reasoning branch,
while the visible text remains free of thinking tags.
"""

from __future__ import annotations

from soothe_nano.llm.thinking import ThinkingStreamFilter, strip_thinking

# --- strip_thinking with capture_sink ---


def test_strip_thinking_captures_inner_content() -> None:
    """Captured inner text is appended to the sink list."""
    sink: list[str] = []
    result = strip_thinking(
        "before <thinking>secret reasoning</thinking> after",
        capture_sink=sink,
    )
    assert result == "before  after"
    assert sink == ["secret reasoning"]


def test_strip_thinking_without_sink_discards_content() -> None:
    """Without a sink, reasoning is still stripped but not captured."""
    result = strip_thinking("before <thinking>hidden</thinking> after")
    assert result == "before  after"


def test_strip_thinking_multiple_blocks_all_captured() -> None:
    """Multiple thinking blocks are all captured in order."""
    sink: list[str] = []
    result = strip_thinking(
        "a <think>first</think> b <reasoning>second</reasoning> c",
        capture_sink=sink,
    )
    assert result == "a  b  c"
    assert sink == ["first", "second"]


def test_strip_thinking_empty_block_captured_as_empty() -> None:
    """Empty thinking blocks produce empty captured strings."""
    sink: list[str] = []
    result = strip_thinking("text <thinking></thinking> end", capture_sink=sink)
    assert result == "text  end"
    assert sink == [""]


def test_strip_thinking_multiline_content_captured() -> None:
    """Multi-line thinking content is captured verbatim."""
    sink: list[str] = []
    result = strip_thinking(
        "start <thinking>line1\nline2\nline3</thinking> end",
        capture_sink=sink,
    )
    assert result == "start  end"
    assert sink == ["line1\nline2\nline3"]


def test_strip_thinking_no_blocks_no_capture() -> None:
    """No thinking blocks means no capture and no change."""
    sink: list[str] = []
    result = strip_thinking("plain text", capture_sink=sink)
    assert result == "plain text"
    assert sink == []


# --- ThinkingStreamFilter.captured_reasoning ---


def test_filter_captures_complete_block() -> None:
    """A complete thinking block is captured by the stream filter."""
    filt = ThinkingStreamFilter()
    out1 = filt.feed("hello <thinking>reason")
    out2 = filt.feed("ing here</thinking> world")
    assert out1 == "hello "
    assert out2 == " world"
    assert filt.captured_reasoning == "reasoning here"


def test_filter_captures_multiple_blocks() -> None:
    """Multiple thinking blocks in a stream are all captured."""
    filt = ThinkingStreamFilter()
    filt.feed("<think>first</think> middle ")
    filt.feed("<reasoning>second</reasoning> end")
    assert filt.captured_reasoning == "firstsecond"


def test_filter_no_capture_without_thinking_tags() -> None:
    """No thinking tags means no captured reasoning."""
    filt = ThinkingStreamFilter()
    filt.feed("just regular text")
    assert filt.captured_reasoning == ""


def test_filter_unterminated_block_captured_on_finalize() -> None:
    """Unterminated thinking blocks are captured on finalize (model cut off mid-think).

    The content between the opening tag and end-of-stream is treated as
    reasoning even though the closing tag never arrived — this matches the
    behavior of capturing complete blocks.
    """
    filt = ThinkingStreamFilter()
    filt.feed("text <thinking>unterminated")
    result = filt.finalize()
    assert result == ""
    assert filt.captured_reasoning == "unterminated"


def test_filter_empty_content_no_capture() -> None:
    """Empty content produces no captured reasoning."""
    filt = ThinkingStreamFilter()
    filt.feed("")
    assert filt.captured_reasoning == ""


# --- suffixed/attribute tags (Hunyuan hy3/hy4: <think:ID>) ---


def test_strip_thinking_suffixed_tag() -> None:
    """hy4's `<think:ID>...</think:ID>` is stripped and captured."""
    sink: list[str] = []
    result = strip_thinking(
        "before <think:232e4rfa0123>secret reasoning</think:232e4rfa0123> after",
        capture_sink=sink,
    )
    assert result == "before  after"
    assert sink == ["secret reasoning"]


def test_strip_thinking_suffixed_open_bare_close() -> None:
    """A suffixed opening tag pairs with a bare closing tag."""
    sink: list[str] = []
    result = strip_thinking("a <think:abc123>secret</think> b", capture_sink=sink)
    assert result == "a  b"
    assert sink == ["secret"]


def test_strip_thinking_attribute_tag() -> None:
    """Whitespace-separated attributes on the opening tag are tolerated."""
    sink: list[str] = []
    result = strip_thinking('a <think id="x">secret</think> b', capture_sink=sink)
    assert result == "a  b"
    assert sink == ["secret"]


def test_strip_thinking_suffixed_variants() -> None:
    """`<thinking:ID>` and `<reasoning:ID>` are handled too, case-insensitively."""
    sink: list[str] = []
    result = strip_thinking(
        "a <THINKING:zz>one</THINKING:zz> b <reasoning:q>two</reasoning:q> c",
        capture_sink=sink,
    )
    assert result == "a  b  c"
    assert sink == ["one", "two"]


def test_strip_thinking_does_not_match_lookalike_tag() -> None:
    """`<thinkx>` is not mistaken for `<think>`."""
    assert strip_thinking("keep <thinkx>this</thinkx> text") == ("keep <thinkx>this</thinkx> text")


def test_filter_suffixed_tag_split_across_chunks() -> None:
    """A suffixed tag split mid-ID is buffered and stripped without leaking."""
    filt = ThinkingStreamFilter()
    out = "".join(
        [
            filt.feed("hello <think:232e4rfa"),
            filt.feed("0123>secret rea"),
            filt.feed("soning</think:232e4"),
            filt.feed("rfa0123> world"),
            filt.finalize(),
        ]
    )
    assert out == "hello  world"
    assert filt.captured_reasoning == "secret reasoning"


def test_filter_suffixed_unterminated_captured_on_finalize() -> None:
    """Unterminated suffixed blocks are captured on finalize."""
    filt = ThinkingStreamFilter()
    assert filt.feed("prefix <think:ID>unterminated") == "prefix "
    assert filt.finalize() == ""
    assert filt.captured_reasoning == "unterminated"
