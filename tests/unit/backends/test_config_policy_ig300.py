"""IG-300: ConfigDrivenPolicy filesystem boundary + metadata path extraction."""

from pathlib import Path
from types import SimpleNamespace

from soothe_nano.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
)
from soothe_nano.security.policy_profiles import (
    ConfigDrivenPolicy,
    _extract_required_permission,
)


def _security(
    *,
    allow_out: bool = False,
    require_approval_out: bool = True,
    allowed: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        allow_paths_outside_workspace=allow_out,
        require_approval_for_outside_paths=require_approval_out,
        denied_paths=[],
        allowed_paths=allowed or ["**"],
        denied_file_types=[],
        require_approval_for_file_types=[],
        whitelist_paths_bypass=[],
        whitelist_commands_bypass=[],
        hard_deny_severities={"critical"},
    )


def test_glob_outside_workspace_read_is_audited_allow(tmp_path: Path) -> None:
    """RFC-LOOP-030: outside-workspace reads are `high` hints — below the
    default critical-only hard set the policy allows with audit and the
    permission grant decides. The write boundary stays critical (see the
    companion test below)."""
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir=str(ws))
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="glob",
        tool_args={"path": str(other), "pattern": "*.py"},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "allow"


def test_edit_outside_workspace_write_still_denied(tmp_path: Path) -> None:
    """The workspace WRITE boundary is critical and hard-denies (RFC-LOOP-030)."""
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir=str(ws))
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "write", "*")])),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="edit_file",
        tool_args={"file_path": str(other / "x.md")},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "deny"
    assert "outside workspace" in d.reason


def test_read_file_allowed_inside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    f = ws / "a.txt"
    f.write_text("hi", encoding="utf-8")

    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir=str(ws))
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(
            frozenset([Permission("fs", "read", "*"), Permission("fs", "write", "*")])
        ),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"file_path": str(f)},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "allow"


def test_outside_path_need_approval_when_configured(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    cfg = SimpleNamespace(
        security=_security(allow_out=True, require_approval_out=True),
        workspace_dir=str(ws),
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": str(other / "x.txt")},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "need_approval"


def test_outside_allowed_when_flag_true_and_no_approval_required(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    cfg = SimpleNamespace(
        security=_security(allow_out=True, require_approval_out=False),
        workspace_dir=str(ws),
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": str(other / "x.txt")},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "allow"


def test_denied_by_allowed_paths_whitelist(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = SimpleNamespace(
        security=SimpleNamespace(
            allow_paths_outside_workspace=True,
            require_approval_for_outside_paths=False,
            denied_paths=[],
            allowed_paths=["/only/here/**"],
            denied_file_types=[],
            require_approval_for_file_types=[],
        ),
        workspace_dir=str(ws),
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": str(ws / "a.txt")},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "deny"
    assert "allowed pattern" in d.reason


def test_extract_required_permission_uses_file_path() -> None:
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"file_path": "/tmp/x"},
    )
    perm = _extract_required_permission(action)
    assert perm is not None
    assert perm.scope == "/tmp/x"


def test_run_background_denied_for_dangerous_command() -> None:
    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir="/tmp/ws")
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("shell", "execute", "*")])),
        scope_id="t1",
        workspace="/tmp/ws",
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="run_background",
        tool_args={"command": "rm -rf /"},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "deny"
    assert "Command blocked by security rule" in d.reason


def test_sensitive_system_path_read_audited_allow_write_denied(tmp_path: Path) -> None:
    """RFC-LOOP-030: sensitive system paths are `medium` hints on read
    (allow-with-audit) and `critical` hard-denies on write."""
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = SimpleNamespace(
        security=_security(allow_out=True, require_approval_out=False), workspace_dir=str(ws)
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action = ActionRequest(
        action_type="tool_call",
        tool_name="read_file",
        tool_args={"path": "/etc/hosts"},
    )
    d = policy.check(action, ctx)
    assert d.verdict == "allow"

    cfg_w = SimpleNamespace(
        security=_security(allow_out=True, require_approval_out=False), workspace_dir=str(ws)
    )
    policy_w = ConfigDrivenPolicy(config=cfg_w)
    ctx_w = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "write", "*")])),
        scope_id="t1",
        workspace=str(ws.resolve()),
    )
    action_w = ActionRequest(
        action_type="tool_call",
        tool_name="edit_file",
        tool_args={"file_path": "/etc/hosts"},
    )
    d_w = policy_w.check(action_w, ctx_w)
    assert d_w.verdict == "deny"
    assert "sensitive system pattern" in d_w.reason


def test_git_operations_including_push_allowed() -> None:
    cfg = SimpleNamespace(security=_security(allow_out=False), workspace_dir="/tmp/ws")
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("shell", "execute", "*")])),
        scope_id="t1",
        workspace="/tmp/ws",
    )

    commands = [
        "git status",
        "git fetch origin",
        "git pull origin main",
        "git clone https://example.com/repo.git",
        "git push origin main",
    ]
    for command in commands:
        decision = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="run_command",
                tool_args={"command": command},
            ),
            ctx,
        )
        assert decision.verdict == "allow"


def test_path_whitelist_bypass_overrides_default_deny() -> None:
    cfg = SimpleNamespace(
        security=SimpleNamespace(
            **{
                **_security(allow_out=False).__dict__,
                "whitelist_paths_bypass": ["/etc/**", "/private/etc/**"],
            }
        ),
        workspace_dir="/tmp/ws",
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
        scope_id="t1",
        workspace="/tmp/ws",
    )
    decision = policy.check(
        ActionRequest(
            action_type="tool_call",
            tool_name="read_file",
            tool_args={"path": "/etc/hosts"},
        ),
        ctx,
    )
    assert decision.verdict == "allow"


def test_command_whitelist_bypass_overrides_default_deny() -> None:
    cfg = SimpleNamespace(
        security=SimpleNamespace(
            **{
                **_security(allow_out=False).__dict__,
                "whitelist_commands_bypass": [r"rm\s+-rf\s+/"],
            }
        ),
        workspace_dir="/tmp/ws",
    )
    policy = ConfigDrivenPolicy(config=cfg)
    ctx = PolicyContext(
        active_permissions=PermissionSet(frozenset([Permission("shell", "execute", "*")])),
        scope_id="t1",
        workspace="/tmp/ws",
    )
    decision = policy.check(
        ActionRequest(
            action_type="tool_call",
            tool_name="run_command",
            tool_args={"command": "rm -rf /"},
        ),
        ctx,
    )
    assert decision.verdict == "allow"
