"""Pytest fixtures for soothe-nano (no SootheRunner / StrangeLoop)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from soothe_nano.config import SootheConfig


def pytest_addoption(parser) -> None:
    """Add custom command-line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (tests/integration/ and @pytest.mark.integration)",
    )


def pytest_configure(config) -> None:
    """Register markers."""
    config.addinivalue_line("markers", "integration: requires external services or slow e2e")
    config.addinivalue_line("markers", "slow: long-running or stress tests")
    config.addinivalue_line("markers", "requires_postgresql: requires PostgreSQL database")
    config.addinivalue_line("markers", "requires_llm_api: requires LLM API keys")


def _is_integration_item(item: pytest.Item) -> bool:
    if item.get_closest_marker("integration") is not None:
        return True
    path = str(item.path)
    return f"{os.sep}tests{os.sep}integration{os.sep}" in path


def pytest_collection_modifyitems(config, items) -> None:
    """Skip integration tests unless ``--run-integration`` is passed."""
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if _is_integration_item(item):
            item.add_marker(skip)


def _has_valid_api_key() -> bool:
    """True when at least one supported LLM provider credential is present."""
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
    )


_CACHED_BASE_CONFIG: SootheConfig | None = None


def _repo_root() -> Path:
    """Repository root: nearest ancestor holding pyproject.toml.

    Resolved by walking up from this file so the path holds both in the
    monorepo layout (``packages/soothe-nano/tests/``) and standalone.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return here.parents[1]


def get_base_config() -> SootheConfig:
    """Load integration base config once (develop nano.yml or env override)."""
    global _CACHED_BASE_CONFIG
    if _CACHED_BASE_CONFIG is None:
        env_path = os.environ.get("SOOTHE_INTEGRATION_BASE_CONFIG", "").strip()
        if env_path:
            p = Path(env_path).expanduser()
            _CACHED_BASE_CONFIG = (
                SootheConfig.from_yaml_file(str(p)) if p.is_file() else SootheConfig()
            )
        else:
            config_path = _repo_root() / "config" / "develop" / "nano.yml"
            _CACHED_BASE_CONFIG = (
                SootheConfig.from_yaml_file(str(config_path))
                if config_path.is_file()
                else SootheConfig()
            )
    return _CACHED_BASE_CONFIG


@pytest.fixture
def test_config() -> SootheConfig:
    """Minimal NanoConfig for unit tests."""
    return SootheConfig()


@pytest.fixture
def requires_llm_api(integration_config: SootheConfig):
    """Skip when LLM API credentials are missing or don't match the model.

    Beyond a coarse env-var check, this resolves the configured default chat
    model's provider and verifies the credential that provider actually needs
    is present. This prevents false positives where, e.g., only a DASHSCOPE key
    is set but the default model routes to the OpenAI provider (or vice versa).
    """
    if not _has_valid_api_key():
        pytest.skip(
            "Test requires LLM API key (set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "or DASHSCOPE_API_KEY)"
        )
    # Resolve the default model spec and verify the credential its provider
    # needs is actually present. A provider-key mismatch (e.g. only
    # DASHSCOPE_API_KEY set but default model is openai:gpt-4o-mini) would
    # otherwise surface as a hard error mid-test instead of a clean skip.
    try:
        specs = integration_config.resolve_model_specs("default")
    except Exception:
        specs = []
    if specs and not _spec_credential_available(integration_config, specs[0]):
        provider, _, model = specs[0].partition(":")
        pytest.skip(
            f"Default model '{provider}:{model}' needs a {provider} credential "
            f"that is not set in this environment"
        )
    # Verify the resolved default model can actually be created with the
    # current environment; a provider-key mismatch would otherwise surface
    # as a hard error mid-test instead of a clean skip.
    try:
        import openai

        cred_errors: tuple[type[BaseException], ...] = (openai.OpenAIError, ValueError)
    except ImportError:  # pragma: no cover - openai is a core dep
        cred_errors = (ValueError,)
    try:
        integration_config.create_chat_model("default")
    except cred_errors as exc:  # type: ignore[misc]
        pytest.skip(f"Default model cannot be created with current credentials: {exc}")


# Maps a provider name (the part before ':' in a model spec) to the env vars
# whose presence satisfies that provider when no explicit provider config
# supplies an api_key. Used by requires_llm_api to catch provider/key mismatch.
_PROVIDER_CREDENTIAL_ENVVARS = {
    "openai": ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "dashscope": ("DASHSCOPE_API_KEY",),
    "azure": ("AZURE_OPENAI_API_KEY", "AZURE_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "vertex": ("GOOGLE_APPLICATION_CREDENTIALS",),
}


def _spec_credential_available(config: SootheConfig, spec: str) -> bool:
    """True when the provider for *spec* has a resolvable api_key or env cred.

    Resolves the spec's provider through the config's provider list; if the
    provider entry supplies a resolvable api_key, that satisfies the check.
    Otherwise falls back to the well-known env vars for that provider type.
    """
    provider_name, _, _ = spec.partition(":")
    if not provider_name:
        return True
    provider = config.llm_factory.registry.get_provider(provider_name)
    if provider and provider.api_key:
        from soothe_nano.config.env import _resolve_provider_env

        resolved = _resolve_provider_env(
            provider.api_key, provider_name=provider.name, field_name="api_key"
        )
        if resolved:
            return True
    envvars = _PROVIDER_CREDENTIAL_ENVVARS.get(provider_name)
    if envvars:
        return any(os.getenv(v) for v in envvars)
    # Unknown provider: fall back to the coarse env-var check.
    return _has_valid_api_key()


@pytest.fixture
def integration_config() -> SootheConfig:
    """Develop nano.yml config for live LLM integration tests."""
    return get_base_config().model_copy(deep=True)


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Isolated workspace directory for filesystem/tool tests."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture(autouse=True)
def _isolate_soothe_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point SOOTHE_HOME at a temp dir that does not pollute per-test tmp_path."""
    home = tmp_path_factory.mktemp("soothe-home")
    monkeypatch.setenv("SOOTHE_HOME", str(home))
    monkeypatch.setattr("soothe_nano.config.SOOTHE_HOME", home)
    monkeypatch.setattr("soothe_nano.config.env.SOOTHE_HOME", home)
