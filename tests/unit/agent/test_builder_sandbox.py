"""Unit tests for AgentBuilder sandbox-mode wiring (ArcBoxBackend injection)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from soothe_deepagents.backends.composite import CompositeBackend
from soothe_deepagents.backends.protocol import SandboxBackendProtocol

from soothe_nano.agent.builder import AgentBuilder
from soothe_nano.agent.interaction_mode import (
    FILESYSTEM_TOOLS_ASK,
    FILESYSTEM_TOOLS_SANDBOX,
    SANDBOX_EXCLUDED_TOOL_GROUPS,
)
from soothe_nano.config import SootheConfig
from soothe_nano.sandbox.arcbox import ArcBoxBackend, CommandRunResult
from soothe_nano.utils.resolver import resolve_tools


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
        assert set(wrapped.routes) == {
            "/memories",
            "/.soothe",
            "/large_tool_results",
            "/conversation_history",
        }
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
        tools: list[Any] | None = None,
        config_subagents: list[Any] | None = None,
        subagent_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        def _fake_create_deep_agent(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(name="graph")

        def _fake_resolve_tools(*args: Any, **kwargs: Any) -> list[Any]:
            resolve_kwargs.update(kwargs)
            return []

        def _fake_resolve_subagents(*args: Any, **kwargs: Any) -> list[Any]:
            if subagent_kwargs is not None:
                subagent_kwargs.update(kwargs)
            return list(config_subagents or [])

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
                side_effect=_fake_resolve_subagents,
            ),
            patch(
                "soothe_nano.agent.builder.filter_subagents_for_mode",
                side_effect=lambda agents, mode: list(agents),
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
            return AgentBuilder(cfg).build(
                backend=backend,
                interaction_mode=interaction_mode,
                tools=tools,
            )

    def test_sandbox_backend_wrapped_and_fs_surface_extended(self) -> None:
        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        agent = self._build_with_patches(cfg, sandbox, resolve_kwargs, captured)

        backend_arg = captured["backend"]
        assert isinstance(backend_arg, CompositeBackend)
        assert backend_arg.default is sandbox
        # Framework-state prefixes routed to the host: memory, .soothe state,
        # and the upstream middleware artifact defaults (verified against
        # FilesystemMiddleware prefix resolution under a sandbox default).
        assert set(backend_arg.routes) == {
            "/memories",
            "/.soothe",
            "/large_tool_results",
            "/conversation_history",
        }

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


class TestSandboxToolPlacementGate:
    """Fail-closed gate for tools without a declared sandbox placement."""

    @staticmethod
    def _fake_tool(name: str) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(name=name)

    def test_undeclared_custom_tool_raises(self) -> None:
        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        with pytest.raises(ValueError, match="my_custom_tool"):
            TestAgentBuilderSandboxMode()._build_with_patches(
                cfg, sandbox, resolve_kwargs, captured, tools=[self._fake_tool("my_custom_tool")]
            )

    def test_override_declares_tool(self) -> None:
        cfg = SootheConfig()
        cfg.sandbox.placement_overrides.add("my_custom_tool")
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg, sandbox, resolve_kwargs, captured, tools=[self._fake_tool("my_custom_tool")]
        )
        assert any(getattr(t, "name", "") == "my_custom_tool" for t in captured["tools"])

    def test_on_deny_drop_removes_tool(self, caplog) -> None:
        cfg = SootheConfig()
        cfg.sandbox.on_deny = "drop"
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg, sandbox, resolve_kwargs, captured, tools=[self._fake_tool("mcp_fs_read")]
        )
        assert all(getattr(t, "name", "") != "mcp_fs_read" for t in captured["tools"])
        assert any("dropping undeclared tools" in rec.message for rec in caplog.records)

    def test_host_mode_never_gates(self) -> None:
        cfg = SootheConfig()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg, None, resolve_kwargs, captured, tools=[self._fake_tool("my_custom_tool")]
        )
        assert any(getattr(t, "name", "") == "my_custom_tool" for t in captured["tools"])

    def test_infra_catalog_tools_allowed(self) -> None:
        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg,
            sandbox,
            resolve_kwargs,
            captured,
            tools=[self._fake_tool(n) for n in ("search_tools", "mcp_resources_list")],
        )
        names = {getattr(t, "name", "") for t in captured["tools"]}
        assert {"search_tools", "mcp_resources_list"} <= names


class TestSandboxPlannerThreading:
    """RFC §7.2-7: planner recon tools bind to the injected sandbox backend."""

    def test_sandbox_mode_threads_backend_and_keeps_planner(self) -> None:
        from types import SimpleNamespace

        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        subagent_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg,
            sandbox,
            resolve_kwargs,
            captured,
            config_subagents=[
                SimpleNamespace(name="planner"),
                SimpleNamespace(name="deep_research"),
            ],
            subagent_kwargs=subagent_kwargs,
        )
        names = [getattr(sa, "name", None) for sa in captured["subagents"]]
        assert "planner" in names
        assert "deep_research" in names
        # Composite (resolved_backend) is threaded for the planner context.
        assert subagent_kwargs.get("sandbox_backend") is captured["backend"]

    def test_host_mode_passes_no_backend(self) -> None:
        from types import SimpleNamespace

        cfg = SootheConfig()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        subagent_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg,
            None,
            resolve_kwargs,
            captured,
            config_subagents=[SimpleNamespace(name="planner")],
            subagent_kwargs=subagent_kwargs,
        )
        assert any(getattr(sa, "name", None) == "planner" for sa in captured["subagents"])
        assert subagent_kwargs.get("sandbox_backend") is None


class TestAllModesTimesSandbox:
    """RFC §7.2-6: every interaction mode × sandbox combination must build."""

    def test_plan_plus_sandbox(self, caplog) -> None:
        from soothe_nano.agent.interaction_mode import (
            ASK_MUTATING_TOOL_GROUPS,
            FILESYSTEM_TOOLS_ASK,
        )

        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg, sandbox, resolve_kwargs, captured, interaction_mode="plan"
        )
        assert captured["filesystem_tools"] == FILESYSTEM_TOOLS_ASK
        assert captured["permissions"] is None
        excluded = set(resolve_kwargs.get("exclude_tool_groups") or ())
        assert excluded >= set(ASK_MUTATING_TOOL_GROUPS) | set(SANDBOX_EXCLUDED_TOOL_GROUPS)
        assert "shell" in excluded
        assert any("permissions dropped" in rec.message for rec in caplog.records)

    def test_bypass_plus_sandbox(self, caplog) -> None:
        cfg = SootheConfig()
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(
            cfg, sandbox, resolve_kwargs, captured, interaction_mode="bypass"
        )
        assert captured["filesystem_tools"] == FILESYSTEM_TOOLS_SANDBOX
        assert captured["permissions"] is None
        excluded = set(resolve_kwargs.get("exclude_tool_groups") or ())
        assert excluded >= set(SANDBOX_EXCLUDED_TOOL_GROUPS)
        assert "shell" not in excluded  # bypass keeps guest-bound shell
        assert any("permissions dropped" in rec.message for rec in caplog.records)


class RecordingClient:
    """Guest client recording every wire call for routing assertions."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, str | None]] = []
        self.written: dict[str, bytes] = {}

    def run(
        self, command: str, *, cwd: str | None = None, timeout: int | None = None
    ) -> CommandRunResult:
        self.commands.append((command, cwd))
        if command == "pwd":
            return CommandRunResult(stdout="/workspace", exit_code=0)
        return CommandRunResult(stdout="", exit_code=0)

    def read_bytes(self, path: str) -> bytes:
        return self.written.get(path, b"")

    def write_bytes(self, path: str, data: bytes) -> None:
        self.written[path] = data


class TestGeneralPurposeSubagentSandbox:
    """GP subagent variants stay host-permission-free under a sandbox backend."""

    def _sandbox_cfg(self, gp_mode: str) -> SootheConfig:
        cfg = SootheConfig()
        cfg.agent.runtime.general_purpose_subagent = gp_mode
        return cfg

    def test_per_step_registers_permissions_free_readonly_spec(self) -> None:
        from soothe_deepagents.middleware.filesystem import FilesystemMiddleware

        cfg = self._sandbox_cfg("per_step")
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(cfg, sandbox, resolve_kwargs, captured)

        assert captured["enable_general_purpose_subagent"] is True
        assert captured["general_purpose_subagent_profile"] is None
        spec = next(
            sa
            for sa in captured["subagents"]
            if isinstance(sa, dict) and sa.get("name") == "general-purpose-readonly"
        )
        assert len(spec["middleware"]) == 1
        fs_mw = spec["middleware"][0]
        assert isinstance(fs_mw, FilesystemMiddleware)
        # Sandbox mode: no host permissions, read-only tool allowlist only.
        assert fs_mw._permissions == []
        assert set(fs_mw._enabled_tools or frozenset()) == set(FILESYSTEM_TOOLS_ASK)
        assert fs_mw.backend is captured["backend"]

    def test_readonly_profile_empty_permissions_and_readonly_allowlist(self) -> None:
        cfg = self._sandbox_cfg("readonly")
        sandbox = make_sandbox()
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}
        TestAgentBuilderSandboxMode()._build_with_patches(cfg, sandbox, resolve_kwargs, captured)

        profile = captured["general_purpose_subagent_profile"]
        assert profile is not None
        assert profile.permissions == []
        assert list(profile.filesystem_tools) == list(FILESYSTEM_TOOLS_ASK)
        assert not {"write_file", "edit_file", "delete"} & set(FILESYSTEM_TOOLS_ASK)
        assert captured["enable_general_purpose_subagent"] is True
        # subagents_for_graph is None when no config subagents exist.
        assert not any(
            isinstance(sa, dict) and sa.get("name") == "general-purpose-readonly"
            for sa in captured["subagents"] or []
        )


class TestCompositeRoutingBehavior:
    """Behavioral routing of the builder-assembled composite shape.

    Mirrors ``_wrap_sandbox_backend``'s production shape (four host prefixes,
    sandbox default) against a real host ``FilesystemBackend`` and a
    recording guest client.
    """

    @staticmethod
    def _make_composite(sandbox: ArcBoxBackend, host_root: str) -> CompositeBackend:
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        return CompositeBackend(
            default=sandbox,
            routes={
                "/memories": FilesystemBackend(root_dir=host_root),
                "/.soothe": FilesystemBackend(root_dir=host_root),
                "/large_tool_results": FilesystemBackend(root_dir=host_root),
                "/conversation_history": FilesystemBackend(root_dir=host_root),
            },
        )

    def test_host_prefixes_guest_default_and_execute_routing(self, tmp_path) -> None:
        client = RecordingClient()
        sandbox = ArcBoxBackend(
            sandbox_id="sbx-routing", client=client, workspace_root="/workspace"
        )
        composite = self._make_composite(sandbox, str(tmp_path))

        uploads = composite.upload_files(
            [
                ("/memories/session.md", b"host-side"),
                ("/workspace/notes.txt", b"guest-side"),
                ("/workspace/.soothe/background/bg-1.log", b"guest-log"),
            ]
        )
        assert all(r.error is None for r in uploads)
        # Host prefixes land in the host backend's root, never the guest client.
        assert (tmp_path / "session.md").read_bytes() == b"host-side"
        # Guest paths (including guest-space .soothe logs) fall through to the
        # sandbox default.
        assert client.written == {
            "/workspace/notes.txt": b"guest-side",
            "/workspace/.soothe/background/bg-1.log": b"guest-log",
        }

        downloads = composite.download_files(["/memories/session.md"])
        assert downloads[0].content == b"host-side"

        # Execution is never path-routed: always the guest default.
        response = composite.execute("pwd")
        assert response.output == "/workspace"
        assert response.exit_code == 0
        assert client.commands == [("pwd", "/workspace")]


class TestExecuteToolHiddenInSandbox:
    """The built-in FS ``execute`` must never reach the model in sandbox mode.

    Guest shell access is owned by nano's ``run_command``; upstream
    ``FilesystemMiddleware`` constructs its ``execute`` tool unconditionally,
    so hiding relies on the allowlist-driven filter in
    ``_unsupported_tools_and_execution_state``.
    """

    def test_execute_filtered_out_of_model_requests(self) -> None:
        from soothe_deepagents.middleware.filesystem import FilesystemMiddleware

        # Construction-level guarantee: the allowlist never lists execute.
        assert "execute" not in FILESYSTEM_TOOLS_SANDBOX

        sandbox = make_sandbox()
        mw = FilesystemMiddleware(backend=sandbox, tools=list(FILESYSTEM_TOOLS_SANDBOX))
        # Middleware constructs execute unconditionally (upstream behavior).
        request_names = {t.name for t in mw.tools} | {"run_command"}
        assert "execute" in request_names

        # runtime=None is tolerated: workspace binding is duck-typed and no-ops.
        unsupported, execution_active, _ = mw._unsupported_tools_and_execution_state(
            request_names, None
        )
        assert "execute" in unsupported
        assert execution_active is False
        visible = {name for name in request_names if name not in unsupported}
        assert "execute" not in visible
        assert "run_command" in visible
