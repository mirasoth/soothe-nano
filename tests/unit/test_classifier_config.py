"""Tests for the classifier configuration.

A classifier backend is a regular `providers` entry distinguished by
`provider_type: typesafe` — the local gateway and hosted Jev are two entries of
one protocol. Decision parameters live in the shared `classifier` block so nano
internals and host consumers calibrate once.
"""

from __future__ import annotations

import pytest

from soothe_nano.config import (
    ClassifierConfig,
    ModelProviderConfig,
    SootheConfig,
)

langchain_typesafe = pytest.importorskip("langchain_typesafe")
ChoiceAnswer = langchain_typesafe.ChoiceAnswer

# ---------------------------------------------------------------------------
# Provider list: `typesafe` marks a classifier backend
# ---------------------------------------------------------------------------


def test_typesafe_marks_a_classifier_backend() -> None:
    local = ModelProviderConfig(
        name="local-nanojev",
        provider_type="typesafe",
        api_base_url="http://127.0.0.1:8767",
        api_key="local-nanojev",
    )
    assert local.provider_type == "typesafe"


def test_local_and_hosted_are_two_entries_of_one_protocol() -> None:
    """Local gateway and hosted Jev are two entries of the same type."""
    local = ModelProviderConfig(name="local-nanojev", provider_type="typesafe")
    hosted = ModelProviderConfig(name="hosted-jev", provider_type="typesafe")
    assert local.provider_type == hosted.provider_type == "typesafe"


def test_non_typesafe_entries_are_not_classifiers() -> None:
    """A chat provider (`openai`) is never returned as a classifier backend."""
    cfg = SootheConfig(
        providers=[ModelProviderConfig(name="openai", provider_type="openai", api_key="k")],
    )
    assert cfg.find_classifier_provider("openai") is None


def test_classifier_timeout_and_batch_bounds() -> None:
    with pytest.raises(ValueError):
        ModelProviderConfig(name="x", provider_type="typesafe", timeout_seconds=0)
    with pytest.raises(ValueError):
        ModelProviderConfig(name="x", provider_type="typesafe", max_states_per_request=64)


# ---------------------------------------------------------------------------
# Decision parameters
# ---------------------------------------------------------------------------


def test_defaults_are_local() -> None:
    cfg = ClassifierConfig()
    assert cfg.enabled is False
    assert cfg.provider == "local-nanojev"
    assert cfg.strict is False
    assert cfg.min_confidence == 0.6
    assert cfg.min_margin == 0.15
    assert cfg.suppress_min_confidence == 0.9


def test_suppression_bar_sits_above_the_trust_floor() -> None:
    """Suppressing work is riskier than doing it, so its bar is higher."""
    cfg = ClassifierConfig()
    assert cfg.suppress_min_confidence > cfg.min_confidence


def test_suppression_bar_is_a_probability() -> None:
    with pytest.raises(ValueError):
        ClassifierConfig(suppress_min_confidence=1.5)
    with pytest.raises(ValueError):
        ClassifierConfig(suppress_min_confidence=-0.1)


class TestTrustGate:
    cfg = ClassifierConfig(min_confidence=0.8)

    def test_high_confidence_trusted(self) -> None:
        assert self.cfg.trusted(0.95) is True

    def test_low_confidence_untrusted(self) -> None:
        """Out-of-distribution input returns a diffuse distribution; the
        verdict must not drive a decision regardless of the label."""
        assert self.cfg.trusted(0.37) is False

    def test_absent_confidence_is_not_penalised(self) -> None:
        """Missing confidence is not evidence of drift."""
        assert self.cfg.trusted(None) is True


class TestMarginGate:
    cfg = ClassifierConfig(min_margin=0.15)

    def test_clear_leader_is_decisive(self) -> None:
        assert self.cfg.decisive({"allow": 0.9, "escalate": 0.08, "reject": 0.02}) is True

    def test_near_tie_is_not_decisive(self) -> None:
        """A near-tie means the endpoint cannot separate the options."""
        assert self.cfg.decisive({"allow": 0.45, "reject": 0.40, "escalate": 0.15}) is False

    def test_missing_distribution_is_decisive(self) -> None:
        assert self.cfg.decisive(None) is True
        assert self.cfg.decisive({}) is True


def test_choice_carries_confidence_where_noul_does_not() -> None:
    """Regression guard for the primitive choice: binary `Noul` answers expose
    only a probability, so distribution-shift gating requires `Choice`."""
    from langchain_typesafe import Noul, NoulAnswer

    assert "confidence" not in NoulAnswer.model_fields
    assert "confidence" not in Noul.model_fields
    assert "confidence" in ChoiceAnswer.model_fields


# ---------------------------------------------------------------------------
# SootheConfig wiring
# ---------------------------------------------------------------------------


def test_default_config_ships_local_provider() -> None:
    cfg = SootheConfig()
    names = [p.name for p in cfg.providers]
    assert "local-nanojev" in names
    local = cfg.find_classifier_provider("local-nanojev")
    assert local is not None
    assert local.api_base_url == "http://127.0.0.1:8767"
    assert local.provider_type == "typesafe"


def test_provider_kwargs_resolve_endpoint_and_limits() -> None:
    cfg = SootheConfig()
    resolved = cfg.classifier_provider_kwargs()
    assert resolved is not None
    provider_type, kwargs = resolved
    assert provider_type == "typesafe"
    assert kwargs["base_url"] == "http://127.0.0.1:8767"
    assert kwargs["api_key"] == "local-nanojev"
    assert kwargs["model"] == "jev-latest"
    assert kwargs["timeout"] == 5.0
    assert kwargs["max_states_per_request"] == 32
    # Decision parameters stay on `classifier`; kwargs only carry transport.
    assert "min_confidence" not in kwargs


def test_missing_provider_returns_none() -> None:
    """Callers treat None as 'classification unavailable' and fall back."""
    cfg = SootheConfig()
    assert cfg.classifier_provider_kwargs("does-not-exist") is None


def test_provider_kwargs_apply_defaults_when_omitted() -> None:
    """A bare typesafe entry without model/timeout/batch gets shared defaults."""
    cfg = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="bare", provider_type="typesafe", api_base_url="http://127.0.0.1:9999"
            ),
        ],
        classifier=ClassifierConfig(provider="bare"),
    )
    resolved = cfg.classifier_provider_kwargs()
    assert resolved is not None
    assert resolved[1]["model"] == "jev-latest"
    assert resolved[1]["timeout"] == 5.0
    assert resolved[1]["max_states_per_request"] == 32


def test_switching_deployment_changes_only_the_reference() -> None:
    """Local ↔ hosted is a config change: add an entry, point at it."""
    cfg = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="local-nanojev",
                provider_type="typesafe",
                api_base_url="http://127.0.0.1:8767",
            ),
            ModelProviderConfig(
                name="hosted-jev",
                provider_type="typesafe",
                api_base_url="https://api.typesafe.dev",
                api_key="key",
            ),
        ],
        classifier=ClassifierConfig(enabled=True, provider="hosted-jev"),
    )
    resolved = cfg.classifier_provider_kwargs()
    assert resolved is not None
    assert resolved[1]["base_url"] == "https://api.typesafe.dev"
