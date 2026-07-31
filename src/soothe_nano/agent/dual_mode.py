"""Opt-in dual-mode CoreAgent: AGENT and ASK graphs with per-thread pin."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from soothe_nano.agent.builder import AgentBuilder
from soothe_nano.agent.core_agent import SootheNanoAgent
from soothe_nano.agent.interaction_mode import (
    InteractionMode,
    resolve_interaction_mode,
)
from soothe_nano.config import SootheConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import BaseTool
    from langgraph.store.base import BaseStore
    from langgraph.types import Checkpointer
    from soothe_deepagents.backends.protocol import BackendProtocol
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from soothe_sdk.protocols.core_agent import CoreAgentCapabilities
    from soothe_sdk.protocols.memory import MemoryProtocol
    from soothe_sdk.protocols.planner import PlannerProtocol
    from soothe_sdk.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

ModeFactory = Callable[[InteractionMode], SootheNanoAgent]


class DualModeCoreAgent:
    """Routes calls to lazily compiled AGENT and ASK CoreAgent graphs.

    The first mode used for a given ``thread_id`` is pinned. A later call that
    requests a different mode for the same thread raises ``ValueError``. Pass a
    new ``thread_id`` (or call ``clear_thread_pin``) to switch modes.
    """

    def __init__(
        self,
        factory: ModeFactory,
        *,
        default_mode: InteractionMode = "agent",
        config: Any | None = None,
    ) -> None:
        self._factory = factory
        self._default_mode = default_mode if default_mode in ("agent", "ask") else "agent"
        self._config = config
        self._agents: dict[InteractionMode, SootheNanoAgent] = {}
        self._thread_modes: dict[str, InteractionMode] = {}

    @property
    def default_mode(self) -> InteractionMode:
        return self._default_mode

    @property
    def config(self) -> Any | None:
        if self._config is not None:
            return self._config
        if self._agents:
            return next(iter(self._agents.values())).config
        return None

    def materialize(self, mode: InteractionMode | None = None) -> SootheNanoAgent:
        """Compile (if needed) and return the agent for ``mode``."""
        resolved = mode if mode in ("agent", "ask") else self._default_mode
        agent = self._agents.get(resolved)
        if agent is None:
            agent = self._factory(resolved)
            self._agents[resolved] = agent
            logger.info("[Init] DualModeCoreAgent materialized mode=%s", resolved)
        return agent

    def clear_thread_pin(self, thread_id: str | None = None) -> None:
        """Clear mode pin for one thread, or all threads when ``thread_id`` is None."""
        if thread_id is None:
            self._thread_modes.clear()
            return
        self._thread_modes.pop(thread_id, None)

    def resolve_mode_for_config(self, config: RunnableConfig | None) -> InteractionMode:
        """Resolve and pin interaction mode for this call's thread."""
        configurable = (config or {}).get("configurable") or {}
        if not isinstance(configurable, dict):
            configurable = {}
        raw = configurable.get("interaction_mode")
        requested: InteractionMode
        if raw in ("agent", "ask"):
            requested = raw
        else:
            requested = self._default_mode

        thread_id = configurable.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            return requested

        pinned = self._thread_modes.get(thread_id)
        if pinned is None:
            self._thread_modes[thread_id] = requested
            return requested
        if pinned != requested:
            msg = (
                f"Thread {thread_id!r} is pinned to interaction_mode={pinned!r}; "
                f"cannot switch to {requested!r}. Use a new thread_id or "
                "clear_thread_pin() before changing modes."
            )
            raise ValueError(msg)
        return pinned

    def _agent_for(self, config: RunnableConfig | None) -> SootheNanoAgent:
        mode = self.resolve_mode_for_config(config)
        return self.materialize(mode)

    @property
    def graph(self) -> Any:
        return self.materialize(self._default_mode).graph

    @property
    def execution_graph(self) -> Any:
        return self.materialize(self._default_mode).execution_graph

    @property
    def checkpointer(self) -> Any:
        return self.materialize(self._default_mode).checkpointer

    @property
    def can_read_graph_state(self) -> bool:
        return self.materialize(self._default_mode).can_read_graph_state

    @property
    def memory(self) -> Any | None:
        return self.materialize(self._default_mode).memory

    @property
    def planner(self) -> Any | None:
        return self.materialize(self._default_mode).planner

    @property
    def policy(self) -> Any | None:
        return self.materialize(self._default_mode).policy

    @property
    def subagents(self) -> list[Any]:
        return self.materialize(self._default_mode).subagents

    @property
    def interaction_mode(self) -> InteractionMode:
        return self._default_mode

    def list_capabilities(self) -> CoreAgentCapabilities:
        return self.materialize(self._default_mode).list_capabilities()

    def astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
        durability: str | None = None,
    ) -> AsyncIterator[Any]:
        return self._agent_for(config).astream(
            input_arg,
            config,
            stream_mode=stream_mode,
            subgraphs=subgraphs,
            durability=durability,
        )

    async def aget_state(self, config: RunnableConfig | None = None) -> Any:
        return await self._agent_for(config).aget_state(config=config)

    async def ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
        return await self._agent_for(config).ainvoke(input_arg, config, durability=durability)

    def execution_astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
        durability: str | None = None,
    ) -> AsyncIterator[Any]:
        return self._agent_for(config).execution_astream(
            input_arg,
            config,
            stream_mode=stream_mode,
            subgraphs=subgraphs,
            durability=durability,
        )

    def execute_stream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        return self._agent_for(config).execute_stream(
            input_arg,
            config,
            stream_mode=stream_mode,
            subgraphs=subgraphs,
        )

    async def execution_aget_state(self, config: RunnableConfig | None = None) -> Any:
        return await self._agent_for(config).execution_aget_state(config=config)

    async def read_runtime_state(
        self,
        config: RunnableConfig | None = None,
        *,
        execution_scope: bool = False,
    ) -> Any:
        return await self._agent_for(config).read_runtime_state(
            config=config, execution_scope=execution_scope
        )

    async def execution_ainvoke(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        durability: str | None = None,
    ) -> Any:
        return await self._agent_for(config).execution_ainvoke(
            input_arg, config, durability=durability
        )


def create_dual_mode_nano_agent(
    config: SootheConfig | None = None,
    *,
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    backend: BackendProtocol | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    memory_store: MemoryProtocol | None = None,
    planner: PlannerProtocol | None = None,
    policy: PolicyProtocol | None = None,
    mcp_registry: Any | None = None,
    core_agent_kind: str | None = None,
    default_mode: InteractionMode | None = None,
) -> DualModeCoreAgent:
    """Build a DualModeCoreAgent that compiles AGENT and ASK graphs on demand.

    Shared kwargs (checkpointer, store, backend, mcp) are reused for both modes.
    Graphs are not compiled until first use of that mode.
    """
    cfg = config or SootheConfig()
    resolved_default = resolve_interaction_mode(default_mode, cfg)
    builder = AgentBuilder(cfg, mcp_registry=mcp_registry)

    def _factory(mode: InteractionMode) -> SootheNanoAgent:
        return builder.build(
            model=model,
            tools=tools,
            subagents=subagents,
            middleware=middleware,
            checkpointer=checkpointer,
            store=store,
            backend=backend,
            interrupt_on=interrupt_on,
            memory_store=memory_store,
            planner=planner,
            policy=policy,
            mcp_registry=mcp_registry,
            core_agent_kind=core_agent_kind,
            interaction_mode=mode,
        )

    return DualModeCoreAgent(
        _factory,
        default_mode=resolved_default,
        config=cfg,
    )


__all__ = [
    "DualModeCoreAgent",
    "create_dual_mode_nano_agent",
]
