"""Protocol, subagent, and tool resolution for create_nano_agent.

Covers protocol resolution (memory, planner, policy), infrastructure
resolution (durability, checkpointer), and tool/subagent resolution
(including the lazy subagent graph compilation). The shared checkpointer
pool lives in `soothe_nano.persistence.shared_checkpointer_pool`.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_nano.config import SootheConfig, SubagentConfig
from soothe_nano.config.models import ModelRole
from soothe_nano.core.exceptions import ConfigurationError
from soothe_nano.toolkits.filesystem_tools import build_filesystem_tools
from soothe_nano.workspace.workspace_paths import WorkspacePaths
from soothe_nano.workspace.workspace_policy import WorkspaceResolver

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.types import Checkpointer
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent

    from soothe_nano.protocols.durability import DurabilityProtocol
    from soothe_nano.protocols.memory import MemoryProtocol
    from soothe_nano.protocols.planner import PlannerProtocol
    from soothe_nano.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_FACTORIES",
    "resolve_checkpointer",
    "resolve_durability",
    "resolve_memory",
    "resolve_planner",
    "resolve_policy",
    "resolve_subagents",
    "resolve_tools",
]

# In-process LRU-style cache for resolved tool groups, so groups resolved once
# (sequentially or via parallel `ThreadPoolExecutor`) are reused on subsequent lookups.
_tool_cache: dict[tuple[str, str | None], list[BaseTool]] = {}


def get_cached_tools(tool_name: str, workspace: str | None = None) -> list[BaseTool] | None:
    """Get tools from cache if available.

    Args:
        tool_name: Name of the tool group.
        workspace: Workspace path for cache scoping. Tools resolved for
            different workspaces are cached separately.

    Returns:
        Cached tools or None if not cached.
    """
    return _tool_cache.get((tool_name, workspace))


def cache_tools(tool_name: str, tools: list[BaseTool], workspace: str | None = None) -> None:
    """Cache a tool group for reuse.

    Args:
        tool_name: Name of the tool group.
        tools: List of tools to cache.
        workspace: Workspace path for cache scoping.
    """
    _tool_cache[(tool_name, workspace)] = tools
    logger.debug(
        "Cached tool group '%s' (workspace=%s, %d tools)", tool_name, workspace, len(tools)
    )


def _workspace_backend_factory(
    *,
    virtual_mode: bool,
    max_file_size_mb: int,
) -> Callable[[str], Any]:
    """Build a workspace-scoped backend factory for surgical file tools."""
    from soothe_nano.workspace.workspace_filesystem import WorkspaceBackendRegistry

    def factory(workspace: str) -> Any:
        return WorkspaceBackendRegistry.get(
            Path(workspace).expanduser().resolve(),
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    return factory


def _build_soothe_file_tools(config: SootheConfig | None) -> list[BaseTool]:
    """Create filesystem tools bound to the effective workspace."""
    resolved_cwd = str(WorkspaceResolver.effective_tool_workspace(config))
    paths = WorkspacePaths.from_config(config) if config else None
    virtual_mode = paths.virtual_mode if paths is not None else False
    max_file_size_mb = paths.max_file_size_mb if paths is not None else 10
    backend = _workspace_backend_factory(
        virtual_mode=virtual_mode,
        max_file_size_mb=max_file_size_mb,
    )(resolved_cwd)
    return build_filesystem_tools(
        backend=backend,
        backup_enabled=True,
        workspace_root=resolved_cwd,
        workspace_backend_factory=_workspace_backend_factory(
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        ),
        tool_token_limit_before_evict=20000,
    )


def _get_subagent_factories() -> dict[str, Callable[..., SubAgent | CompiledSubAgent]]:
    """Lazily load subagent factories on first access.

    This avoids importing heavy subagent modules at module load time.
    """
    from soothe_nano.subagents.browser_use import create_browser_use_subagent
    from soothe_nano.subagents.computer_use import create_computer_use_subagent
    from soothe_nano.subagents.deep_research import create_deep_research_subagent
    from soothe_nano.subagents.plan import create_plan_subagent

    return {
        "planner": create_plan_subagent,
        "deep_research": create_deep_research_subagent,
        "browser_use": create_browser_use_subagent,
        "computer_use": create_computer_use_subagent,
    }


# Lazy accessor for SUBAGENT_FACTORIES
class _SubagentFactoriesAccessor:
    """Lazy accessor for subagent factories."""

    _factories: dict[str, Callable[..., SubAgent | CompiledSubAgent]] | None = None

    def get(self, key: str, default: Any = None) -> Any:
        if self._factories is None:
            self._factories = _get_subagent_factories()
        return self._factories.get(key, default)


SUBAGENT_FACTORIES = _SubagentFactoriesAccessor()


def _call_subagent_factory(factory: Any, kwargs: dict[str, Any]) -> Any:
    """Invoke a subagent factory and return its spec (dict or agent object).

    Plugin factories from `@subagent` are async; built-in factories are sync.
    When no event loop is running, coroutine results are driven with
    :func:`asyncio.run` (AgentBuilder runs in a synchronous context).
    When a loop is already running (e.g. async tests or nested async), the
    coroutine is completed on a worker thread with its own loop so we never
    call :func:`asyncio.run` from inside a running loop.
    """
    import asyncio
    import inspect
    from concurrent.futures import ThreadPoolExecutor

    result = factory(**kwargs)
    if not inspect.iscoroutine(result):
        return result
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(result)

    def _run_coro_on_fresh_loop(coro: Any) -> Any:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run_coro_on_fresh_loop, result).result()


def _resolve_subagent_chat_model(
    config: SootheConfig,
    sub_cfg: SubagentConfig,
    *,
    default_role: ModelRole,
) -> BaseChatModel:
    """Resolve a subagent chat model from an explicit spec or router role.

    When `sub_cfg.model` is set (`provider:model`), it takes precedence over
    `sub_cfg.model_role` and `default_role`.
    """
    if sub_cfg.model:
        return config.create_chat_model_for_spec(sub_cfg.model)
    role = sub_cfg.model_role or default_role
    return config.create_chat_model(role)


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


def resolve_tools(
    tools_config: Any,
    *,
    lazy: bool = False,
    config: SootheConfig | None = None,
    exclude_tool_groups: frozenset[str] | set[str] | None = None,
    sandbox_backend: Any = None,
) -> list[BaseTool]:
    """Resolve tool groups from ToolsConfig to instantiated langchain BaseTool lists.

    Args:
        tools_config: ToolsConfig instance with enabled tool groups.
        lazy: If True, load tool groups in parallel using a thread pool
            for faster startup.  Historically this created lazy proxies,
            but those are incompatible with langgraph ToolNode's eager
            metadata probing.
        config: Optional Soothe config for tool configuration.
        exclude_tool_groups: Optional tool group names to skip (e.g. Ask mode
        omits `shell`).
        sandbox_backend: Optional sandbox backend; when set, the shell tool
        group is rebuilt with a ``BackendShellExecutor`` bound to this
        backend (never cached, never resolved from plugins — both would
        leak host-bound shell tools into a sandboxed agent).

    Returns:
        Flat list of fully-initialised `BaseTool` instances.
    """
    import time

    # Get list of enabled tool group names
    # Note: "deep_research" is a subagent, not a tool group - handled in resolve_subagents()
    _tool_groups = [
        "shell",
        "datetime",
        "wizsearch",
        "http_requests",
        "deepxiv",
    ]
    skipped = frozenset(exclude_tool_groups or ())
    enabled_tools = []
    for name in _tool_groups:
        if name in skipped:
            continue
        group_cfg = getattr(tools_config, name, None)
        if group_cfg and group_cfg.enabled:
            enabled_tools.append(name)

    # Host-execution tools run on the host via subprocess (see toolkits.shell)
    # unless a sandbox backend rebinds them to the guest below.

    total_start = time.perf_counter()

    parallel = lazy and len(enabled_tools) > 1
    tools = (
        _resolve_tools_parallel(enabled_tools, config, sandbox_backend)
        if parallel
        else _resolve_tools_sequential(enabled_tools, config, sandbox_backend)
    )

    total_elapsed_ms = (time.perf_counter() - total_start) * 1000
    logger.info(
        "Resolved %d tool groups (%d tools) in %.1fms (parallel=%s)",
        len(enabled_tools),
        len(tools),
        total_elapsed_ms,
        parallel,
    )

    return tools


def _resolve_tools_sequential(
    tool_names: list[str],
    config: SootheConfig | None = None,
    sandbox_backend: Any = None,
) -> list[BaseTool]:
    """Load tool groups one-by-one, skipping failures."""
    tools: list[BaseTool] = []
    for name in tool_names:
        try:
            resolved = _resolve_single_tool_group(name, config, sandbox_backend)
            tools.extend(resolved)
        except Exception:
            logger.warning("Failed to load tool group '%s'", name, exc_info=True)
    return tools


def _resolve_tools_parallel(
    tool_names: list[str],
    config: SootheConfig | None = None,
    sandbox_backend: Any = None,
) -> list[BaseTool]:
    """Load tool groups concurrently via ThreadPoolExecutor.

    Overlaps I/O-bound module imports and network initialisation across
    tool groups while preserving the original ordering in the result.
    Failed groups are logged and skipped.
    """
    from concurrent.futures import ThreadPoolExecutor

    max_workers = min(len(tool_names), 4)
    results: dict[str, list[BaseTool]] = {}

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tool-load") as pool:
        futures = {
            name: pool.submit(_resolve_single_tool_group, name, config, sandbox_backend)
            for name in tool_names
        }
        for name in tool_names:
            try:
                results[name] = futures[name].result()
            except Exception:
                logger.warning("Failed to load tool group '%s'", name, exc_info=True)

    tools: list[BaseTool] = []
    for name in tool_names:
        tools.extend(results.get(name, []))
    return tools


_SHELL_FAMILY_TOOL_NAMES = frozenset(
    {"run_command", "run_background", "tail_background_log", "kill_process", "run_python"}
)
"""Shell tools resolvable individually; sandbox mode must rebind them too."""


def _resolve_sandbox_shell_tools(
    config: SootheConfig | None,
    sandbox_backend: Any,
) -> list[BaseTool]:
    """Build the five shell tools bound to the sandbox guest.

    Bypasses both the tool cache and the plugin registry: cached or plugin
    shell tools carry no executor and would silently run on the host.
    """
    from soothe_nano.toolkits.shell import BackendShellExecutor, build_shell_toolkit

    executor = BackendShellExecutor(sandbox_backend)
    return build_shell_toolkit(
        config=config,
        workspace_root=executor.workspace_root,
        executor=executor,
    ).get_tools()


def _resolve_single_tool_group(
    name: str,
    config: SootheConfig | None = None,
    sandbox_backend: Any = None,
) -> list[BaseTool]:
    """Resolve a single tool group name to a list of BaseTool instances with caching and profiling.

    This method checks the cache first, and if not found, delegates to the uncached version.
    """
    if sandbox_backend is not None and (name == "shell" or name in _SHELL_FAMILY_TOOL_NAMES):
        tools = _resolve_sandbox_shell_tools(config, sandbox_backend)
        if name == "shell":
            return tools
        tool_map = {tool.name: tool for tool in tools}
        if name in tool_map:
            return [tool_map[name]]
        logger.warning("Tool '%s' not found in sandbox ShellToolkit", name)
        return []

    from soothe_nano.workspace.workspace_filesystem import FrameworkFilesystem

    # Include workspace in cache key to prevent cross-workspace tool reuse
    current_ws = FrameworkFilesystem.get_current_workspace()
    ws_key = str(current_ws) if current_ws else None

    cached = get_cached_tools(name, workspace=ws_key)
    if cached is not None:
        logger.debug("Tool group '%s' loaded from cache (%d tools)", name, len(cached))
        return cached

    start = time.perf_counter()
    tools = _resolve_single_tool_group_uncached(name, config)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if tools:
        cache_tools(name, tools, workspace=ws_key)

    logger.debug("Tool group '%s' loaded in %.1fms (%d tools)", name, elapsed_ms, len(tools))
    return tools


def _resolve_single_tool_group_uncached(
    name: str, config: SootheConfig | None = None
) -> list[BaseTool]:
    """Resolve a single tool group name to a list of BaseTool instances.

    Args:
        name: Tool group name.
        config: Optional Soothe config for tool configuration.
    """
    # Try plugin registry first
    try:
        from soothe_nano.plugin.global_registry import get_plugin_registry, is_plugins_loaded

        if is_plugins_loaded():
            registry = get_plugin_registry()
            plugin_tools = registry.get_tools_for_group(name)
            if plugin_tools:
                logger.debug(
                    "Resolved tool group '%s' from plugins (%d tools)", name, len(plugin_tools)
                )
                return plugin_tools
    except RuntimeError:
        logger.debug(
            "Plugin registry not loaded, falling back to hardcoded dispatch for '%s'", name
        )

    # Toolkit dispatch using new toolkit classes
    if name == "datetime":
        from soothe_nano.toolkits.datetime import DatetimeToolkit

        toolkit = DatetimeToolkit()
        return toolkit.get_tools()

    if name == "wizsearch":
        from soothe_nano.toolkits.wizsearch import WizsearchToolkit

        web_search_config: dict = {}
        if config and hasattr(config, "tools") and hasattr(config.tools, "wizsearch"):
            ws = config.tools.wizsearch
            web_search_config = {
                "default_engines": ws.default_engines,
                "max_results_per_engine": ws.max_results_per_engine,
                "timeout": ws.timeout,
                "proxy": ws.proxy,
            }
        if config and hasattr(config, "debug"):
            web_search_config["debug"] = config.debug
        toolkit = WizsearchToolkit(config=web_search_config)
        return toolkit.get_tools()

    if name == "shell":
        from soothe_nano.toolkits.shell import build_shell_toolkit

        resolved_cwd = str(WorkspaceResolver.effective_tool_workspace(config))
        return build_shell_toolkit(
            config=config,
            workspace_root=resolved_cwd,
        ).get_tools()

    if name == "http_requests":
        from soothe_nano.toolkits.http_requests import HttpRequestsToolkit

        toolkit = HttpRequestsToolkit(config=config)
        return toolkit.get_tools()

    # Support individual tool names (map to consolidated group)
    if name in (
        "run_command",
        "run_background",
        "tail_background_log",
        "kill_process",
        "run_python",
    ):
        # Host-execution tools do not require a sandbox backend.
        from soothe_nano.toolkits.shell import build_shell_toolkit

        resolved_cwd = str(WorkspaceResolver.effective_tool_workspace(config))
        all_tools = build_shell_toolkit(
            config=config,
            workspace_root=resolved_cwd,
        ).get_tools()
        tool_map = {tool.name: tool for tool in all_tools}
        if name in tool_map:
            return [tool_map[name]]
        logger.warning("Tool '%s' not found in ShellToolkit", name)
        return []

    # Support individual tool names (map to consolidated group)
    if name in (
        "read_file",
        "write_file",
        "delete",
        "search_files",
        "list_files",
        "file_info",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "apply_diff",
    ):
        full_tool_map = {tool.name: tool for tool in _build_soothe_file_tools(config)}
        if name in full_tool_map:
            return [full_tool_map[name]]
        logger.warning("Tool '%s' not found in filesystem tools", name)
        return []

    if name == "deepxiv":
        from soothe_nano.toolkits.deepxiv import DeepxivToolkit, resolve_deepxiv_token

        token: str | None = None
        timeout = 60
        max_retries = 3
        if config and hasattr(config, "tools"):
            dx = getattr(config.tools, "deepxiv", None)
            if dx:
                token = getattr(dx, "token", None)
                timeout = getattr(dx, "timeout", 60)
                max_retries = getattr(dx, "max_retries", 3)
        toolkit = DeepxivToolkit(
            token=resolve_deepxiv_token(token),
            timeout=timeout,
            max_retries=max_retries,
        )
        return toolkit.get_tools()

    logger.warning("Unknown tool group '%s', skipping.", name)
    return []


# ---------------------------------------------------------------------------
# Subagent resolution
# ---------------------------------------------------------------------------


def resolve_subagents(
    config: SootheConfig,
    default_model: BaseChatModel | None = None,
    *,
    lazy: bool = False,
    sandbox_backend: Any | None = None,
) -> list[SubAgent | CompiledSubAgent]:
    """Build subagent specs from config.

    Args:
        config: Soothe configuration.
        default_model: Pre-configured model instance to use as default.
        lazy: Accepted for API compatibility with `resolve_tools`; spec
            registration is already lazy (graphs compile on first invoke).
        sandbox_backend: Optional composite sandbox backend (sandbox mode).
            Threaded into subagent contexts that need it (planner recon
            tools bind to it — RFC §7.2-7).

    Returns:
        List of subagent specs for the runtime.
    """
    del lazy  # Registration is inherently lazy; kept for API compatibility.

    total_start = time.perf_counter()

    # Collect (name, factory, kwargs) tuples for enabled subagents
    pending: list[tuple[str, Callable, dict]] = []
    resolved_cwd = str(WorkspaceResolver.effective_tool_workspace(config))

    for name, sub_cfg in config.subagents.items():
        if not sub_cfg.enabled:
            continue

        factory = None
        resolved_via_plugin = False
        try:
            from soothe_nano.plugin.global_registry import get_plugin_registry, is_plugins_loaded

            if is_plugins_loaded():
                registry = get_plugin_registry()
                reg_factory = registry.get_subagent_factory(name)
                if reg_factory is not None:
                    factory = reg_factory
                    resolved_via_plugin = True
                    logger.debug("Resolved subagent '%s' from plugin registry", name)
        except RuntimeError:
            logger.debug("Plugin registry not loaded, using fallback for '%s'", name)

        if factory is None:
            factory = SUBAGENT_FACTORIES.get(name)

        if factory is None:
            logger.warning("Unknown subagent '%s', skipping.", name)
            continue

        if name == "deep_research":
            model_override = _resolve_subagent_chat_model(config, sub_cfg, default_role="fast")
        elif name == "planner":
            model_override = _resolve_subagent_chat_model(config, sub_cfg, default_role="think")
        elif name in ("browser_use", "computer_use"):
            model_override = None
        else:
            model_override = sub_cfg.model or default_model or config.resolve_model("default")

        if resolved_via_plugin:
            from soothe_nano.plugin.context import create_plugin_context

            plugin_instance = factory.__self__
            pname = plugin_instance.manifest.name
            plugin_ctx = create_plugin_context(
                plugin_name=pname,
                config=dict(sub_cfg.config),
                soothe_config=config,
            )
            call_kwargs = dict(sub_cfg.config)
            call_kwargs["model"] = model_override
            call_kwargs["config"] = config
            call_kwargs["context"] = plugin_ctx
            pending.append((name, factory, call_kwargs))
            continue

        extra_kwargs: dict = dict(sub_cfg.config)
        if name == "deep_research":
            # Research YAML options live in ``config.subagents[name].config`` only.
            # Factories accept ``model``, ``SootheConfig``, and ``context``.
            extra_kwargs.clear()
            extra_kwargs["config"] = config
            extra_kwargs["context"] = {"work_dir": resolved_cwd}
        elif name == "planner":
            extra_kwargs.clear()
            extra_kwargs["config"] = config
            context: dict[str, Any] = {"work_dir": resolved_cwd}
            if sandbox_backend is not None:
                context["sandbox_backend"] = sandbox_backend
            extra_kwargs["context"] = context
        elif name in ("browser_use", "computer_use"):
            if name == "browser_use":
                from soothe_nano.subagents.browser_use.config_model import BrowserUseSubagentConfig

                cfg_cls = BrowserUseSubagentConfig
            else:
                from soothe_nano.subagents.computer_use.config_model import (
                    ComputerUseSubagentConfig,
                )

                cfg_cls = ComputerUseSubagentConfig

            extra_kwargs.clear()
            cfg_dict = dict(sub_cfg.config)
            if cfg_dict:
                extra_kwargs["config"] = cfg_cls(**cfg_dict)
            extra_kwargs["soothe_config"] = config
            pending.append((name, factory, extra_kwargs))
            continue

        pending.append((name, factory, {"model": model_override, **extra_kwargs}))

    subagents = _resolve_subagents_sequential(pending)

    total_elapsed_ms = (time.perf_counter() - total_start) * 1000
    logger.info("Resolved %d subagents in %.1fms", len(subagents), total_elapsed_ms)

    return subagents


def _resolve_subagents_sequential(
    pending: list[tuple[str, Callable, dict]],
) -> list[SubAgent | CompiledSubAgent]:
    """Register lazy subagent specs one-by-one (graphs compile on first task invoke)."""
    subagents: list[SubAgent | CompiledSubAgent] = []
    for name, factory, kwargs in pending:
        start = time.perf_counter()
        try:
            spec = lazy_compiled_subagent_spec(name, factory, kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("Registered lazy subagent '%s' in %.1fms", name, elapsed_ms)
            subagents.append(spec)
        except Exception:
            logger.exception("Failed to register subagent '%s'", name)
    return subagents


# ---------------------------------------------------------------------------
# Deferred subagent graph compilation for faster CoreAgent startup
# ---------------------------------------------------------------------------

_BUILTIN_DESCRIPTIONS: dict[str, str] = {
    "plan": (
        "Planning delegate with agentic loops: iteratively runs multiple readonly "
        "recon passes per round (and multiple collection rounds) to gather workspace "
        "evidence, then iteratively refines a full markdown execution plan before "
        "returning one report. Use when the main thread needs structured recon-plus-plan "
        "without doing every recon and rewrite itself."
    ),
    "deep_research": ("Public-domain research subagent for web, academic, and URL sources."),
    "computer_use": (
        "Desktop automation specialist for GUI tasks. Can take screenshots, "
        "click at screen coordinates, type text, press keyboard keys and "
        "hotkeys, and scroll. Use for desktop application control, visual "
        "UI interaction, and screen-based automation."
    ),
}


def subagent_description(name: str, factory: Callable[..., Any]) -> str:
    """Resolve task-tool description without compiling the subagent graph."""
    plugin_desc = getattr(factory, "_subagent_description", None)
    if isinstance(plugin_desc, str) and plugin_desc.strip():
        return plugin_desc
    return _BUILTIN_DESCRIPTIONS.get(name, f"Subagent '{name}'.")


class LazySubagentRunnable:
    """Runnable wrapper that compiles a subagent graph on first invoke."""

    def __init__(
        self,
        factory: Callable[..., Any],
        kwargs: dict[str, Any],
        name: str,
        *,
        pending_config: dict[str, Any] | None = None,
    ) -> None:
        self._factory = factory
        self._kwargs = kwargs
        self._name = name
        self._pending_config = pending_config
        self._delegate: Any | None = None
        self._lock = threading.Lock()

    def _materialize(self) -> Any:
        if self._delegate is not None:
            return self._delegate
        with self._lock:
            if self._delegate is not None:
                return self._delegate
            spec = _default_materialize(self._factory, self._kwargs)
            runnable = spec["runnable"] if isinstance(spec, dict) else spec.runnable
            if self._pending_config:
                runnable = runnable.with_config(self._pending_config)
            self._delegate = runnable
            logger.info("Materialized lazy subagent '%s'", self._name)
            return self._delegate

    def with_config(self, config: Any = None, **kwargs: Any) -> LazySubagentRunnable:
        merged = dict(self._pending_config or {})
        if config:
            if isinstance(config, dict):
                merged.update(config)
            else:
                merged["config"] = config
        merged.update(kwargs)
        cloned = LazySubagentRunnable(
            self._factory,
            self._kwargs,
            self._name,
            pending_config=merged or None,
        )
        if self._delegate is not None:
            cloned._delegate = self._delegate.with_config(config, **kwargs)
        return cloned

    def invoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._materialize().invoke(state, config, **kwargs)

    async def ainvoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._materialize().ainvoke(state, config, **kwargs)

    def stream(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._materialize().stream(state, config, **kwargs)

    async def astream(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        async for chunk in self._materialize().astream(state, config, **kwargs):
            yield chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self._materialize(), name)


def _default_materialize(factory: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    return _call_subagent_factory(factory, kwargs)


def lazy_compiled_subagent_spec(
    name: str,
    factory: Callable[..., Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build a CompiledSubAgent dict without compiling the underlying graph."""
    return {
        "name": name,
        "description": subagent_description(name, factory),
        "runnable": LazySubagentRunnable(factory, kwargs, name),
    }


# ---------------------------------------------------------------------------
# Protocol resolution (memory, planner, policy)
# ---------------------------------------------------------------------------


def _create_loop_phase_model(
    config: SootheConfig,
    role: str,
    *,
    fallback: BaseChatModel | None,
    phase: str,
) -> BaseChatModel | None:
    """Resolve a loop-phase chat model from router role."""
    try:
        return config.create_chat_model(role)
    except Exception:
        logger.warning(
            "Failed to create %s model for role=%s; falling back to planner model",
            phase,
            role,
            exc_info=True,
        )
        return fallback


def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation using MemU.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if not config.agent.protocols.memory.enabled:
        return None

    try:
        from soothe_nano.backends.memory.memu_adapter import MemUMemory

        logger.info(
            "Using MemU memory backend (chat: %s, embed: %s)",
            config.resolve_model(config.agent.protocols.memory.llm_chat_role),
            config.resolve_model(config.agent.protocols.memory.llm_embed_role),
        )

        return MemUMemory(config)

    except ImportError:
        logger.exception("MemU memory backend requires dependencies")
        raise
    except Exception:
        logger.exception("Failed to initialize MemU memory backend")
        raise


def resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol | None:
    """Resolve planner protocol for Coding CoreAgent.

    `LLMPlanner` lives in full `soothe`. Inject via `AgentBuilder.build(planner=...)`.
    """
    del config, model
    return None


def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A PolicyProtocol instance.
    """
    from soothe_nano.security import ConfigDrivenPolicy

    return ConfigDrivenPolicy(config=config)


# ---------------------------------------------------------------------------
# Infrastructure resolution (durability, checkpointer)
# ---------------------------------------------------------------------------


def resolve_durability(
    config: SootheConfig,
    *,
    metadata_pool_cls: type | None = None,
) -> DurabilityProtocol:
    """Instantiate the DurabilityProtocol implementation from config.

    Supports: postgresql, sqlite backends (binary choice).
    Uses multi-database PostgreSQL architecture (metadata database).

    Args:
        config: Soothe configuration.
        metadata_pool_cls: Optional metadata pool class (host injects its
            registry-bound subclass). Defaults to nano `SharedMetadataPool`.
    """
    backend = config.resolve_durability_backend()  # Resolve inheritance
    if backend == "postgresql":
        try:
            from soothe_nano.backends.durability.postgresql import PostgreSQLDurability
            from soothe_nano.backends.persistence import create_persist_store
            from soothe_nano.persistence.shared_metadata_pool import SharedMetadataPool

            pool_cls = metadata_pool_cls or SharedMetadataPool
            # Use dedicated metadata database.
            dsn = config.resolve_postgres_dsn_for_database("metadata")
            shared_pool = pool_cls.get_or_create_pool(config)
            persist_store = create_persist_store(
                backend="postgresql",
                dsn=dsn,
                namespace="durability",
                config=config,
                shared_pool=shared_pool,
            )
            logger.debug("Using PostgreSQL durability backend (metadata database)")
            return PostgreSQLDurability(persist_store=persist_store)
        except Exception as e:
            logger.error(
                "PostgreSQL durability requested but failed: %s. "
                "Check PostgreSQL configuration and connectivity. "
                "Ensure soothe is up to date: pip install -U soothe-nano",
                e,
            )
            raise ConfigurationError(
                f"PostgreSQL durability backend unavailable: {e}\n"
                f"Verify postgres_base_dsn and postgres_databases configuration.\n"
                f"Ensure metadata database is created and accessible."
            )

    if backend == "sqlite":
        try:
            from soothe_nano.backends.durability.sqlite import SQLiteDurability

            logger.info("Using SQLite durability backend (databases/metadata.db)")
            return SQLiteDurability()
        except Exception as e:
            logger.error(
                "SQLite durability requested but failed: %s. "
                "Check sqlite3 installation and path configuration.",
                e,
            )
            raise ConfigurationError(
                f"SQLite durability backend unavailable: {e}\nVerify database path configuration."
            )

    raise ConfigurationError(
        f"Unknown durability backend: {backend}\nSupported backends: postgresql, sqlite"
    )


def resolve_checkpointer(
    config: SootheConfig,
    *,
    checkpointer_pool_cls: type | None = None,
) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Uses persistence configuration for PostgreSQL or SQLite connection.
    Uses dedicated checkpoints database for PostgreSQL.
    No fallback to in-memory storage - persistent storage required.

    Args:
        config: Soothe configuration.
        checkpointer_pool_cls: Optional checkpointer pool class (host injects
            its registry-bound subclass). Defaults to nano
            `SharedCheckpointerPool`.

    Returns:
        A tuple of (checkpointer, connection_resource) for PostgreSQL, or just the checkpointer for SQLite.
        The connection_resource must be closed during cleanup (e.g., via runner.cleanup()).
    """
    backend = config.resolve_checkpointer_backend()  # Resolve inheritance
    if backend == "postgresql":
        from soothe_nano.persistence.shared_checkpointer_pool import SharedCheckpointerPool

        pool_cls = checkpointer_pool_cls or SharedCheckpointerPool
        pool = pool_cls.get_or_create_pool(config)
        if pool is not None:
            return (None, pool)
        logger.error("PostgreSQL checkpointer unavailable")
        raise ConfigurationError(
            "PostgreSQL checkpointer requested but failed.\n"
            "Check postgres_base_dsn and postgres_databases configuration.\n"
            "Ensure checkpoints database is created and accessible.\n"
            "No fallback - production requires persistent storage."
        )

    if backend == "sqlite":
        result = _resolve_sqlite_checkpointer(config)
        if result:
            return result
        logger.error("SQLite checkpointer unavailable")
        raise ConfigurationError(
            "SQLite checkpointer requested but failed.\n"
            "Check sqlite3 installation and path configuration.\n"
            "No fallback - persistent storage required."
        )

    raise ConfigurationError(
        f"Unknown checkpointer backend: {backend}\n"
        f"Supported: postgresql, sqlite\n"
        f"No in-memory fallback - persistent storage required."
    )


def _resolve_sqlite_checkpointer(config: SootheConfig) -> tuple[Checkpointer | None, Any] | None:
    """Resolve SQLite checkpointer database path.

    Defers AsyncSqliteSaver creation to async context (same pattern as PostgreSQL).
    Callers that construct the saver need `langgraph-checkpoint-sqlite` installed.

    Returns:
        A tuple of (None, db_path) if successful, None otherwise.
        The runner will create AsyncSqliteSaver from the path in async context.
    """
    try:
        from soothe_nano.paths import resolve_checkpoints_db_path

        db_path = str(resolve_checkpoints_db_path())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Failed to create SQLite checkpointer path: %s", exc)
        return None

    logger.info("SQLite checkpointer path resolved at %s", db_path)
    return (None, db_path)
