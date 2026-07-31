"""Unit tests for ASK / AGENT interaction modes."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from soothe_sdk.protocols.policy import (
    ActionRequest,
    Permission,
    PolicyContext,
)

from soothe_nano.agent.dual_mode import DualModeCoreAgent
from soothe_nano.agent.interaction_mode import (
    ASK_MUTATING_TOOL_GROUPS,
    ASK_POLICY_PROFILE,
    ASK_SYSTEM_PROMPT_SUFFIX,
    FILESYSTEM_TOOLS_AGENT,
    FILESYSTEM_TOOLS_ASK,
    append_ask_system_prompt,
    ask_permissions,
    filter_subagents_for_mode,
    resolve_interaction_mode,
)
from soothe_nano.config import SootheConfig
from soothe_nano.config.models import AgentConfig, AgentRuntimeConfig
from soothe_nano.security.policy_profiles import (
    ASK_PROFILE,
    READONLY_PROFILE,
    ConfigDrivenPolicy,
)


class TestInteractionModeHelpers:
    def test_resolve_defaults_to_agent(self) -> None:
        assert resolve_interaction_mode(None, None) == "agent"
        assert resolve_interaction_mode(None, SootheConfig()) == "agent"

    def test_resolve_kwarg_overrides_config(self) -> None:
        cfg = SootheConfig(agent=AgentConfig(runtime=AgentRuntimeConfig(interaction_mode="ask")))
        assert resolve_interaction_mode("agent", cfg) == "agent"
        assert resolve_interaction_mode(None, cfg) == "ask"

    def test_filesystem_tool_lists(self) -> None:
        assert "write_file" in FILESYSTEM_TOOLS_AGENT
        assert "write_file" not in FILESYSTEM_TOOLS_ASK
        assert "read_file" in FILESYSTEM_TOOLS_ASK
        assert "file_info" in FILESYSTEM_TOOLS_ASK

    def test_ask_permissions_deny_write(self) -> None:
        rules = ask_permissions()
        assert len(rules) == 1
        assert rules[0].operations == ["write"]
        assert rules[0].mode == "deny"

    def test_filter_subagents_ask_allowlist(self) -> None:
        specs = [
            {"name": "planner", "description": "p"},
            {"name": "browser_use", "description": "b"},
        ]
        assert filter_subagents_for_mode(specs, "agent") == specs
        kept = filter_subagents_for_mode(specs, "ask")
        assert len(kept) == 1
        assert kept[0]["name"] == "planner"

    def test_append_ask_prompt(self) -> None:
        out = append_ask_system_prompt("Hello")
        assert out.startswith("Hello")
        assert ASK_SYSTEM_PROMPT_SUFFIX in out


class TestAskPolicyProfile:
    def test_ask_profile_registered(self) -> None:
        assert ASK_PROFILE.name == "ask"
        assert ASK_POLICY_PROFILE == "ask"

    def test_ask_allows_read_denies_write(self) -> None:
        assert ASK_PROFILE.permissions.contains(Permission("fs", "read", "*"))
        assert not ASK_PROFILE.permissions.contains(Permission("fs", "write", "*"))
        assert not ASK_PROFILE.permissions.contains(Permission("shell", "execute", "*"))
        assert len(ASK_PROFILE.approvable.permissions) == 0

    def test_ask_policy_check_denies_shell(self) -> None:
        policy = ConfigDrivenPolicy()
        ctx = PolicyContext(active_permissions=ASK_PROFILE.permissions)
        decision = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="run_command",
                tool_args={"command": "ls"},
            ),
            ctx,
        )
        assert decision.verdict == "deny"

    def test_readonly_still_approvable(self) -> None:
        """Soft readonly profile must remain distinct from hard ask."""
        assert READONLY_PROFILE.approvable.contains(Permission("fs", "write", "*"))
        assert not ASK_PROFILE.approvable.contains(Permission("fs", "write", "*"))


class TestAgentBuilderInteractionMode:
    def test_agent_mode_passes_agent_filesystem_tools(self) -> None:
        captured: dict[str, Any] = {}

        def _fake_create_deep_agent(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(name="graph")

        cfg = SootheConfig()
        with (
            patch(
                "soothe_deepagents.create_deep_agent",
                side_effect=_fake_create_deep_agent,
            ),
            patch(
                "soothe_nano.agent.builder.resolve_tools",
                return_value=[],
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
            from soothe_nano.agent.builder import AgentBuilder

            agent = AgentBuilder(cfg).build(interaction_mode="agent")

        assert agent.interaction_mode == "agent"
        assert captured["filesystem_tools"] == FILESYSTEM_TOOLS_AGENT
        assert captured.get("permissions") is None
        assert captured["enable_general_purpose_subagent"] is True

    def test_ask_mode_hard_ask_surface(self) -> None:
        captured: dict[str, Any] = {}
        resolve_kwargs: dict[str, Any] = {}

        def _fake_create_deep_agent(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(name="graph")

        def _fake_resolve_tools(*args: Any, **kwargs: Any) -> list[Any]:
            resolve_kwargs.update(kwargs)
            return []

        cfg = SootheConfig()
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
                return_value=[
                    {"name": "planner", "description": "p"},
                    {"name": "browser_use", "description": "b"},
                ],
            ),
            patch(
                "soothe_nano.agent.builder.build_soothe_middleware_stack",
                return_value=(),
            ) as mw_stack,
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
            from soothe_nano.agent.builder import AgentBuilder

            agent = AgentBuilder(cfg).build(interaction_mode="ask")

        assert agent.interaction_mode == "ask"
        assert captured["filesystem_tools"] == FILESYSTEM_TOOLS_ASK
        assert captured["permissions"] is not None
        assert captured["enable_general_purpose_subagent"] is False
        assert resolve_kwargs.get("exclude_tool_groups") == ASK_MUTATING_TOOL_GROUPS
        assert agent.list_capabilities().metadata.get("interaction_mode") == "ask"
        mw_stack.assert_called_once()
        assert mw_stack.call_args.kwargs.get("policy_profile_name") == ASK_POLICY_PROFILE
        prompt = captured["system_prompt"]
        assert isinstance(prompt, str)
        assert "Ask mode" in prompt or "ask" in prompt.lower()
        sub_names = {s.get("name") for s in (captured.get("subagents") or [])}
        assert sub_names == {"planner"}


class TestDualModeCoreAgent:
    def test_pin_and_conflict(self) -> None:
        built: list[str] = []

        def factory(mode: str) -> Any:
            built.append(mode)
            agent = MagicMock()
            agent.interaction_mode = mode
            agent.ainvoke = MagicMock(return_value="ok")
            return agent

        dual = DualModeCoreAgent(factory, default_mode="agent")  # type: ignore[arg-type]
        cfg_agent = {"configurable": {"thread_id": "t1", "interaction_mode": "agent"}}
        assert dual.resolve_mode_for_config(cfg_agent) == "agent"
        assert dual.resolve_mode_for_config(cfg_agent) == "agent"

        cfg_ask = {"configurable": {"thread_id": "t1", "interaction_mode": "ask"}}
        with pytest.raises(ValueError, match="pinned"):
            dual.resolve_mode_for_config(cfg_ask)

        dual.clear_thread_pin("t1")
        assert dual.resolve_mode_for_config(cfg_ask) == "ask"

    def test_materialize_both_modes(self) -> None:
        built: list[str] = []

        def factory(mode: str) -> Any:
            built.append(mode)
            agent = MagicMock()
            agent.interaction_mode = mode
            return agent

        dual = DualModeCoreAgent(factory, default_mode="agent")  # type: ignore[arg-type]
        a1 = dual.materialize("agent")
        a2 = dual.materialize("ask")
        a3 = dual.materialize("agent")
        assert built == ["agent", "ask"]
        assert a1 is a3
        assert a1 is not a2
