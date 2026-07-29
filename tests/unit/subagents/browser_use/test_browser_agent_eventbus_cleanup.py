"""The browser subagent must shut down the browser Agent's own event bus.

``Agent.run()`` stops that bus on the way out, but the subagent drives a manual
``step()`` loop instead. A bus left running keeps a self-re-arming asyncio task
alive that prevents the calling process from exiting.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from bubus import EventBus
from langchain_core.messages import HumanMessage

from soothe_nano.config import SootheConfig
from soothe_nano.subagents.browser_use import create_browser_use_subagent
from soothe_nano.subagents.browser_use.config_model import BrowserUseSubagentConfig
from soothe_nano.subagents.browser_use.implementation import _stop_browser_agent_eventbus


@pytest.fixture(autouse=True)
async def _force_stop_leaked_buses() -> Any:
    """Reap any bus the code under test left running.

    Without this, a regression would hang the whole session in loop teardown
    instead of failing the assertion below.
    """
    yield
    for bus in list(EventBus.all_instances):
        if bus._is_running:
            await bus.stop(clear=True, timeout=0)


class _FakeHistory:
    history: list[Any] = []

    def is_done(self) -> bool:
        return True

    def final_result(self) -> str:
        return "scraped the page"


class _FakeSession:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeState:
    n_steps = 1


class _FakeBrowserAgent:
    """Stand-in for ``browser_use.Agent`` carrying a real ``bubus`` event bus."""

    instances: list[_FakeBrowserAgent] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.eventbus = EventBus(name="Agent_fake")
        self.eventbus._start()
        self.browser_session = _FakeSession()
        self.history = _FakeHistory()
        self.state = _FakeState()
        self.step_error: Exception | None = None
        _FakeBrowserAgent.instances.append(self)

    async def step(self) -> None:
        if self.step_error is not None:
            raise self.step_error


def _run_subagent() -> Any:
    subagent = create_browser_use_subagent(
        config=BrowserUseSubagentConfig(cleanup_on_exit=False, enable_existing_browser=False),
        soothe_config=SootheConfig(),
    )
    return subagent["runnable"]


async def _invoke(step_error: Exception | None = None) -> _FakeBrowserAgent:
    _FakeBrowserAgent.instances.clear()

    def make_agent(**kwargs: Any) -> _FakeBrowserAgent:
        agent = _FakeBrowserAgent(**kwargs)
        agent.step_error = step_error
        return agent

    module = "soothe_nano.subagents.browser_use.implementation"
    with (
        patch("browser_use.Agent", side_effect=make_agent),
        patch("browser_use.Browser"),
        patch("browser_use.llm.ChatOpenAI"),
        patch(f"{module}.cleanup_stale_chrome", return_value=0),
        patch(
            f"{module}._resolve_browser_llm_credentials",
            return_value=("test-model", None, None),
        ),
        patch(
            f"{module}._synthesize_browser_use_result",
            return_value=None,
        ),
    ):
        await _run_subagent().ainvoke({"messages": [HumanMessage(content="scrape a page")]})

    assert _FakeBrowserAgent.instances, "browser Agent was never constructed"
    return _FakeBrowserAgent.instances[-1]


async def test_eventbus_stopped_after_successful_run() -> None:
    agent = await _invoke()
    assert agent.eventbus._is_running is False
    assert agent.eventbus._runloop_task is None


async def test_eventbus_stopped_after_failed_step() -> None:
    agent = await _invoke(step_error=RuntimeError("browser blew up"))
    assert agent.eventbus._is_running is False
    assert agent.eventbus._runloop_task is None


async def test_run_leaves_no_stray_eventbus_task() -> None:
    before = {t for t in asyncio.all_tasks()}
    await _invoke()
    stray = [
        t
        for t in asyncio.all_tasks() - before
        if "_run_loop" in (t.get_name() or "") and not t.done()
    ]
    assert stray == []


async def test_stop_helper_tolerates_missing_bus() -> None:
    await _stop_browser_agent_eventbus(None, run_id="abc")
    await _stop_browser_agent_eventbus(object(), run_id="abc")


async def test_stop_helper_swallows_bus_errors() -> None:
    class _Exploding:
        async def stop(self, **_kwargs: Any) -> None:
            raise RuntimeError("nope")

    class _Agent:
        eventbus = _Exploding()

    await _stop_browser_agent_eventbus(_Agent(), run_id="abc")


@pytest.mark.parametrize("clear", [True])
async def test_stop_helper_clears_history(clear: bool) -> None:
    captured: dict[str, Any] = {}

    class _Recording:
        _is_running = True

        async def stop(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class _Agent:
        eventbus = _Recording()

    await _stop_browser_agent_eventbus(_Agent(), run_id="abc")
    assert captured["clear"] is clear
    assert captured["timeout"] == pytest.approx(3.0)
