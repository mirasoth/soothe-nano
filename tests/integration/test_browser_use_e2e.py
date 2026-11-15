"""Integration tests for browser-use 1.x end-to-end against a local site.

Gated behind `--run-integration` (tests/integration/ auto-skips otherwise).
Offline scenarios need a local Chromium; LLM-driven ones additionally need
credentials (BROWSER_USE_E2E_API_KEY / OPENAI_API_KEY, or the configured
develop model) and are skipped without them.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from soothe_nano.config import SootheConfig

_SITE_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "browser_use_e2e" / "local_site.py"
)


def _load_local_site_class() -> type:
    """Import examples.browser_use_e2e.local_site (examples is not an installed package)."""
    spec = importlib.util.spec_from_file_location("browser_use_e2e_local_site", _SITE_MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.LocalSite


@pytest.fixture
def local_site():
    site = _load_local_site_class()()
    site.start()
    yield site
    site.stop()


def _build_e2e_config() -> SootheConfig:
    """Config whose browser_use model resolves to an OpenAI-compatible endpoint."""
    if os.getenv("BROWSER_USE_E2E_API_KEY") or os.getenv("OPENAI_API_KEY"):
        return SootheConfig()
    dashscope_key = os.getenv("DASHSCOPE_API_KEY")
    if not dashscope_key:
        pytest.skip(
            "needs an LLM key (BROWSER_USE_E2E_API_KEY / OPENAI_API_KEY / DASHSCOPE_API_KEY)"
        )
    from soothe_nano.config.models import ModelProviderConfig, ModelRouter, RouterProfile

    provider = ModelProviderConfig(
        name="dashscope",
        provider_type="openai",
        api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=dashscope_key,
        models=["qwen-plus"],
    )
    return SootheConfig(
        providers=[provider],
        router_profiles=[
            RouterProfile(name="e2e", router=ModelRouter(default="dashscope:qwen-plus"))
        ],
        active_router_profile="e2e",
    )


@pytest.mark.integration
async def test_browser_lifecycle_starts_and_stops_chromium(local_site) -> None:
    """Browser('chromium') starts a real local browser and stops cleanly."""
    from browser_use import Browser

    browser = Browser("chromium", headless=True)
    try:
        info = await browser.start()
        assert browser.kind == "chromium"
        assert info, "browser.start() returned no info"
    finally:
        await browser.stop()


@pytest.mark.integration
async def test_browser_use_subagent_end_to_end(
    local_site,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The soothe_nano browser_use subagent completes a run against the local site.

    Drives the real graph: router-resolved LLM, browser launch, agent.run(),
    wire events, and result quality gate.
    """
    from langchain_core.messages import HumanMessage

    from soothe_nano.subagents.browser_use import create_browser_use_subagent
    from soothe_nano.subagents.browser_use.config_model import BrowserUseSubagentConfig

    config = _build_e2e_config()
    browser_config = BrowserUseSubagentConfig(
        max_steps=12,
        cleanup_on_exit=False,
        enable_existing_browser=False,
        user_data_dir=str(tmp_path / "profile"),
    )
    subagent = create_browser_use_subagent(
        config=browser_config,
        soothe_config=config,
    )
    task = f"Open {local_site.url('/')} and report the alpha value shown in the list, exactly as printed."
    final = await subagent["runnable"].ainvoke({"messages": [HumanMessage(content=task)]})
    messages = final.get("messages", []) if isinstance(final, dict) else []
    answer = str(messages[-1].content) if messages else ""
    assert "4247" in str(answer), f"alpha marker missing from subagent answer: {answer[:300]!r}"


_RUNNER_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "examples" / "browser_use_e2e" / "run_e2e.py"
)


def _load_run_e2e_module() -> type:
    """Import the run_e2e harness (examples is not an installed package)."""
    spec = importlib.util.spec_from_file_location("browser_use_e2e_run", _RUNNER_MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
async def test_run_e2e_harness_offline_smoke(tmp_path: Path) -> None:
    """The example harness's offline scenarios run green without network access."""
    run_e2e = _load_run_e2e_module()
    assert set(run_e2e.DEFAULT_OFFLINE) <= set(run_e2e.SCENARIOS)
    exit_code = await run_e2e._run_scenarios(["browser_lifecycle"])
    assert exit_code == 0
