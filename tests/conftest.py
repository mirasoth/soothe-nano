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
        or (os.getenv("DASHSCOPE_CP_API_KEY") and os.getenv("DASHSCOPE_CP_BASE_URL"))
    )


_CACHED_BASE_CONFIG: SootheConfig | None = None


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
            # packages/soothe-nano/tests/conftest.py → monorepo root is parents[3]
            repo_root = Path(__file__).resolve().parents[3]
            config_path = repo_root / "config" / "develop" / "nano.yml"
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
def requires_llm_api():
    """Skip when no LLM API credentials are available."""
    if not _has_valid_api_key():
        pytest.skip(
            "Test requires LLM API key (set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "DASHSCOPE_API_KEY, or DASHSCOPE_CP_API_KEY + DASHSCOPE_CP_BASE_URL)"
        )


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
