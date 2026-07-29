"""Unit tests for Soothe-targeting shell command bans (IG-622)."""

from __future__ import annotations

import pytest
from soothe_sdk.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityRequest,
)

from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity
from soothe_nano.toolkits.execution import (
    clear_protected_kill_hooks,
    register_protected_kill_hook,
)


def _eval(command: str):
    ev = WorkspaceToolOperationSecurity()
    return ev.evaluate(
        OperationSecurityRequest(
            action_type="tool_call",
            tool_name="run_command",
            tool_args={"command": command},
            operation_kind="shell_execute",
            command=command,
        ),
        OperationSecurityContext(workspace=None, security_config=None),
    )


@pytest.mark.parametrize(
    "command",
    [
        'pkill -9 -f "pytest packages/soothe"',
        "pkill -f soothed",
        "killall soothe",
        "soothed stop",
        "soothed restart",
        "kill $(lsof -t -iTCP:8765)",
        "kill -9 $(lsof -nP -iTCP:8765 -sTCP:LISTEN -t)",
        "kill $(cat ~/.soothe/soothed.pid)",
        "kill $(pgrep -f soothed)",
    ],
)
def test_operation_security_blocks_soothe_process_wipes(command: str) -> None:
    decision = _eval(command)
    assert decision.verdict == "deny"
    assert decision.rule_id is not None
    assert (
        "soothe" in decision.rule_id
        or "soothed" in decision.rule_id
        or "daemon" in decision.rule_id
    )


def test_operation_security_allows_unrelated_pkill() -> None:
    decision = _eval("pkill -f my_unrelated_worker")
    assert decision.verdict == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "kill 424242",
        "kill -9 424242",
        "kill -TERM 424242",
        "kill -s SIGTERM 424242",
        "kill 111 424242",
        "sleep 1; kill 424242; echo done",
    ],
)
def test_operation_security_blocks_kill_of_hook_protected_pid(command: str) -> None:
    clear_protected_kill_hooks()

    def refuse_daemon(pid: int) -> str | None:
        if pid == 424242:
            return "Error: refusing to kill Soothe daemon PID 424242"
        return None

    unregister = register_protected_kill_hook(refuse_daemon)
    try:
        decision = _eval(command)
        assert decision.verdict == "deny"
        assert decision.rule_id == "command.dangerous.kill_protected_pid"
        assert "424242" in (decision.reason or "")
    finally:
        unregister()
        clear_protected_kill_hooks()


def test_operation_security_allows_kill_of_unprotected_pid() -> None:
    clear_protected_kill_hooks()

    def refuse_daemon(pid: int) -> str | None:
        if pid == 424242:
            return "Error: refusing to kill Soothe daemon PID 424242"
        return None

    unregister = register_protected_kill_hook(refuse_daemon)
    try:
        decision = _eval("kill 999001")
        assert decision.verdict == "allow"
    finally:
        unregister()
        clear_protected_kill_hooks()
