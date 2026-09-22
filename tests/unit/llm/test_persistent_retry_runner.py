"""Unit tests for PersistentRetryRunner and LLM call resilience features.

Covers:
- P0: Persistent retry with heartbeat (exponential backoff, total cap, heartbeat callback)
- P1: Foreground/background query-source discrimination
- P2: Model fallback on repeated capacity errors (spec-based and role-based)
- P5: Stale-connection detection (ECONNRESET/EPIPE/ConnectionResetError)
- Config field validation for new LLMRateLimitConfig fields
- Event emission via stream_writer (ModelFallbackEvent, LLMPersistentRetryEvent)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from soothe_deepagents.middleware.llm_rate_limit import LLMRateLimitRegistry

from soothe_nano.config.models import LLMRateLimitConfig, QuerySource
from soothe_nano.llm.invoke_policy import (
    PersistentRetryRunner,
    _calc_persistent_backoff,
    _is_capacity_error,
    _is_persistent_retriable,
    _is_stale_connection_error,
    _sleep_with_heartbeat,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_llm_rate_limit_registry() -> None:
    """Reset the process-wide LLM rate-limit registry between tests."""
    LLMRateLimitRegistry.reset_for_tests()


@pytest.fixture
def mock_request() -> ModelRequest:
    """Create a minimal ModelRequest with a mock model."""
    return ModelRequest(
        model=MagicMock(name="primary_model"),
        messages=[],
    )


@pytest.fixture
def mock_handler_ok() -> AsyncMock:
    """Handler that returns a successful response."""
    return AsyncMock(return_value=ModelResponse(result=[AIMessage(content="ok")]))


def _make_capacity_error() -> Exception:
    """Create a mock 529/capacity error."""
    return Exception("service overloaded — 529")


def _make_rate_limit_error() -> Exception:
    """Create a mock 429 rate-limit error."""
    return Exception("rate limit exceeded — 429")


def _make_stale_connection_error() -> Exception:
    """Create a mock ECONNRESET/stale-connection error.

    Uses BrokenPipeError (no text) so the upstream ``_is_transient_connection_error``
    does not intercept it for internal retry; it is still detected by
    ``_is_stale_connection_error`` via the type name.
    """
    return BrokenPipeError()


def _make_non_retriable_error() -> Exception:
    """Create a mock non-retriable error."""
    return ValueError("invalid request")


def _persistent_config(**overrides: object) -> LLMRateLimitConfig:
    """Build an LLMRateLimitConfig with persistent retry enabled.

    Uses minimum-allowed config values. Tests that need fast retry timing
    patch ``_sleep_with_heartbeat`` to avoid real sleeps.
    """
    defaults: dict[str, object] = {
        "persistent_retry_enabled": True,
        "persistent_retry_max_backoff_seconds": 1.0,
        "persistent_retry_total_cap_seconds": 60.0,
        "rate_limit_backoff_base": 1.0,
        "rate_limit_backoff_max": 10.0,
        "max_rate_limit_retries": 1,
        "retry_on_rate_limit": True,
    }
    defaults.update(overrides)
    return LLMRateLimitConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Config field tests
# ---------------------------------------------------------------------------


class TestQuerySourceEnum:
    """QuerySource StrEnum has the expected members."""

    def test_members(self) -> None:
        """All five query-source members exist with correct values."""
        assert QuerySource.main_loop == "main_loop"
        assert QuerySource.compact == "compact"
        assert QuerySource.summary == "summary"
        assert QuerySource.clarification == "clarification"
        assert QuerySource.subagent == "subagent"

    def test_from_string(self) -> None:
        """QuerySource can be constructed from a string."""
        assert QuerySource("main_loop") is QuerySource.main_loop


class TestLLMRateLimitConfigFields:
    """New config fields on LLMRateLimitConfig."""

    def test_defaults(self) -> None:
        """New fields have correct defaults."""
        cfg = LLMRateLimitConfig()
        assert cfg.persistent_retry_enabled is False
        assert cfg.persistent_retry_max_backoff_seconds == 300.0
        assert cfg.persistent_retry_total_cap_seconds == 21600.0
        assert cfg.query_source_discrimination_enabled is False
        assert cfg.fallback_model is None
        assert cfg.fallback_model_role == "fast"
        assert cfg.fallback_model_threshold == 3
        assert cfg.stale_connection_recovery_enabled is False

    def test_persistent_retry_max_backoff_capped_at_300(self) -> None:
        """persistent_retry_max_backoff_seconds cannot exceed 300."""
        with pytest.raises(ValueError):
            LLMRateLimitConfig(persistent_retry_max_backoff_seconds=301.0)

    def test_persistent_retry_total_cap_capped_at_21600(self) -> None:
        """persistent_retry_total_cap_seconds cannot exceed 21600."""
        with pytest.raises(ValueError):
            LLMRateLimitConfig(persistent_retry_total_cap_seconds=21601.0)

    def test_fallback_model_threshold_min_1(self) -> None:
        """fallback_model_threshold minimum is 1."""
        with pytest.raises(ValueError):
            LLMRateLimitConfig(fallback_model_threshold=0)

    def test_custom_values(self) -> None:
        """Custom values are accepted within bounds."""
        cfg = LLMRateLimitConfig(
            persistent_retry_enabled=True,
            persistent_retry_max_backoff_seconds=60.0,
            persistent_retry_total_cap_seconds=3600.0,
            query_source_discrimination_enabled=True,
            fallback_model="openai:gpt-4o-mini",
            fallback_model_role="think",
            fallback_model_threshold=5,
            stale_connection_recovery_enabled=True,
        )
        assert cfg.persistent_retry_enabled is True
        assert cfg.persistent_retry_max_backoff_seconds == 60.0
        assert cfg.persistent_retry_total_cap_seconds == 3600.0
        assert cfg.query_source_discrimination_enabled is True
        assert cfg.fallback_model == "openai:gpt-4o-mini"
        assert cfg.fallback_model_role == "think"
        assert cfg.fallback_model_threshold == 5
        assert cfg.stale_connection_recovery_enabled is True

    def test_fallback_model_role_can_be_none(self) -> None:
        """fallback_model_role can be explicitly set to None."""
        cfg = LLMRateLimitConfig(fallback_model_role=None)
        assert cfg.fallback_model_role is None


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestIsCapacityError:
    """_is_capacity_error detects 529/overloaded conditions."""

    def test_status_code_529(self) -> None:
        """Error with response status_code 529 is detected."""
        response = MagicMock(status_code=529)
        exc = Exception("error")
        exc.response = response  # type: ignore[attr-defined]
        assert _is_capacity_error(exc) is True

    def test_overloaded_text(self) -> None:
        """Error with 'overloaded' text is detected."""
        assert _is_capacity_error(Exception("server overloaded")) is True

    def test_529_text(self) -> None:
        """Error with '529' text is detected."""
        assert _is_capacity_error(Exception("HTTP 529")) is True

    def test_service_unavailable_text(self) -> None:
        """Error with 'service unavailable' text is detected."""
        assert _is_capacity_error(Exception("service unavailable")) is True

    def test_non_capacity_error(self) -> None:
        """Non-capacity errors are not detected."""
        assert _is_capacity_error(ValueError("bad request")) is False

    def test_chained_capacity_error(self) -> None:
        """Capacity error in a cause chain is detected."""
        inner = Exception("overloaded")
        outer = Exception("wrapper")
        outer.__cause__ = inner
        assert _is_capacity_error(outer) is True


class TestIsStaleConnectionError:
    """_is_stale_connection_error detects ECONNRESET/EPIPE conditions."""

    def test_connection_reset_error(self) -> None:
        """ConnectionResetError is detected."""
        assert _is_stale_connection_error(ConnectionResetError()) is True

    def test_broken_pipe_error(self) -> None:
        """BrokenPipeError is detected."""
        assert _is_stale_connection_error(BrokenPipeError()) is True

    def test_econnreset_text(self) -> None:
        """Error with 'econnreset' text is detected."""
        assert _is_stale_connection_error(Exception("ECONNRESET")) is True

    def test_epipe_text(self) -> None:
        """Error with 'epipe' text is detected."""
        assert _is_stale_connection_error(Exception("EPIPE")) is True

    def test_connection_reset_text(self) -> None:
        """Error with 'connection reset' text is detected."""
        assert _is_stale_connection_error(Exception("connection reset")) is True

    def test_non_stale_error(self) -> None:
        """Non-stale errors are not detected."""
        assert _is_stale_connection_error(ValueError("bad request")) is False


class TestIsPersistentRetriable:
    """_is_persistent_retriable combines all retriable error checks."""

    def test_rate_limit_error(self) -> None:
        """429 rate-limit errors are retriable."""
        assert _is_persistent_retriable(_make_rate_limit_error()) is True

    def test_capacity_error(self) -> None:
        """529/capacity errors are retriable."""
        assert _is_persistent_retriable(_make_capacity_error()) is True

    def test_stale_connection_error(self) -> None:
        """ECONNRESET/stale-connection errors are retriable."""
        assert _is_persistent_retriable(_make_stale_connection_error()) is True

    def test_non_retriable(self) -> None:
        """Non-retriable errors are not retriable."""
        assert _is_persistent_retriable(_make_non_retriable_error()) is False


class TestCalcPersistentBackoff:
    """_calc_persistent_backoff computes exponential backoff with cap."""

    def test_first_attempt(self) -> None:
        """Attempt 0 returns base."""
        assert _calc_persistent_backoff(0, base=2.0, max_backoff=300.0) == 2.0

    def test_exponential(self) -> None:
        """Backoff grows exponentially."""
        assert _calc_persistent_backoff(1, base=2.0, max_backoff=300.0) == 4.0
        assert _calc_persistent_backoff(2, base=2.0, max_backoff=300.0) == 8.0
        assert _calc_persistent_backoff(3, base=2.0, max_backoff=300.0) == 16.0

    def test_capped(self) -> None:
        """Backoff is capped at max_backoff."""
        assert _calc_persistent_backoff(20, base=2.0, max_backoff=60.0) == 60.0


class TestSleepWithHeartbeat:
    """_sleep_with_heartbeat yields heartbeats during sleep."""

    @pytest.mark.asyncio
    async def test_heartbeat_called(self) -> None:
        """Heartbeat callback is invoked during sleep when delay exceeds interval."""
        calls: list[None] = []

        def _cb() -> None:
            calls.append(None)

        await _sleep_with_heartbeat(0.03, heartbeat_callback=_cb, heartbeat_interval=0.01)
        assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_no_heartbeat_when_delay_zero(self) -> None:
        """No heartbeat when delay is zero or negative."""
        calls: list[None] = []

        def _cb() -> None:
            calls.append(None)

        await _sleep_with_heartbeat(0.0, heartbeat_callback=_cb)
        assert len(calls) == 0

    @pytest.mark.asyncio
    async def test_no_heartbeat_when_no_callback(self) -> None:
        """No error when heartbeat_callback is None."""
        await _sleep_with_heartbeat(0.01, heartbeat_callback=None, heartbeat_interval=0.005)


# ---------------------------------------------------------------------------
# PersistentRetryRunner tests — P0 persistent retry with heartbeat
# ---------------------------------------------------------------------------


class TestPersistentRetryRunnerP0:
    """P0: Persistent retry with heartbeat."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(
        self, mock_request: ModelRequest, mock_handler_ok: AsyncMock
    ) -> None:
        """When the handler succeeds, no retry is needed."""
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg)
        result = await runner.awrap_model_call(mock_request, mock_handler_ok)
        assert result is mock_handler_ok.return_value

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_then_succeeds(self, mock_request: ModelRequest) -> None:
        """Retries on 429 and eventually succeeds."""
        handler = AsyncMock(
            side_effect=[
                _make_rate_limit_error(),
                _make_rate_limit_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_capacity_error_then_succeeds(
        self, mock_request: ModelRequest
    ) -> None:
        """Retries on 529/capacity error and eventually succeeds."""
        handler = AsyncMock(
            side_effect=[_make_capacity_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_stale_connection_then_succeeds(
        self, mock_request: ModelRequest
    ) -> None:
        """Retries on ECONNRESET and eventually succeeds."""
        handler = AsyncMock(
            side_effect=[
                _make_stale_connection_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 2

    @pytest.mark.asyncio
    async def test_non_retriable_error_raises_immediately(self, mock_request: ModelRequest) -> None:
        """Non-retriable errors propagate without retry."""
        handler = AsyncMock(side_effect=[_make_non_retriable_error()])
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg)
        with pytest.raises(ValueError, match="invalid request"):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 1

    @pytest.mark.asyncio
    async def test_total_cap_reached_raises_timeout(self, mock_request: ModelRequest) -> None:
        """When total cap is reached, raises TimeoutError."""
        handler = AsyncMock(side_effect=[_make_rate_limit_error()])
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg)
        with (
            patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock),
            patch("soothe_nano.llm.invoke_policy.time.monotonic", side_effect=[0.0, 100.0]),
        ):
            with pytest.raises(TimeoutError, match="total cap"):
                await runner.awrap_model_call(mock_request, handler)

    @pytest.mark.asyncio
    async def test_heartbeat_callback_invoked_during_backoff(
        self, mock_request: ModelRequest
    ) -> None:
        """Heartbeat callback is invoked during backoff sleeps."""
        heartbeat_calls: list[None] = []

        def _hb() -> None:
            heartbeat_calls.append(None)

        # Two 429 errors exhaust the internal policy (max_rate_limit_retries=1),
        # then the PersistentRetryRunner retries and the third call succeeds.
        handler = AsyncMock(
            side_effect=[
                _make_rate_limit_error(),
                _make_rate_limit_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, heartbeat_callback=_hb)

        async def _capturing_sleep(
            delay: float, *, heartbeat_callback=None, heartbeat_interval=15.0
        ) -> None:
            if heartbeat_callback is not None:
                heartbeat_callback()

        with (
            patch(
                "soothe_nano.llm.invoke_policy._sleep_with_heartbeat", side_effect=_capturing_sleep
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await runner.awrap_model_call(mock_request, handler)
        assert len(heartbeat_calls) >= 1


# ---------------------------------------------------------------------------
# PersistentRetryRunner tests — P1 query-source discrimination
# ---------------------------------------------------------------------------


class TestPersistentRetryRunnerP1:
    """P1: Foreground/background query-source discrimination."""

    @pytest.mark.asyncio
    async def test_background_bails_on_capacity(self, mock_request: ModelRequest) -> None:
        """Background source (compact) bails immediately on 529."""
        mock_request.model_settings = {"query_source": QuerySource.compact}
        handler = AsyncMock(side_effect=[_make_capacity_error()])
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, query_source_discrimination=True)
        with pytest.raises(Exception, match="overloaded"):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 1

    @pytest.mark.asyncio
    async def test_background_bails_on_529_summary(self, mock_request: ModelRequest) -> None:
        """Background source (summary) bails immediately on 529."""
        mock_request.model_settings = {"query_source": QuerySource.summary}
        handler = AsyncMock(side_effect=[_make_capacity_error()])
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, query_source_discrimination=True)
        with pytest.raises(Exception, match="overloaded"):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 1

    @pytest.mark.asyncio
    async def test_foreground_retries_on_capacity(self, mock_request: ModelRequest) -> None:
        """Foreground source (main_loop) retries on 529 per P0."""
        mock_request.model_settings = {"query_source": QuerySource.main_loop}
        handler = AsyncMock(
            side_effect=[_make_capacity_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, query_source_discrimination=True)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 2

    @pytest.mark.asyncio
    async def test_foreground_clarification_retries(self, mock_request: ModelRequest) -> None:
        """Foreground source (clarification) retries on 529."""
        mock_request.model_settings = {"query_source": QuerySource.clarification}
        handler = AsyncMock(
            side_effect=[_make_capacity_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, query_source_discrimination=True)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 2

    @pytest.mark.asyncio
    async def test_query_source_from_string(self, mock_request: ModelRequest) -> None:
        """QuerySource can be passed as a string in model_settings."""
        mock_request.model_settings = {"query_source": "compact"}
        handler = AsyncMock(side_effect=[_make_capacity_error()])
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, query_source_discrimination=True)
        with pytest.raises(Exception, match="overloaded"):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 1

    @pytest.mark.asyncio
    async def test_no_discrimination_retries_background(self, mock_request: ModelRequest) -> None:
        """When discrimination is off, background sources still retry."""
        mock_request.model_settings = {"query_source": QuerySource.compact}
        handler = AsyncMock(
            side_effect=[_make_capacity_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, query_source_discrimination=False)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 2

    @pytest.mark.asyncio
    async def test_background_retries_on_rate_limit_not_capacity(
        self, mock_request: ModelRequest
    ) -> None:
        """Background source retries on 429 (not a capacity error) per P0."""
        mock_request.model_settings = {"query_source": QuerySource.compact}
        handler = AsyncMock(
            side_effect=[_make_rate_limit_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, query_source_discrimination=True)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 2


# ---------------------------------------------------------------------------
# PersistentRetryRunner tests — P2 model fallback
# ---------------------------------------------------------------------------


class TestPersistentRetryRunnerP2:
    """P2: Model fallback on repeated capacity errors."""

    @pytest.mark.asyncio
    async def test_fallback_after_threshold(self, mock_request: ModelRequest) -> None:
        """After threshold capacity errors, switches to fallback model."""
        mock_request.model_settings = {"query_source": QuerySource.main_loop}
        fallback_model = MagicMock(name="fallback_model")
        handler = AsyncMock(
            side_effect=[
                _make_capacity_error(),
                _make_capacity_error(),
                _make_capacity_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model="openai:gpt-4o-mini",
            fallback_model_threshold=3,
        )

        def _fallback_and_mark(request):
            runner._fallback_active = True
            return fallback_model

        with (
            patch.object(runner, "_maybe_get_fallback_model", side_effect=_fallback_and_mark),
            patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock),
        ):
            await runner.awrap_model_call(mock_request, handler)
        assert handler.call_count == 4
        assert runner._fallback_active is True

    @pytest.mark.asyncio
    async def test_no_fallback_when_not_configured(self, mock_request: ModelRequest) -> None:
        """When fallback_model is None and fallback_model_role is None, no fallback occurs."""
        mock_request.model_settings = {"query_source": QuerySource.main_loop}
        handler = AsyncMock(
            side_effect=[_make_capacity_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model=None,
            fallback_model_role=None,
            fallback_model_threshold=3,
        )
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert runner._fallback_active is False

    @pytest.mark.asyncio
    async def test_fallback_emits_event(self, mock_request: ModelRequest) -> None:
        """model_fallback_triggered event is emitted on fallback."""
        mock_request.model_settings = {"query_source": QuerySource.main_loop}
        fallback_model = MagicMock(name="fallback_model")
        handler = AsyncMock(
            side_effect=[
                _make_capacity_error(),
                _make_capacity_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model="openai:gpt-4o-mini",
            fallback_model_role=None,
            fallback_model_threshold=2,
        )
        with (
            patch.object(runner, "_maybe_get_fallback_model", return_value=fallback_model),
            patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock),
            patch("soothe_nano.llm.invoke_policy._emit_model_fallback_event") as mock_emit,
        ):
            await runner.awrap_model_call(mock_request, handler)
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args
            assert call_kwargs.kwargs["to_model"] == "openai:gpt-4o-mini"
            assert call_kwargs.kwargs["to_role"] is None
            assert call_kwargs.kwargs["consecutive_capacity_errors"] == 2
            assert call_kwargs.kwargs["request"] is not None

    @pytest.mark.asyncio
    async def test_non_capacity_error_resets_counter(self, mock_request: ModelRequest) -> None:
        """Non-capacity retriable error resets the capacity error counter."""
        mock_request.model_settings = {"query_source": QuerySource.main_loop}
        handler = AsyncMock(
            side_effect=[
                _make_capacity_error(),
                _make_rate_limit_error(),
                _make_capacity_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model="openai:gpt-4o-mini",
            fallback_model_threshold=3,
        )
        with (
            patch.object(runner, "_maybe_get_fallback_model", return_value=MagicMock()),
            patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock),
        ):
            await runner.awrap_model_call(mock_request, handler)
        assert runner._consecutive_capacity_errors == 0


# ---------------------------------------------------------------------------
# PersistentRetryRunner tests — P5 stale-connection detection
# ---------------------------------------------------------------------------


class TestPersistentRetryRunnerP5:
    """P5: Stale-connection detection."""

    @pytest.mark.asyncio
    async def test_stale_connection_disables_keepalive(self) -> None:
        """On ECONNRESET, keep-alive is disabled on the model for retry."""
        model = MagicMock(name="model")
        model.model_kwargs = {}
        request = ModelRequest(model=model, messages=[])
        handler = AsyncMock(
            side_effect=[
                _make_stale_connection_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, stale_connection_recovery=True)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(request, handler)
        assert model.model_kwargs.get("extra_body", {}).get("keep_alive") is False

    @pytest.mark.asyncio
    async def test_stale_connection_recovery_disabled(self) -> None:
        """When stale_connection_recovery is False, keep-alive is not touched."""
        model = MagicMock(name="model")
        model.model_kwargs = {}
        request = ModelRequest(model=model, messages=[])
        handler = AsyncMock(
            side_effect=[
                _make_stale_connection_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, stale_connection_recovery=False)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(request, handler)
        assert "extra_body" not in model.model_kwargs

    @pytest.mark.asyncio
    async def test_non_stale_error_does_not_disable_keepalive(self) -> None:
        """On non-stale retriable error, keep-alive is not touched."""
        model = MagicMock(name="model")
        model.model_kwargs = {}
        request = ModelRequest(model=model, messages=[])
        handler = AsyncMock(
            side_effect=[_make_rate_limit_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(config=cfg, stale_connection_recovery=True)
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(request, handler)
        assert "extra_body" not in model.model_kwargs


# ---------------------------------------------------------------------------
# Thread-id extraction tests
# ---------------------------------------------------------------------------


class TestPersistentRetryRunnerThreadId:
    """Thread-id extraction from ModelRequest."""

    def test_thread_id_from_runtime_config(self) -> None:
        """Thread ID is extracted from runtime.config.configurable.thread_id."""
        request = MagicMock()
        request.runtime.config = {"configurable": {"thread_id": "my-thread"}}
        assert PersistentRetryRunner._thread_id_from_request(request) == "my-thread"

    def test_thread_id_default(self) -> None:
        """Defaults to 'default' when no thread_id is present."""
        request = MagicMock()
        request.runtime.config = {}
        assert PersistentRetryRunner._thread_id_from_request(request) == "default"


# ---------------------------------------------------------------------------
# Role-based fallback tests (GZD-01)
# ---------------------------------------------------------------------------


class TestRoleBasedFallback:
    """Role-based model fallback via fallback_model_role."""

    def _make_request_with_config(
        self, soothe_config: Any, *, stream_writer: Any = None
    ) -> ModelRequest:
        """Create a ModelRequest with a mock runtime carrying soothe_config."""
        runtime = MagicMock()
        runtime.config = {"configurable": {"soothe_config": soothe_config}}
        runtime.stream_writer = stream_writer
        return ModelRequest(
            model=MagicMock(name="primary_model"),
            messages=[],
            runtime=runtime,
        )

    @pytest.mark.asyncio
    async def test_role_based_fallback_resolves_via_create_chat_model(self) -> None:
        """When fallback_model_role is set, model is created via create_chat_model(role)."""
        fallback_model = MagicMock(name="fast_model")
        soothe_config = MagicMock()
        soothe_config.create_chat_model = MagicMock(return_value=fallback_model)
        request = self._make_request_with_config(soothe_config)
        request.model_settings = {"query_source": QuerySource.main_loop}

        handler = AsyncMock(
            side_effect=[
                _make_capacity_error(),
                _make_capacity_error(),
                _make_capacity_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model_role="fast",
            fallback_model_threshold=3,
        )
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(request, handler)
        assert runner._fallback_active is True
        soothe_config.create_chat_model.assert_called_once_with("fast")

    @pytest.mark.asyncio
    async def test_role_takes_precedence_over_spec(self) -> None:
        """When both role and spec are set, role is used first."""
        fallback_model = MagicMock(name="fast_model")
        soothe_config = MagicMock()
        soothe_config.create_chat_model = MagicMock(return_value=fallback_model)
        soothe_config.create_chat_model_for_spec = MagicMock()
        request = self._make_request_with_config(soothe_config)
        request.model_settings = {"query_source": QuerySource.main_loop}

        handler = AsyncMock(
            side_effect=[
                _make_capacity_error(),
                _make_capacity_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model="openai:gpt-4o-mini",
            fallback_model_role="fast",
            fallback_model_threshold=2,
        )
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(request, handler)
        assert runner._fallback_active is True
        soothe_config.create_chat_model.assert_called_once_with("fast")
        soothe_config.create_chat_model_for_spec.assert_not_called()

    @pytest.mark.asyncio
    async def test_role_fallback_emits_event_with_role(self) -> None:
        """Role-based fallback emits event with to_role set."""
        fallback_model = MagicMock(name="fast_model")
        soothe_config = MagicMock()
        soothe_config.create_chat_model = MagicMock(return_value=fallback_model)
        request = self._make_request_with_config(soothe_config)
        request.model_settings = {"query_source": QuerySource.main_loop}

        handler = AsyncMock(
            side_effect=[
                _make_capacity_error(),
                _make_capacity_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model_role="fast",
            fallback_model_threshold=2,
        )
        with (
            patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock),
            patch("soothe_nano.llm.invoke_policy._emit_model_fallback_event") as mock_emit,
        ):
            await runner.awrap_model_call(request, handler)
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args
            assert call_kwargs.kwargs["to_role"] == "fast"
            assert "role:fast" in call_kwargs.kwargs["to_model"]

    @pytest.mark.asyncio
    async def test_no_fallback_when_both_role_and_spec_none(
        self, mock_request: ModelRequest
    ) -> None:
        """No fallback when both fallback_model and fallback_model_role are None."""
        mock_request.model_settings = {"query_source": QuerySource.main_loop}
        handler = AsyncMock(
            side_effect=[_make_capacity_error(), ModelResponse(result=[AIMessage(content="ok")])],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model=None,
            fallback_model_role=None,
            fallback_model_threshold=1,
        )
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(mock_request, handler)
        assert runner._fallback_active is False


# ---------------------------------------------------------------------------
# Event emission via stream_writer tests (GZD-01)
# ---------------------------------------------------------------------------


class TestEventEmissionViaStreamWriter:
    """Model fallback and persistent retry events emitted via stream_writer."""

    def _make_request_with_stream(
        self, *, soothe_config: Any = None, stream_writer: Any = None
    ) -> ModelRequest:
        """Create a ModelRequest with a mock runtime carrying stream_writer."""
        runtime = MagicMock()
        configurable = {}
        if soothe_config is not None:
            configurable["soothe_config"] = soothe_config
        runtime.config = {"configurable": configurable} if configurable else {}
        runtime.stream_writer = stream_writer
        return ModelRequest(
            model=MagicMock(name="primary_model"),
            messages=[],
            runtime=runtime,
        )

    @pytest.mark.asyncio
    async def test_model_fallback_event_emitted_to_stream_writer(self) -> None:
        """ModelFallbackEvent is dispatched as a custom stream chunk."""
        fallback_model = MagicMock(name="fallback_model")
        soothe_config = MagicMock()
        soothe_config.create_chat_model = MagicMock(return_value=fallback_model)
        stream_writer = MagicMock()
        request = self._make_request_with_stream(
            soothe_config=soothe_config, stream_writer=stream_writer
        )
        request.model_settings = {"query_source": QuerySource.main_loop}

        # With max_rate_limit_retries=1, each run_llm_call_with_policy call
        # consumes 2 handler calls when both fail. Need 4 capacity errors
        # (2 retry cycles) to reach threshold=2, then success.
        handler = AsyncMock(
            side_effect=[
                _make_capacity_error(),
                _make_capacity_error(),
                _make_capacity_error(),
                _make_capacity_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model_role="fast",
            fallback_model_threshold=2,
        )
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(request, handler)
        # stream_writer should have been called with custom event chunks
        assert stream_writer.call_count >= 1
        # Find the model_fallback event among the stream_writer calls
        fallback_events = [
            call
            for call in stream_writer.call_args_list
            if isinstance(call.args[0], tuple)
            and len(call.args[0]) == 3
            and call.args[0][1] == "custom"
            and isinstance(call.args[0][2], dict)
            and call.args[0][2].get("type") == "soothe.cognition.llm.model_fallback"
        ]
        assert len(fallback_events) == 1
        event_data = fallback_events[0].args[0][2]
        assert event_data["to_role"] == "fast"
        assert event_data["consecutive_capacity_errors"] == 2

    @pytest.mark.asyncio
    async def test_persistent_retry_event_emitted_to_stream_writer(self) -> None:
        """LLMPersistentRetryEvent is dispatched on each retry backoff."""
        stream_writer = MagicMock()
        request = self._make_request_with_stream(stream_writer=stream_writer)
        request.model_settings = {"query_source": QuerySource.main_loop}

        handler = AsyncMock(
            side_effect=[
                _make_rate_limit_error(),
                _make_rate_limit_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model=None,
            fallback_model_role=None,
        )
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            await runner.awrap_model_call(request, handler)
        # Find persistent retry events
        retry_events = [
            call
            for call in stream_writer.call_args_list
            if isinstance(call.args[0], tuple)
            and len(call.args[0]) == 3
            and call.args[0][1] == "custom"
            and isinstance(call.args[0][2], dict)
            and call.args[0][2].get("type") == "soothe.cognition.llm.persistent_retry"
        ]
        assert len(retry_events) == 1
        event_data = retry_events[0].args[0][2]
        assert event_data["attempt"] == 1
        assert event_data["error_type"] == "Exception"

    @pytest.mark.asyncio
    async def test_no_stream_event_when_no_stream_writer(self) -> None:
        """Events are silently skipped when stream_writer is not available."""
        request = self._make_request_with_stream(stream_writer=None)
        request.model_settings = {"query_source": QuerySource.main_loop}

        handler = AsyncMock(
            side_effect=[
                _make_rate_limit_error(),
                _make_rate_limit_error(),
                ModelResponse(result=[AIMessage(content="ok")]),
            ],
        )
        cfg = _persistent_config()
        runner = PersistentRetryRunner(
            config=cfg,
            fallback_model=None,
            fallback_model_role=None,
        )
        with patch("soothe_nano.llm.invoke_policy._sleep_with_heartbeat", new_callable=AsyncMock):
            # Should not raise even without stream_writer
            result = await runner.awrap_model_call(request, handler)
        assert result is not None
