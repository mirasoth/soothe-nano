"""Tests for the `agent.rules` host-rule key (`<HOST_RULES>` block rendering).

Contract:
- unset/empty/blank rules leave prompts unchanged (no block — zero drift guard);
- set rules render one bullet per entry, positioned after the identity block;
- both prompt surfaces carry the block: `SootheConfig.resolve_system_prompt()`
  (builder path) and `SystemPromptMiddleware._get_prompt_for_complexity`
  (runtime path, on every complexity tier).
"""

from __future__ import annotations

from soothe_nano.config.settings import SootheConfig
from soothe_nano.middleware.system_prompt import SystemPromptMiddleware
from soothe_nano.prompts.system_templates import SystemTemplates


def test_format_host_rules_none_and_empty_return_none() -> None:
    assert SystemTemplates.format_host_rules(None) is None
    assert SystemTemplates.format_host_rules([]) is None
    assert SystemTemplates.format_host_rules(["", "   "]) is None


def test_format_host_rules_renders_bullets() -> None:
    assert (
        SystemTemplates.format_host_rules(["Rule one", "Rule two"])
        == "<HOST_RULES>\n- Rule one\n- Rule two\n</HOST_RULES>"
    )
    # Blank entries are dropped; surrounding whitespace is stripped.
    assert SystemTemplates.format_host_rules(["  Rule  ", "", "Rule 2  "]) == (
        "<HOST_RULES>\n- Rule\n- Rule 2\n</HOST_RULES>"
    )


def test_resolve_system_prompt_without_rules_has_no_block() -> None:
    config = SootheConfig()
    assert config.agent.rules is None
    assert "<HOST_RULES>" not in config.resolve_system_prompt()


def test_resolve_system_prompt_with_rules_appends_block_after_identity() -> None:
    config = SootheConfig(agent={"name": "TestAgent", "rules": ["Keep deliverables clean"]})
    prompt = config.resolve_system_prompt()
    assert "<HOST_RULES>\n- Keep deliverables clean\n</HOST_RULES>" in prompt
    assert prompt.index("<ASSISTANT_IDENTITY>") < prompt.index("<HOST_RULES>")


def test_middleware_default_config_has_no_block() -> None:
    middleware = SystemPromptMiddleware(config=SootheConfig())
    for complexity in ("minimal", "simple", "medium", "complex"):
        assert "<HOST_RULES>" not in middleware._get_prompt_for_complexity(complexity, {}), (
            complexity
        )


def test_middleware_rules_present_on_every_tier() -> None:
    config = SootheConfig(agent={"name": "TestAgent", "rules": ["Rule A"]})
    middleware = SystemPromptMiddleware(config=config)
    for complexity in ("minimal", "simple", "medium", "complex"):
        prompt = middleware._get_prompt_for_complexity(complexity, {})
        assert "<HOST_RULES>\n- Rule A\n</HOST_RULES>" in prompt, complexity
