"""Unit tests for AgentBuilder sandbox-mode wiring (ArcBoxBackend injection)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from soothe_deepagents.backends.composite import CompositeBackend
from soothe_deepagents.backends.protocol import SandboxBackendProtocol

from soothe_nano.agent.builder import AgentBuilder
from soothe_nano.agent.interaction_mode import (
    FILESYSTEM_TOOLS_SANDBOX,
    SANDBOX_EXCLUDED_TOOL_GROUPS,
)
from soothe_nano.config import SootheConfig
from soothe_nano.resolve._resolver_tools import resolve_tools
from soothe_nano.sandbox.arcbox import ArcBoxBackend, CommandRunResult


class ScriptedClient:
    """Idle guest client: build-time code paths never run guest commands."""

    def run(
        self, command: str, *, cwd: str | None = None, timeout: int | None = None
    ) -> CommandRunResult:
        return CommandRunResult(stdout="", exit_code=0)

    def read_bytes(self, path: str) -> bytes:
        raise NotImplementedError

    def write_bytes(self, path: str, data: bytes) -> None:
        raise NotImplementedError


def make_sandbox(workspace_root: str = "/workspace") -> ArcBoxBackend:
    return ArcBoxBackend(
        sandbox_id="sbx-builder-test",
        client=ScriptedClient(),
        workspace_root=workspace_root,
    )


class TestExtractSandboxBackend:
    def test_bare_sandbox_detected(self) -> None:
        sandbox = make_sandbox()
        assert AgentBuilder._extract_sandbox_backend(sandbox) is sandbox

    def test_composite_default_unwrapped(self) -> None:
        sandbox = make_sandbox()
        composite = CompositeBackend(default=sandbox, routes={"/memories": sandbox})
        assert AgentBuilder._extract_sandbox_backend(composite) is sandbox

    def test_host_backend_returns_none(self) -> None:
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        assert AgentBuilder._extract_sandbox_backend(FilesystemBackend(root_dir="/tmp")) is None


class TestWrapSandboxBackend:
    def test_bare_sandbox_wrapped_with_host_routes(self) -> None:
        builder = AgentBuilder(SootheConfig())
        sandbox = make_sandbox()
        wrapped = builder._wrap_sandbox_backend(sandbox, sandbox, None)
        assert isinstance(wrapped, CompositeBackend)
        assert wrapped.default is sandbox
        assert set(wrapped.routes) == {"/memories", "/.soothe"}
        assert all(backend is not sandbox for backend in wrapped.routes.values())

    def test_caller_composite_trusted_as_is(self) -> None:
        builder = AgentBuilder(SootheConfig())
        sandbox = make_sandbox()
        composite = CompositeBackend(default=sandbox, routes={"/memories": sandbox})
        assert builder._wrap_sandbox_backend(sandbox, composite, None) is composite


class TestResolveToolsSandboxBinding:
    def test_shell_group_gets_guest_executor(self) -> None:
        sandbox = make_sandbox()
        tools_config = SootheConfig().tools
        tools = resolve_tools(tools_config, config=None, sandbox_backend=sandbox)
        shell_tools = [
            t
            for t in tools
            if getattr(t, "name", "")
            in {
                "run_command",
                "run_python",
                "run_background",
                "tail_background_log",
                "kill_process",
            }
        ]
        assert len(shell_tools) == 5
        for tool in shell_tools:
            executor = tool.executor
            assert executor is not None
            assert executor.workspace_root == "/workspace"

    def test_sandbox_shell_never_served_from_cache(self) -> None:
        sandbox_a, sandbox_b = make_sandbox(), make_sandbox()
        tools_config = SootheConfig().tools
        first = [
            t
            for t in resolve_tools(tools_config, sandbox_backend=sandbox_a)
            if t.name == "run_command"
        ]
        second = [
            t
            for t in resolve_tools(tools_config, sandbox_backend=sandbox_b)
            if t.name == "run_command"
        ]
        assert first and second
        assert first[0] is not second[0]
        assert first[0].executor._backend is sandbox_a
        assert second[0].executor._backend is sandbox_b

    def test_host_mode_shell_untouched(self) -> None:
        tools_config = SootheConfig().tools
        tools = resolve_tools(tools_config, config=None, sandbox_backend=None)
        run_command = next(t for t in tools if t.name == "run_command")
        assert run_command.executor is None


class TestAgentBuilderSandboxMode:
    def _build_with_patches(
        self,
        cfg: SootheConfig,
        backend: Any,
        resolve_kwargs: dict[str, Any],
        captured: dict[str, Any],
        *,
        interaction_mode: str | None = None,
    ) -> Any:
        def _fake_create_deep_agent(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(name="graph")

        def _fake_resolve_tools(*args: Any, **kwargs: Any) -> list[Any]:
            resolve_kwargs.update(kwargs)
            return []

        with (
            patch(
                "soothe_deepagents.create_deep_agent",
                side_effect=_fake_create_deep_agent,
            ),
            patch(
                "soothe_nano.agent.builder.resolve_tools",
                side_effect=_fake_resolve_tools,
            ),
            patch(
                "soothe_nano.agent.builder.resolve_subagents",
                return_value=[],
            ),
            patch(
                "soothe_nano.agent.builder.build_soothe_middleware_stack",
                return_value=(),
            ),
            patch.object(
                type(cfg),
                "create_chat_model",
                return_value=MagicMock(name="model"),
            ),
            patch(
                "soothe_nano.agent.builder.ephemeral_execute_stream_enabled",
                return_value=False,
            ),
        ):
            return AgentBuilder(cfg).build(backend=backend, interaction_mode=interaction_mode)

    def test_sandbox_backend_wrapped_and_fs_surface_extended(self) -> None:
        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        agent = self._build_with_patches(cfg, sandbox, resolve_kwargs, captured)

        backend_arg = captured["backend"]
        assert isinstance(backend_arg, CompositeBackend)
        assert backend_arg.default is sandbox
        assert set(backend_arg.routes) == {"/memories", "/.soothe"}

        assert captured["filesystem_tools"] == FILESYSTEM_TOOLS_SANDBOX
        assert captured["permissions"] is None
        assert resolve_kwargs.get("sandbox_backend") is sandbox
        excluded = resolve_kwargs.get("exclude_tool_groups") or frozenset()
        assert set(excluded) >= set(SANDBOX_EXCLUDED_TOOL_GROUPS)
        assert agent.list_capabilities().metadata.get("sandbox") is True

    def test_preassembled_composite_passes_through(self) -> None:
        cfg = SootheConfig()
        sandbox = make_sandbox()
        composite = CompositeBackend(default=sandbox, routes={"/memories": sandbox})
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        self._build_with_patches(cfg, composite, resolve_kwargs, captured)
        assert captured["backend"] is composite

    def test_host_backend_keeps_legacy_surface(self) -> None:
        from soothe_nano.agent.interaction_mode import FILESYSTEM_TOOLS_AGENT

        cfg = SootheConfig()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        self._build_with_patches(cfg, None, resolve_kwargs, captured)
        assert not isinstance(captured["backend"], CompositeBackend)
        assert captured["filesystem_tools"] == FILESYSTEM_TOOLS_AGENT
        assert captured["permissions"] is None
        assert resolve_kwargs.get("sandbox_backend") is None
        assert resolve_kwargs.get("exclude_tool_groups") is None

    def test_ask_plus_sandbox_drops_permissions_and_warns(self, caplog) -> None:
        from soothe_nano.agent.interaction_mode import (
            ASK_MUTATING_TOOL_GROUPS,
            FILESYSTEM_TOOLS_ASK,
        )

        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        self._build_with_patches(cfg, sandbox, resolve_kwargs, captured, interaction_mode="ask")
        assert captured["filesystem_tools"] == FILESYSTEM_TOOLS_ASK
        assert captured["permissions"] is None
        excluded = set(resolve_kwargs.get("exclude_tool_groups") or ())
        assert excluded >= set(ASK_MUTATING_TOOL_GROUPS) | set(SANDBOX_EXCLUDED_TOOL_GROUPS)
        assert "shell" in excluded  # readonly modes never expose shell, even guest-bound
        assert any("permissions dropped" in rec.message for rec in caplog.records)

    def test_sandbox_backend_is_protocol_instance(self) -> None:
        assert isinstance(make_sandbox(), SandboxBackendProtocol)
