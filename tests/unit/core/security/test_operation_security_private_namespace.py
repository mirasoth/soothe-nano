"""Private-namespace protection in the operation guard.

`.soothe` framework-state subdirs are never written through direct tool
calls (critical → hard-deny under the default posture); reads stay allowed
(medium → audited risk_hint). The rest of the namespace — subagent outputs,
the virtual-mode home scratch area — stays writable, because `~` resolves
to `<workspace>/.soothe` in virtual mode and a blanket deny would break
benign home writes.
"""

from __future__ import annotations

from typing import Any

from soothe_nano.config.models import SecurityConfig
from soothe_nano.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityRequest,
)
from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity

_NO_SECURITY_CONFIG = object()


def _eval_fs(
    path: str,
    kind: str,
    *,
    workspace: str | None = None,
    hard: Any = _NO_SECURITY_CONFIG,
):
    ev = WorkspaceToolOperationSecurity()
    security = (
        SecurityConfig()
        if hard is _NO_SECURITY_CONFIG
        else SecurityConfig(hard_deny_severities=hard)
    )
    return ev.evaluate(
        OperationSecurityRequest(
            action_type="tool_call",
            tool_name="edit_file" if kind == "filesystem_write" else "read_file",
            tool_args={"file_path": path},
            operation_kind=kind,
            target_path=path,
        ),
        OperationSecurityContext(workspace=workspace, security_config=security),
    )


class TestPrivateNamespaceWrites:
    def test_framework_state_write_is_denied_under_default_posture(self) -> None:
        decision = _eval_fs(".soothe/backups/restore-1.md", "filesystem_write")
        assert decision.verdict == "deny"
        assert decision.rule_id == "filesystem.private_namespace"

    def test_absolute_framework_state_write_is_denied(self) -> None:
        decision = _eval_fs("/ws/run-1/.soothe/background/bg-1.log", "filesystem_write")
        assert decision.verdict == "deny"

    def test_conversation_history_write_is_denied(self) -> None:
        decision = _eval_fs("/ws/run-1/.soothe/conversation_history/compact.md", "filesystem_write")
        assert decision.verdict == "deny"

    def test_sandbox_posture_downgrades_to_hint(self) -> None:
        decision = _eval_fs(".soothe/skills/x/SKILL.md", "filesystem_write", hard=[])
        assert decision.verdict == "risk_hint"
        assert decision.rule_id == "filesystem.private_namespace"


class TestPrivateNamespaceReads:
    def test_framework_state_read_is_an_audited_hint(self) -> None:
        decision = _eval_fs("/ws/run-1/.soothe/background/bg-1.log", "filesystem_read")
        assert decision.verdict == "risk_hint"
        assert decision.rule_id == "filesystem.private_namespace"


class TestNamespaceRemainingWritable:
    def test_subagent_output_write_is_allowed(self) -> None:
        decision = _eval_fs("/ws/run-1/.soothe/agents/deep_research/report.md", "filesystem_write")
        assert decision.verdict == "allow"

    def test_virtual_home_scratch_write_is_allowed(self) -> None:
        """`~` resolves to `<workspace>/.soothe` in virtual mode — must stay writable."""
        decision = _eval_fs("/ws/run-1/.soothe/notes.md", "filesystem_write")
        assert decision.verdict == "allow"

    def test_rails_authoring_write_is_allowed(self) -> None:
        decision = _eval_fs("/ws/run-1/.soothe/rails/my-rail.yml", "filesystem_write")
        assert decision.verdict == "allow"
