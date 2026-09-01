"""Unit tests for bypass_security flag on OperationSecurityContext.

When bypass_security=True, the WorkspaceToolOperationSecurity.evaluate()
method short-circuits to an allow verdict, skipping all path and command
checks — including bypass-immune dangerous paths and banned commands.
"""

from __future__ import annotations

from soothe_sdk.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityRequest,
)

from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity


def _eval_command(command: str, *, bypass: bool = False):
    ev = WorkspaceToolOperationSecurity()
    return ev.evaluate(
        OperationSecurityRequest(
            action_type="tool_call",
            tool_name="run_command",
            tool_args={"command": command},
            operation_kind="shell_execute",
            command=command,
        ),
        OperationSecurityContext(workspace=None, security_config=None, bypass_security=bypass),
    )


def _eval_path(path: str, *, bypass: bool = False):
    ev = WorkspaceToolOperationSecurity()
    return ev.evaluate(
        OperationSecurityRequest(
            action_type="tool_call",
            tool_name="edit_file",
            tool_args={"file_path": path},
            operation_kind="filesystem_write",
            target_path=path,
        ),
        OperationSecurityContext(
            workspace="/workspace", security_config=None, bypass_security=bypass
        ),
    )


class TestBypassSecurity:
    def test_bypass_allows_rm_rf_root(self) -> None:
        """rm -rf / is allowed when bypass_security=True."""
        decision = _eval_command("rm -rf /", bypass=True)
        assert decision.verdict == "allow"
        assert "bypass" in decision.reason.lower()

    def test_bypass_allows_sudo(self) -> None:
        """sudo is allowed when bypass_security=True."""
        decision = _eval_command("sudo apt install foo", bypass=True)
        assert decision.verdict == "allow"

    def test_bypass_allows_shred(self) -> None:
        """shred is allowed when bypass_security=True."""
        decision = _eval_command("shred /etc/passwd", bypass=True)
        assert decision.verdict == "allow"

    def test_bypass_allows_dangerous_path(self) -> None:
        """Editing .git/config is allowed when bypass_security=True."""
        decision = _eval_path("/workspace/.git/config", bypass=True)
        assert decision.verdict == "allow"

    def test_bypass_allows_bashrc(self) -> None:
        """Editing .bashrc is allowed when bypass_security=True."""
        decision = _eval_path("/home/user/.bashrc", bypass=True)
        assert decision.verdict == "allow"

    def test_non_bypass_still_blocks_rm_rf(self) -> None:
        """rm -rf / is still denied when bypass_security=False (default)."""
        decision = _eval_command("rm -rf /", bypass=False)
        assert decision.verdict == "deny"

    def test_non_bypass_still_blocks_git_path(self) -> None:
        """.git path is still denied when bypass_security=False (default)."""
        decision = _eval_path("/workspace/.git/config", bypass=False)
        assert decision.verdict == "deny"
