"""Tests for multi-model router profile (parse_model_specs, resolve_model_specs,
MultiModelChatModel failover, LLMFactory multi-spec wrapping)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from soothe_nano.config.models import parse_model_specs
from soothe_nano.config.settings import SootheConfig
from soothe_nano.llm.factory import LLMFactory
from soothe_nano.llm.provider import ChatLitellmModel, MultiModelChatModel
from soothe_nano.llm.registry import ProviderCapabilities

# ---------------------------------------------------------------------------
# parse_model_specs
# ---------------------------------------------------------------------------


class TestParseModelSpecs:
    """Tests for the ``parse_model_specs`` string-parsing helper."""

    def test_single_spec(self) -> None:
        assert parse_model_specs("dashscope:glm-5.2") == ["dashscope:glm-5.2"]

    def test_multi_spec_semicolon_separated(self) -> None:
        result = parse_model_specs("ds1:glm-5.2;ds2:glm-5.2;ds3:glm-5.2")
        assert result == ["ds1:glm-5.2", "ds2:glm-5.2", "ds3:glm-5.2"]

    def test_strips_whitespace(self) -> None:
        result = parse_model_specs("  ds1:glm-5.2 ; ds2:glm-5.2  ")
        assert result == ["ds1:glm-5.2", "ds2:glm-5.2"]

    def test_drops_empty_fragments(self) -> None:
        result = parse_model_specs("ds1:glm-5.2;;ds2:glm-5.2;")
        assert result == ["ds1:glm-5.2", "ds2:glm-5.2"]

    def test_none_returns_empty(self) -> None:
        assert parse_model_specs(None) == []

    def test_empty_string_returns_empty(self) -> None:
        assert parse_model_specs("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert parse_model_specs("   ") == []

    def test_invalid_spec_without_colon_raises(self) -> None:
        with pytest.raises(ValueError, match="must be 'provider:model'"):
            parse_model_specs("invalid-no-colon")


# ---------------------------------------------------------------------------
# SootheConfig.resolve_model_specs / resolve_model
# ---------------------------------------------------------------------------


def _multi_spec_config() -> SootheConfig:
    return SootheConfig(
        router_profiles=[
            {
                "name": "default",
                "router": {
                    "default": "ds1:glm-5.2;ds2:glm-5.2;ds3:glm-5.2",
                    "fast": "dashscope:qwen-flash",
                    "think": "ds1:glm-5.2;ds2:glm-5.2",
                },
            }
        ]
    )


class TestResolveModelSpecs:
    """Tests for ``SootheConfig.resolve_model_specs`` and ``resolve_model``."""

    def test_resolve_model_specs_multi(self) -> None:
        cfg = _multi_spec_config()
        specs = cfg.resolve_model_specs("default")
        assert specs == ["ds1:glm-5.2", "ds2:glm-5.2", "ds3:glm-5.2"]

    def test_resolve_model_specs_single(self) -> None:
        cfg = _multi_spec_config()
        specs = cfg.resolve_model_specs("fast")
        assert specs == ["dashscope:qwen-flash"]

    def test_resolve_model_specs_think_multi(self) -> None:
        cfg = _multi_spec_config()
        specs = cfg.resolve_model_specs("think")
        assert specs == ["ds1:glm-5.2", "ds2:glm-5.2"]

    def test_resolve_model_returns_first_spec_for_multi(self) -> None:
        cfg = _multi_spec_config()
        assert cfg.resolve_model("default") == "ds1:glm-5.2"

    def test_resolve_model_returns_spec_for_single(self) -> None:
        cfg = _multi_spec_config()
        assert cfg.resolve_model("fast") == "dashscope:qwen-flash"

    def test_resolve_model_specs_falls_back_to_default(self) -> None:
        cfg = _multi_spec_config()
        # 'image' is not set — falls back to default (which is multi-spec).
        specs = cfg.resolve_model_specs("image")
        assert specs == ["ds1:glm-5.2", "ds2:glm-5.2", "ds3:glm-5.2"]

    def test_resolve_model_specs_embedding(self) -> None:
        cfg = SootheConfig(
            router_profiles=[
                {
                    "name": "default",
                    "router": {"default": "dashscope:glm-5.2"},
                }
            ],
            embedding_profile=[
                {"model_role": "dashscope:text-embedding-v4", "embedding_dims": 1536}
            ],
        )
        assert cfg.resolve_model_specs("embedding") == ["dashscope:text-embedding-v4"]


# ---------------------------------------------------------------------------
# LLMFactory multi-spec wrapping
# ---------------------------------------------------------------------------


def _make_chat_litellm_model(spec: str) -> ChatLitellmModel:
    """Create a real ``ChatLitellmModel`` for testing (no network calls)."""
    return ChatLitellmModel(
        model=spec,
        api_base=None,
        api_key=None,
        capabilities=ProviderCapabilities(),
        temperature=0.7,
        streaming=True,
        model_kwargs={},
    )


class TestLLMFactoryMultiSpec:
    """Tests for ``LLMFactory.create_chat_model`` with multi-spec roles."""

    @staticmethod
    def _mock_create_from_spec(spec: str, params: dict) -> ChatLitellmModel:
        """Create a real ``ChatLitellmModel`` for a given spec string."""
        return _make_chat_litellm_model(spec)

    def test_multi_spec_returns_multi_model(self) -> None:
        cfg = _multi_spec_config()
        factory = LLMFactory(cfg)
        with patch.object(factory, "_create_from_spec", side_effect=self._mock_create_from_spec):
            model = factory.create_chat_model("default")
        assert isinstance(model, MultiModelChatModel)
        assert len(model.models) == 3

    def test_single_spec_returns_chat_litellm(self) -> None:
        cfg = _multi_spec_config()
        factory = LLMFactory(cfg)
        with patch.object(factory, "_create_from_spec", side_effect=self._mock_create_from_spec):
            model = factory.create_chat_model("fast")
        assert isinstance(model, ChatLitellmModel)
        assert not isinstance(model, MultiModelChatModel)

    def test_multi_spec_cached(self) -> None:
        cfg = _multi_spec_config()
        factory = LLMFactory(cfg)
        with patch.object(factory, "_create_from_spec", side_effect=self._mock_create_from_spec):
            m1 = factory.create_chat_model("default")
            m2 = factory.create_chat_model("default")
        assert m1 is m2

    def test_multi_spec_think_returns_two_models(self) -> None:
        cfg = _multi_spec_config()
        factory = LLMFactory(cfg)
        with patch.object(factory, "_create_from_spec", side_effect=self._mock_create_from_spec):
            model = factory.create_chat_model("think")
        assert isinstance(model, MultiModelChatModel)
        assert len(model.models) == 2


# ---------------------------------------------------------------------------
# MultiModelChatModel failover
# ---------------------------------------------------------------------------


def _make_chat_result(content: str = "hello") -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


class TestMultiModelChatModelFailover:
    """Tests for ``MultiModelChatModel`` random selection and failover."""

    def test_agenerate_succeeds_on_first_model(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(return_value=_make_chat_result("from-m1"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._agenerate = AsyncMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(models=[m1, m2])
        # Patch shuffle to keep order deterministic.
        with patch("soothe_nano.llm.provider.random.shuffle"):
            import asyncio

            result = asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
        assert result.generations[0].message.content == "from-m1"
        # Second model was never called.
        m2._agenerate.assert_not_called()

    def test_agenerate_fails_over_to_second_model(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._agenerate = AsyncMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            import asyncio

            result = asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
        assert result.generations[0].message.content == "from-m2"
        m1._agenerate.assert_called_once()
        m2._agenerate.assert_called_once()

    def test_agenerate_raises_when_all_fail(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._agenerate = AsyncMock(side_effect=RuntimeError("m2 down"))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            import asyncio

            with pytest.raises(RuntimeError, match="all models in pool failed"):
                asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))

    def test_agenerate_tries_all_models_exactly_once(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._agenerate = AsyncMock(side_effect=RuntimeError("m2 down"))

        m3 = _make_chat_litellm_model("ds3:glm-5.2")
        m3._agenerate = AsyncMock(side_effect=RuntimeError("m3 down"))

        wrapper = MultiModelChatModel(models=[m1, m2, m3], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            import asyncio

            with pytest.raises(RuntimeError, match="all models in pool failed"):
                asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))

        m1._agenerate.assert_called_once()
        m2._agenerate.assert_called_once()
        m3._agenerate.assert_called_once()

    def test_generate_sync_succeeds_on_first(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._generate = MagicMock(return_value=_make_chat_result("from-m1"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._generate = MagicMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(models=[m1, m2])
        with patch("soothe_nano.llm.provider.random.shuffle"):
            result = wrapper._generate([HumanMessage(content="hi")])
        assert result.generations[0].message.content == "from-m1"
        m2._generate.assert_not_called()

    def test_generate_sync_fails_over(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._generate = MagicMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._generate = MagicMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(models=[m1, m2], failover_cooldown_s=0)
        with patch("soothe_nano.llm.provider.random.shuffle"):
            result = wrapper._generate([HumanMessage(content="hi")])
        assert result.generations[0].message.content == "from-m2"


class TestMultiModelCircuitBreaker:
    """Tests for the per-model circuit breaker in ``MultiModelChatModel``."""

    def test_circuit_opens_after_threshold_failures(self) -> None:
        """After threshold consecutive failures, the model is skipped."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._agenerate = AsyncMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(
            models=[m1, m2],
            circuit_threshold=3,
            circuit_cooldown_s=60.0,
            failover_cooldown_s=0,
        )
        with patch("soothe_nano.llm.provider.random.shuffle"):
            import asyncio

            # First 2 calls: m1 fails, failover to m2
            for _ in range(2):
                asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
            assert wrapper._circuit._failures["ds1:glm-5.2"] == 2

            # Third call: circuit opens for m1, only m2 is tried
            asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
            assert wrapper._circuit.is_open("ds1:glm-5.2")

        # m1 should have been called 3 times (threshold), now circuit is open
        # Subsequent calls skip m1 entirely
        call_count_before = m1._agenerate.call_count
        with patch("soothe_nano.llm.provider.random.shuffle"):
            asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
        assert m1._agenerate.call_count == call_count_before  # not called

    def test_circuit_resets_on_success(self) -> None:
        """A successful call resets the failure counter."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        results = [_make_chat_result("ok"), _make_chat_result("ok")]
        m1._agenerate = AsyncMock(side_effect=results)

        wrapper = MultiModelChatModel(
            models=[m1],
            circuit_threshold=3,
        )
        with patch("soothe_nano.llm.provider.random.shuffle"):
            import asyncio

            asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
            assert wrapper._circuit._failures.get("ds1:glm-5.2", 0) == 0

    def test_all_circuits_open_falls_back_to_full_pool(self) -> None:
        """When all models have open circuits, fall back to the full pool."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(return_value=_make_chat_result("from-m1"))

        wrapper = MultiModelChatModel(
            models=[m1],
            circuit_threshold=1,
            circuit_cooldown_s=60.0,
        )
        # Force circuit open
        wrapper._circuit.record_failure("ds1:glm-5.2")
        assert wrapper._circuit.is_open("ds1:glm-5.2")

        with patch("soothe_nano.llm.provider.random.shuffle"):
            import asyncio

            result = asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
        # Despite open circuit, fallback allowed the call
        assert result.generations[0].message.content == "from-m1"


# ---------------------------------------------------------------------------
# MultiModelChatModel inter-endpoint failover cooldown
# ---------------------------------------------------------------------------


class TestMultiModelFailoverCooldown:
    """Tests for the inter-endpoint ``failover_cooldown_s`` backoff."""

    def test_sync_cooldown_applied_once_between_failovers(self) -> None:
        """Sync ``_generate`` waits once (3s) between two endpoint attempts."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._generate = MagicMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._generate = MagicMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(models=[m1, m2])
        with (
            patch("soothe_nano.llm.provider.random.shuffle"),
            patch("soothe_nano.llm.provider._failover_backoff") as mock_backoff,
        ):
            result = wrapper._generate([HumanMessage(content="hi")])
        assert result.generations[0].message.content == "from-m2"
        mock_backoff.assert_called_once_with(3.0)

    def test_async_cooldown_applied_once_between_failovers(self) -> None:
        """Async ``_agenerate`` waits once (3s) between two endpoint attempts."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._agenerate = AsyncMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(models=[m1, m2])
        with (
            patch("soothe_nano.llm.provider.random.shuffle"),
            patch("soothe_nano.llm.provider._afailover_backoff") as mock_backoff,
        ):
            import asyncio

            result = asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
        assert result.generations[0].message.content == "from-m2"
        mock_backoff.assert_awaited_once_with(3.0)

    def test_no_cooldown_when_first_model_succeeds(self) -> None:
        """No backoff when the first endpoint succeeds immediately."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._generate = MagicMock(return_value=_make_chat_result("from-m1"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._generate = MagicMock(return_value=_make_chat_result("from-m2"))

        wrapper = MultiModelChatModel(models=[m1, m2])
        with (
            patch("soothe_nano.llm.provider.random.shuffle"),
            patch("soothe_nano.llm.provider._failover_backoff") as mock_backoff,
        ):
            result = wrapper._generate([HumanMessage(content="hi")])
        assert result.generations[0].message.content == "from-m1"
        mock_backoff.assert_not_called()

    def test_no_cooldown_after_last_failure(self) -> None:
        """In an all-fail pool, backoff fires ``len(pool) - 1`` times."""
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m1._agenerate = AsyncMock(side_effect=RuntimeError("m1 down"))

        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        m2._agenerate = AsyncMock(side_effect=RuntimeError("m2 down"))

        m3 = _make_chat_litellm_model("ds3:glm-5.2")
        m3._agenerate = AsyncMock(side_effect=RuntimeError("m3 down"))

        wrapper = MultiModelChatModel(models=[m1, m2, m3])
        with (
            patch("soothe_nano.llm.provider.random.shuffle"),
            patch("soothe_nano.llm.provider._afailover_backoff") as mock_backoff,
        ):
            import asyncio

            with pytest.raises(RuntimeError, match="all models in pool failed"):
                asyncio.run(wrapper._agenerate([HumanMessage(content="hi")]))
        # 3 models → 2 inter-attempt gaps (never after the last failure).
        assert mock_backoff.await_count == 2
        mock_backoff.assert_awaited_with(3.0)


# ---------------------------------------------------------------------------
# MultiModelChatModel.bind_tools
# ---------------------------------------------------------------------------


class TestMultiModelBindTools:
    """Tests for ``MultiModelChatModel.bind_tools`` propagation."""

    def test_bind_tools_propagates_to_all_models(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m2 = _make_chat_litellm_model("ds2:glm-5.2")

        wrapper = MultiModelChatModel(models=[m1, m2])
        bound = wrapper.bind_tools([{"type": "function", "function": {"name": "foo"}}])

        assert isinstance(bound, MultiModelChatModel)
        assert len(bound.models) == 2
        # Each underlying model should have bound_tools set.
        for m in bound.models:
            assert len(m.bound_tools) > 0


# ---------------------------------------------------------------------------
# MultiModelChatModel identity
# ---------------------------------------------------------------------------


class TestMultiModelIdentity:
    """Tests for ``MultiModelChatModel`` identity properties."""

    def test_llm_type(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        wrapper = MultiModelChatModel(models=[m1])
        assert wrapper._llm_type == "litellm-multi"

    def test_identifying_params_includes_pool_size(self) -> None:
        m1 = _make_chat_litellm_model("ds1:glm-5.2")
        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        wrapper = MultiModelChatModel(models=[m1, m2])
        params = wrapper._identifying_params
        assert params["pool_size"] == 2

    def test_capabilities_delegates_to_first_model(self) -> None:
        caps = ProviderCapabilities(supports_json_schema=False, streaming=False)
        m1 = ChatLitellmModel(
            model="ds1:glm-5.2",
            capabilities=caps,
        )
        m2 = _make_chat_litellm_model("ds2:glm-5.2")
        wrapper = MultiModelChatModel(models=[m1, m2])
        assert wrapper.capabilities is caps
