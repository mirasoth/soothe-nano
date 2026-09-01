"""Unit tests for bypass mode in ConfigDrivenPolicy.

When the active profile is "bypass", ConfigDrivenPolicy.check() skips
operation security evaluation entirely, allowing dangerous commands
and bypass-immune paths that would otherwise be denied.
"""

from __future__ import annotations

from soothe_sdk.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityRequest,
)
from soothe_sdk.protocols.policy import (
    ActionRequest,
    PolicyContext,
)

from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity
from soothe_nano.security.policy_profiles import (
    BYPASS_PROFILE,
    STANDARD_PROFILE,
    ConfigDrivenPolicy,
)


def _policy_check(command: str | None = None, path: str | None = None) -> str:
    """Run a tool_call through ConfigDrivenPolicy with the bypass profile."""
    policy = ConfigDrivenPolicy()
    ctx = PolicyContext(active_permissions=BYPASS_PROFILE.permissions)
    tool_args: dict[str, str] = {}
    if command is not None:
        tool_args["command"] = command
    if path is not None:
        tool_args["file_path"] = path
    decision = policy.check(
        ActionRequest(
            action_type="tool_call",
            tool_name="run_command" if command else "edit_file",
            tool_args=tool_args,
        ),
        ctx,
    )
    return decision.verdict


def _op_security_eval(command: str | None = None, path: str | None = None) -> str:
    """Run an operation security check directly (no bypass)."""
    ev = WorkspaceToolOperationSecurity()
    if command is not None:
        req = OperationSecurityRequest(
            action_type="tool_call",
            tool_name="run_command",
            tool_args={"command": command},
            operation_kind="shell_execute",
            command=command,
        )
    else:
        req = OperationSecurityRequest(
            action_type="tool_call",
            tool_name="edit_file",
            tool_args={"file_path": path},
            operation_kind="filesystem_write",
            target_path=path,
        )
    ctx = OperationSecurityContext(workspace="/workspace", security_config=None)
    return ev.evaluate(req, ctx).verdict


class TestBypassMode:
    def test_bypass_allows_rm_rf_root(self) -> None:
        """rm -rf / is allowed through bypass policy."""
        assert _policy_check(command="rm -rf /") == "allow"

    def test_bypass_allows_sudo(self) -> None:
        """sudo is allowed through bypass policy."""
        assert _policy_check(command="sudo apt install foo") == "allow"

    def test_bypass_allows_shred(self) -> None:
        """shred is allowed through bypass policy."""
        assert _policy_check(command="shred /etc/passwd") == "allow"

    def test_bypass_allows_dangerous_path(self) -> None:
        """Editing .git/config is allowed through bypass policy."""
        assert _policy_check(path="/workspace/.git/config") == "allow"

    def test_bypass_allows_bashrc(self) -> None:
        """Editing .bashrc is allowed through bypass policy."""
        assert _policy_check(path="/home/user/.bashrc") == "allow"

    def test_non_bypass_still_blocks_rm_rf(self) -> None:
        """rm -rf / is still denied by operation security without bypass."""
        assert _op_security_eval(command="rm -rf /") == "deny"

    def test_non_bypass_still_blocks_git_path(self) -> None:
        """.git path is still denied by operation security without bypass."""
        assert _op_security_eval(path="/workspace/.git/config") == "deny"

    def test_standard_profile_still_blocks_rm_rf(self) -> None:
        """Standard profile (non-bypass) still denies rm -rf / at policy level."""
        policy = ConfigDrivenPolicy()
        ctx = PolicyContext(active_permissions=STANDARD_PROFILE.permissions)
        decision = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="run_command",
                tool_args={"command": "rm -rf /"},
            ),
            ctx,
        )
        assert decision.verdict == "deny"
