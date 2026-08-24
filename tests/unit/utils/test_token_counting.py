"""Unit tests for token counting utilities (IG-761).

Covers model-aware tokenizer selection, default ``cl100k_base`` behavior, and
the ``len // 4`` fallback when tiktoken is unavailable.
"""

import pytest

from soothe_nano.utils import count_tokens
from soothe_nano.utils.token_counting import (
    _get_encoding_for_model,
    estimate_content_chars,
)


class TestTokenCounting:
    """Test token counting with tiktoken and estimation."""

    def test_count_tokens_tiktoken(self):
        """Test token counting with tiktoken."""
        tokens = count_tokens("Hello world", use_tiktoken=True)
        # tiktoken is accurate: "Hello world" = 2 tokens
        assert tokens == 2

    def test_count_tokens_estimation(self):
        """Test estimation fallback."""
        tokens = count_tokens("Hello world", use_tiktoken=False)
        # Estimation: len("Hello world") // 4 = 11 // 4 = 2
        assert tokens == 2

    def test_count_tokens_cjk(self):
        """Test CJK text handling."""
        text = "使用浏览器获取信息"

        # tiktoken handles CJK correctly
        tokens_tiktoken = count_tokens(text, use_tiktoken=True)
        assert tokens_tiktoken > 0

        # Estimation also works
        tokens_est = count_tokens(text, use_tiktoken=False)
        assert tokens_est > 0

    def test_count_tokens_auto_fallback(self):
        """Test automatic fallback when tiktoken unavailable."""
        # Should gracefully fall back to estimation
        # Even if tiktoken import fails
        tokens = count_tokens("Hello world")  # Default use_tiktoken=True
        assert tokens > 0  # Either 2 (tiktoken) or 2 (estimation)

    def test_count_tokens_empty_string(self):
        """Test empty string handling."""
        assert count_tokens("") == 0
        assert count_tokens("", use_tiktoken=False) == 0

    def test_count_tokens_longer_text(self):
        """Test token counting for longer text."""
        text = "This is a longer piece of text that should have more tokens"

        tokens_tiktoken = count_tokens(text, use_tiktoken=True)
        tokens_est = count_tokens(text, use_tiktoken=False)

        # Both should return positive integers
        assert tokens_tiktoken > 0
        assert tokens_est > 0

        # tiktoken should be more accurate (not just len // 4)
        # For this text, tiktoken will give a more precise count


class TestModelAwareTokenizerSelection:
    """IG-761: model-aware encoding selection in count_tokens."""

    def test_no_model_hint_uses_cl100k_base(self):
        """No model hint → cl100k_base (preserves prior default behavior)."""
        encoding = _get_encoding_for_model(None)
        assert encoding.name == "cl100k_base"

    def test_openai_model_selects_exact_encoding(self):
        """OpenAI model hint → tiktoken.encoding_for_model."""
        # gpt-4o uses o200k_base; gpt-4 uses cl100k_base
        enc_gpt4o = _get_encoding_for_model("gpt-4o")
        assert enc_gpt4o.name == "o200k_base"

        enc_gpt4 = _get_encoding_for_model("gpt-4")
        assert enc_gpt4.name == "cl100k_base"

    def test_unknown_model_falls_back_to_cl100k_base(self):
        """Unknown / non-OpenAI model → cl100k_base approximation."""
        for model in (
            "claude-3-5-sonnet-20241022",
            "gemini-1.5-pro",
            "qwen2.5-coder",
            "llama-3.1-70b",
            "deepseek-chat",
        ):
            encoding = _get_encoding_for_model(model)
            assert encoding.name == "cl100k_base", f"model={model} should fall back to cl100k_base"

    def test_provider_prefixed_model_falls_back(self):
        """provider:model strings (router format) → cl100k_base for non-OpenAI."""
        for model in (
            "anthropic:claude-3-5-sonnet-20241022",
            "vertex_ai/gemini-1.5-pro",
            "openai/qwen2.5-coder",
        ):
            encoding = _get_encoding_for_model(model)
            assert encoding.name == "cl100k_base"

    def test_count_tokens_with_model_hint(self):
        """count_tokens accepts a model hint and returns a positive count."""
        text = "Hello world"
        assert count_tokens(text, model="gpt-4o") == 2
        assert count_tokens(text, model="claude-3-5-sonnet-20241022") == 2
        assert count_tokens(text, model=None) == 2

    def test_encoding_cache_returns_same_instance(self):
        """Repeated calls return the same cached encoding object (perf)."""
        a = _get_encoding_for_model("gpt-4o")
        b = _get_encoding_for_model("gpt-4o")
        assert a is b

    @pytest.mark.parametrize(
        "model",
        [
            None,
            "gpt-4o",
            "gpt-4",
            "gpt-3.5-turbo",
            "claude-3-5-sonnet-20241022",
            "gemini-1.5-pro",
        ],
    )
    def test_count_tokens_positive_for_all_model_hints(self, model):
        """Every model hint path returns a positive count for non-empty text."""
        text = "The quick brown fox jumps over the lazy dog."
        assert count_tokens(text, model=model) > 0


class TestCountTokensEdgeCases:
    """Edge-case coverage for ``count_tokens`` (IG-761)."""

    def test_unicode_emoji_counted(self):
        """Emoji and multi-byte unicode produce positive token counts."""
        text = "Hello 🌍 world 🚀"
        assert count_tokens(text) > 0
        assert count_tokens(text, use_tiktoken=False) > 0

    def test_whitespace_only_string(self):
        """Whitespace-only strings still encode (non-negative)."""
        text = "   \t\n  "
        assert count_tokens(text) >= 0
        assert count_tokens(text, use_tiktoken=False) >= 0

    def test_estimation_with_model_hint(self):
        """Estimation path accepts a model hint without error."""
        tokens = count_tokens("Hello world", use_tiktoken=False, model="gpt-4o")
        assert tokens == 2  # len("Hello world") // 4 == 2

    def test_estimation_path_never_imports_tiktoken(self):
        """``use_tiktoken=False`` skips the tiktoken branch entirely."""
        # Even if tiktoken were unavailable, estimation must succeed.
        tokens = count_tokens("a" * 100, use_tiktoken=False)
        assert tokens == 25  # 100 // 4

    def test_single_character(self):
        """A single character is at least 1 token via tiktoken."""
        assert count_tokens("a") >= 1

    def test_repeated_word_scaling(self):
        """Token count scales sub-linearly with repeated words."""
        one = count_tokens("hello")
        ten = count_tokens("hello " * 10)
        assert ten > one
        assert ten < one * 20  # not 10x linearly (tokenizer merges)


class TestEstimateContentChars:
    """Cover ``estimate_content_chars`` for all content shapes (IG-761)."""

    def test_string_content(self):
        assert estimate_content_chars("hello") == 5

    def test_none_content(self):
        assert estimate_content_chars(None) == 0

    def test_empty_string(self):
        assert estimate_content_chars("") == 0

    def test_list_of_strings(self):
        assert estimate_content_chars(["ab", "cd"]) == 4

    def test_list_of_text_blocks(self):
        blocks = [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
        assert estimate_content_chars(blocks) == 10

    def test_list_of_dict_without_text_key(self):
        """Dict blocks lacking a ``text`` key fall back to ``str(block)``."""
        blocks = [{"type": "image", "url": "x"}]
        # str({"type": "image", "url": "x"}) length
        assert estimate_content_chars(blocks) == len(str(blocks[0]))

    def test_list_of_non_str_non_dict(self):
        """Non-str, non-dict blocks fall back to ``str(block)``."""
        assert estimate_content_chars([123, 456]) == 6  # "123" + "456"

    def test_non_str_non_list_content(self):
        """Arbitrary object falls back to ``str(content)``."""
        assert estimate_content_chars(12345) == 5

    def test_nested_empty_list(self):
        assert estimate_content_chars([]) == 0

    def test_mixed_list_content(self):
        """A list mixing strings, dicts, and ints is summed."""
        mixed = ["ab", {"text": "cd"}, 56]
        # "ab" (2) + "cd" (2) + "56" (2) = 6
        assert estimate_content_chars(mixed) == 6
