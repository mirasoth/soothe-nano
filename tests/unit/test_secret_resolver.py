"""Direct tests for the SootheConfig.secret_resolver property (nano variant).

Validates the fix for issue #22 problem 1: the property exists, is callable,
and resolves ``${ENV_VAR}`` the same way the config-load-time expander does.
"""

from __future__ import annotations

import pytest

from soothe_nano.config.settings import SootheConfig


def test_secret_resolver_is_callable() -> None:
    """secret_resolver is exposed and callable on a default SootheConfig."""
    config = SootheConfig()
    assert callable(config.secret_resolver)


def test_secret_resolver_expands_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SECRET_RESOLVER_VAR", "resolved-value")
    assert SootheConfig().secret_resolver("${TEST_SECRET_RESOLVER_VAR}") == "resolved-value"


def test_secret_resolver_leaves_unresolved_intact() -> None:
    """Unresolved placeholders pass through unchanged (no raise, no strip)."""
    assert (
        SootheConfig().secret_resolver("${DEFINITELY_MISSING_VAR_XYZ}")
        == "${DEFINITELY_MISSING_VAR_XYZ}"
    )


def test_secret_resolver_handles_embedded_and_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAR_A", "alpha")
    monkeypatch.setenv("VAR_B", "beta")
    resolver = SootheConfig().secret_resolver
    assert resolver("Bearer ${VAR_A}") == "Bearer alpha"
    assert resolver("${VAR_A}/${VAR_B}") == "alpha/beta"


def test_secret_resolver_passes_plain_values_through() -> None:
    assert SootheConfig().secret_resolver("no-placeholders-here") == "no-placeholders-here"
