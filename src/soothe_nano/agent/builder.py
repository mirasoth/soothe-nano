"""Coding CoreAgent construction logic."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from soothe_sdk.protocols.core_agent import CoreAgentCapabilities

from soothe_nano.agent.core_agent import SootheNanoAgent, ephemeral_execute_stream_enabled
from soothe_nano.agent.interaction_mode import (
    ASK_MUTATING_TOOL_GROUPS,
    ASK_POLICY_PROFILE,
    BYPASS_POLICY_PROFILE,
    FILESYSTEM_TOOLS_AGENT,
    FILESYSTEM_TOOLS_ASK,
    FILESYSTEM_TOOLS_PLAN,
    PLAN_POLICY_PROFILE,
    READONLY_GP_SYSTEM_PROMPT,
    InteractionMode,
    append_ask_system_prompt,
    append_bypass_system_prompt,
    append_plan_system_prompt,
    ask_permissions,
    bypass_permissions,
    filter_subagents_for_mode,
    plan_permissions,
    resolve_interaction_mode,
)
from soothe_nano.config import SootheConfig
from soothe_nano.middleware import build_soothe_middleware_stack
from soothe_nano.resolve import (
    resolve_memory,
    resolve_planner,
    resolve_policy,
    resolve_subagents,
    resolve_tools,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain_core.tools import BaseTool
    from langgraph.store.base import BaseStore
    from langgraph.types import Checkpointer
    from soothe_deepagents.backends.protocol import BackendProtocol
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from soothe_sdk.protocols.memory import MemoryProtocol
    from soothe_sdk.protocols.planner import PlannerProtocol
    from soothe_sdk.protocols.policy import PolicyProtocol

from langchain_core.language_models import BaseChatModel  # noqa: E402

_PARENT_OWNED_STATE_KEYS = frozenset({"workspace"})

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Builder for SootheNanoAgent instances."""

    def __init__(
        self,
        config: SootheConfig | None = None,
        mcp_registry: Any | None = None,
    ) -> None:
        self._config = config or SootheConfig()
        self._config.propagate_env()
        self._mcp_registry = mcp_registry

    def build(
        self,
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
        interaction_mode: InteractionMode | None = None,
    ) -> SootheNanoAgent:
        from soothe_deepagents import create_deep_agent

        create_start = time.perf_counter()
        selected_kind = (core_agent_kind or self._resolve_core_agent_kind()).strip().lower()
        if selected_kind != "coding":
            msg = (
                f"Unsupported core agent kind: {selected_kind!r}. "
                "Only 'coding' is currently implemented."
            )
            raise ValueError(msg)

        mode = resolve_interaction_mode(interaction_mode, self._config)
        is_ask = mode == "ask"
        is_plan = mode == "plan"
        is_bypass = mode == "bypass"
        is_readonly = is_ask or is_plan
        if is_bypass:
            logger.warning("[Init] Bypass mode active — all security enforcement disabled.")

        resolved_model: str | BaseChatModel
        resolved_model = model if model is not None else self._config.create_chat_model("default")
        default_model_instance = (
            resolved_model if isinstance(resolved_model, BaseChatModel) else None
        )

        resolve_start = time.perf_counter()
        resolved_memory = memory_store or self._resolve_memory()
        resolved_planner = planner or self._resolve_planner(default_model_instance)
        resolved_policy = policy or self._resolve_policy()
        resolve_ms = (time.perf_counter() - resolve_start) * 1000
        logger.debug("[Init] Protocols resolved (%.1fms)", resolve_ms)

        self._load_plugins()

        tools_start = time.perf_counter()
        config_tools = resolve_tools(
            self._config.tools,
            lazy=True,
            config=self._config,
            exclude_tool_groups=ASK_MUTATING_TOOL_GROUPS if is_readonly else None,
        )
        all_tools: list[BaseTool | Callable | dict[str, Any]] = list(config_tools)
        if tools:
            all_tools.extend(tools)

        registry = mcp_registry or self._mcp_registry
        if registry is not None:
            mcp_tools = registry.all_tools()
            if mcp_tools:
                all_tools.extend(mcp_tools)

            if registry.deferred_tools():
                from soothe_nano.mcp.mcp_progressive import create_search_mcp_tools_tool

                all_tools.append(create_search_mcp_tools_tool())

            from soothe_nano.mcp.mcp_resource_tools import create_mcp_resource_tools

            all_tools.extend(create_mcp_resource_tools(registry))

        if (
            self._config.progressive_tools.enabled
            and self._config.progressive_tools.search_tools_enabled
        ):
            from soothe_nano.toolkits.progressive.search_tool import create_search_tools_tool

            all_tools.append(create_search_tools_tool())

        if self._config.progressive_skills.search_skills_enabled:
            from soothe_nano.skills.discovery_tools import (
                create_invoke_skill_tool,
                create_search_skills_tool,
            )

            all_tools.append(create_search_skills_tool())
            all_tools.append(create_invoke_skill_tool())

        tools_ms = (time.perf_counter() - tools_start) * 1000
        logger.info("[Init] Tools resolved: %d tools (%.1fms)", len(all_tools), tools_ms)

        subagents_start = time.perf_counter()
        config_subagents = resolve_subagents(
            self._config,
            default_model=default_model_instance,
            lazy=True,
        )
        all_subagents: list[SubAgent | CompiledSubAgent] = list(config_subagents)
        if subagents:
            all_subagents.extend(subagents)
        all_subagents = filter_subagents_for_mode(all_subagents, mode)
        subagents_ms = (time.perf_counter() - subagents_start) * 1000
        logger.info(
            "[Init] Subagents resolved: %d agents (%.1fms)", len(all_subagents), subagents_ms
        )

        resolved_backend = backend or self._initialize_backend(resolved_policy)

        policy_profile = (
            ASK_POLICY_PROFILE
            if is_ask
            else (
                PLAN_POLICY_PROFILE if is_plan else (BYPASS_POLICY_PROFILE if is_bypass else None)
            )
        )
        default_middleware = build_soothe_middleware_stack(
            self._config,
            resolved_policy,
            mcp_registry=registry,
            policy_profile_name=policy_profile,
        )
        if all_tools:
            from soothe_nano.middleware.mcp_activation import MCPActivationMiddleware
            from soothe_nano.middleware.progressive_tools import ProgressiveToolMiddleware

            for mw in default_middleware:
                if isinstance(mw, ProgressiveToolMiddleware):
                    mw.set_tool_catalog(all_tools)
                elif isinstance(mw, MCPActivationMiddleware) and registry is not None:
                    mw.set_tool_catalog()
        host_prefix = self._host_middleware_prefix()
        host_suffix = self._host_middleware_suffix()
        all_middleware: tuple[AgentMiddleware, ...] = (
            *host_prefix,
            *default_middleware,
            *host_suffix,
            *middleware,
        )

        from soothe_nano.middleware.model_call_profiler import (
            install_model_call_profiler,
            is_profiler_enabled,
        )

        install_model_call_profiler(enabled=is_profiler_enabled(self._config))

        graph_subagents = self._filter_subagents_for_graph(all_subagents)
        catalog_names = self._collect_subagent_names(graph_subagents)

        system_prompt = self._config.resolve_system_prompt()
        if is_ask:
            system_prompt = append_ask_system_prompt(system_prompt)
        elif is_plan:
            system_prompt = append_plan_system_prompt(system_prompt)
        elif is_bypass:
            system_prompt = append_bypass_system_prompt(system_prompt)

        filesystem_tools = (
            FILESYSTEM_TOOLS_ASK
            if is_ask
            else (FILESYSTEM_TOOLS_PLAN if is_plan else FILESYSTEM_TOOLS_AGENT)
        )
        fs_permissions = (
            ask_permissions()
            if is_ask
            else (plan_permissions() if is_plan else (bypass_permissions() if is_bypass else None))
        )

        def _compile_deep_agent(cp: Checkpointer | None) -> Any:
            gp_mode = self._config.agent.runtime.general_purpose_subagent
            # GP is only available in agent interaction mode; ask/plan always off.
            gp_enabled = gp_mode != "off" and not is_readonly
            per_step = gp_enabled and gp_mode == "per_step"
            readonly = gp_enabled and gp_mode == "readonly"

            # Single-variant readonly: construct a profile that restricts the GP
            # subagent to read-only filesystem tools and write-deny permissions.
            gp_profile = None
            if readonly:
                from soothe_deepagents.profiles.harness.harness_profiles import (
                    GeneralPurposeSubagentProfile,
                )

                gp_profile = GeneralPurposeSubagentProfile(
                    filesystem_tools=list(FILESYSTEM_TOOLS_ASK),
                    permissions=ask_permissions(),
                    description=(
                        "Read-only research subagent for inspecting the workspace, searching "
                        "for files and content, and gathering context without modifying files."
                    ),
                    system_prompt=READONLY_GP_SYSTEM_PROMPT,
                )
            # Per-step variant routing: register a second, read-only GP variant
            # alongside the default (full) one so a host middleware can redirect
            # ``task`` calls to it on plan/ask steps. The model-visible name stays
            # ``general-purpose`` (full); ``general-purpose-readonly`` is the
            # redirect target, never advertised to the model.
            subagents_for_graph = graph_subagents or None
            if per_step:
                from soothe_deepagents.middleware.filesystem import (
                    FilesystemMiddleware,
                )

                readonly_gp_spec: SubAgent = {
                    "name": "general-purpose-readonly",
                    "description": (
                        "Read-only research subagent for inspecting the workspace, searching "
                        "for files and content, and gathering context without modifying files."
                    ),
                    "system_prompt": READONLY_GP_SYSTEM_PROMPT,
                    "model": resolved_model,
                    # Restrict the FS tool surface to read-only tools; the custom
                    # FilesystemMiddleware below replaces the default (parent-inheriting)
                    # one by name match in _apply_custom_middleware.
                    "middleware": [
                        FilesystemMiddleware(
                            backend=resolved_backend,
                            _permissions=ask_permissions(),
                            tools=list(FILESYSTEM_TOOLS_ASK),
                        ),
                    ],
                }
                subagents_for_graph = [*list(graph_subagents or []), readonly_gp_spec]
            return create_deep_agent(
                model=resolved_model,
                tools=all_tools or None,
                system_prompt=system_prompt,
                middleware=all_middleware,
                subagents=subagents_for_graph,
                skills=None,
                memory=self._config.memory or None,
                permissions=fs_permissions,
                checkpointer=cp,
                store=store,
                backend=resolved_backend,
                interrupt_on=interrupt_on,
                enable_general_purpose_subagent=gp_enabled,
                general_purpose_subagent_profile=gp_profile,
                filesystem_tools=filesystem_tools,
                parent_owned_state_keys=_PARENT_OWNED_STATE_KEYS,
                debug=self._config.debug,
                recursion_limit=int(self._config.agent.runtime.recursion_limit),
            )

        deep_agent_start = time.perf_counter()
        graph = _compile_deep_agent(checkpointer)
        deep_agent_ms = (time.perf_counter() - deep_agent_start) * 1000
        logger.info(
            "[Init] Deep agent graph created (%.1fms, mode=%s)",
            deep_agent_ms,
            mode,
        )

        execute_graph = None
        execute_graph_compiler = None

        if ephemeral_execute_stream_enabled():

            def execute_graph_compiler() -> Any:
                return _compile_deep_agent(checkpointer)

        capabilities = CoreAgentCapabilities(
            tools=tuple(self._collect_tool_names(all_tools)),
            subagents=tuple(catalog_names),
            features=(
                "langgraph",
                "checkpointer",
                "execution_graph",
                "interrupt_resume",
                "streaming",
            ),
            metadata={
                "runtime_kind": "coding",
                "interaction_mode": mode,
                "tool_count": len(all_tools),
                "subagent_count": len(graph_subagents),
            },
        )

        agent = SootheNanoAgent(
            graph=graph,
            config=self._config,
            memory=resolved_memory,
            planner=resolved_planner,
            policy=resolved_policy,
            subagents=graph_subagents,
            capabilities=capabilities,
            execute_graph=execute_graph,
            execute_graph_compiler=execute_graph_compiler,
            interaction_mode=mode,
        )

        total_ms = (time.perf_counter() - create_start) * 1000
        logger.info("[Init] CoreAgent ready (%.1fms total, mode=%s)", total_ms, mode)
        return agent

    def _filter_subagents_for_graph(
        self, all_subagents: list[SubAgent | CompiledSubAgent]
    ) -> list[SubAgent | CompiledSubAgent]:
        """Return subagent specs bound on the open ``task`` catalog.

        Host builders may override to withhold specialists for outer wiring.
        """
        return list(all_subagents)

    def _host_middleware_prefix(self) -> tuple[AgentMiddleware, ...]:
        """Optional host middleware prepended before the default nano stack."""
        return ()

    def _host_middleware_suffix(self) -> tuple[AgentMiddleware, ...]:
        """Optional host middleware appended after the default nano stack."""
        return ()

    def _resolve_core_agent_kind(self) -> str:
        runtime_cfg = getattr(getattr(self._config, "agent", None), "runtime", None)
        raw = getattr(runtime_cfg, "core_agent_kind", None) if runtime_cfg else None
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return "coding"

    @staticmethod
    def _collect_tool_names(tools: Sequence[BaseTool | Callable | dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for tool in tools:
            if isinstance(tool, dict):
                candidate = tool.get("name")
                if isinstance(candidate, str) and candidate:
                    names.append(candidate)
                continue
            name = getattr(tool, "name", None)
            if isinstance(name, str) and name:
                names.append(name)
                continue
            if callable(tool):
                names.append(getattr(tool, "__name__", "callable_tool"))
        return sorted(set(names))

    @staticmethod
    def _collect_subagent_names(subagents: Sequence[SubAgent | CompiledSubAgent]) -> list[str]:
        names: list[str] = []
        for subagent in subagents:
            name: str | None = None
            if isinstance(subagent, dict):
                raw = subagent.get("name")
                name = raw if isinstance(raw, str) else None
            else:
                raw_name = getattr(subagent, "name", None)
                name = raw_name if isinstance(raw_name, str) else None
            if name and name.strip():
                names.append(name.strip())
        return sorted(set(names))

    def _resolve_memory(self) -> MemoryProtocol | None:
        try:
            import asyncio

            try:
                asyncio.get_running_loop()
                return resolve_memory(self._config)
            except RuntimeError:
                result = asyncio.run(asyncio.to_thread(resolve_memory, self._config))
                return result if not isinstance(result, Exception) else None
        except RuntimeError:
            return resolve_memory(self._config)

    def _resolve_planner(self, default_model: BaseChatModel | None) -> PlannerProtocol | None:
        try:
            import asyncio

            try:
                asyncio.get_running_loop()
                return resolve_planner(self._config, default_model)
            except RuntimeError:
                result = asyncio.run(
                    asyncio.to_thread(resolve_planner, self._config, default_model)
                )
                return result if not isinstance(result, Exception) else None
        except RuntimeError:
            return resolve_planner(self._config, default_model)

    def _resolve_policy(self) -> PolicyProtocol | None:
        try:
            import asyncio

            try:
                asyncio.get_running_loop()
                return resolve_policy(self._config)
            except RuntimeError:
                result = asyncio.run(asyncio.to_thread(resolve_policy, self._config))
                return result if not isinstance(result, Exception) else None
        except RuntimeError:
            return resolve_policy(self._config)

    def _load_plugins(self) -> None:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from soothe_nano.plugin.global_registry import load_plugins

        plugins_start = time.perf_counter()
        try:
            coro = load_plugins(self._config)
            try:
                asyncio.get_running_loop()

                def _run_async_on_fresh_loop() -> None:
                    asyncio.run(coro)

                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(_run_async_on_fresh_loop).result()
            except RuntimeError:
                asyncio.run(coro)
        except RuntimeError:
            logger.debug("[Init] Plugin loading failed, will load on demand")
        plugins_ms = (time.perf_counter() - plugins_start) * 1000
        logger.info("[Init] Plugins loaded (%.1fms)", plugins_ms)

    def _initialize_backend(
        self,
        policy: PolicyProtocol | None,
    ) -> BackendProtocol:
        from soothe_nano.workspace import FrameworkFilesystem

        return FrameworkFilesystem.initialize(
            config=self._config,
            policy=policy,
        )


def create_nano_agent(
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
    core_agent_kind: str | None = None,
    interaction_mode: InteractionMode | None = None,
) -> SootheNanoAgent:
    return AgentBuilder(config).build(
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
        core_agent_kind=core_agent_kind,
        interaction_mode=interaction_mode,
    )
