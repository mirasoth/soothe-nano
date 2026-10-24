"""Relative tool paths are anchored to the workspace root by the guard.

The file-tool backends resolve a bare relative path against the workspace
root; the operation guard must judge the same path, otherwise every natural
agent call like ``write_file("working/notes.md")`` is denied as "outside
workspace" because ``expand_path`` resolves it against the process CWD.
"""

from __future__ import annotations

from pathlib import Path

from soothe_nano.config.models import SecurityConfig
from soothe_nano.protocols.operation_security import OperationSecurityContext
from soothe_nano.security.operation_guard import WorkspaceToolOperationSecurity


def _ctx(ws: Path) -> OperationSecurityContext:
    sec = SecurityConfig(allow_paths_outside_workspace=False)
    return OperationSecurityContext(
        thread_id="t1",
        workspace=str(ws),
        security_config=sec,
    )


def test_relative_path_inside_workspace_allowed(tmp_path: Path) -> None:
    """``working/notes.md`` anchors under the workspace root → allow."""
    ws = tmp_path / "repo"
    ws.mkdir()

    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(_ctx(ws), "working/notes_draft.md")
    assert d.verdict == "allow"


def test_relative_path_nested_deliverables_allowed(tmp_path: Path) -> None:
    """Deep relative paths under the workspace root are allowed."""
    ws = tmp_path / "repo"
    ws.mkdir()

    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(_ctx(ws), "deliverables/report/final.md")
    assert d.verdict == "allow"


def test_relative_path_traversal_still_denied(tmp_path: Path) -> None:
    """Anchoring must not open traversal: ``working/../../etc/x`` escapes and
    is denied by the boundary check after resolution."""
    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()

    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(_ctx(ws), f"working/../../{outside.name}/escape.md")
    assert d.verdict == "deny"
    assert d.rule_id == "filesystem.workspace_boundary"


def test_relative_dot_path_inside_workspace_allowed(tmp_path: Path) -> None:
    """``./x`` and ``x`` behave identically (anchored, not CWD-resolved)."""
    ws = tmp_path / "repo"
    ws.mkdir()

    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(_ctx(ws), "./scratch.txt")
    assert d.verdict == "allow"


def test_absolute_outside_path_unchanged(tmp_path: Path) -> None:
    """Absolute paths outside the workspace keep the old deny (regression guard)."""
    ws = tmp_path / "repo"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(_ctx(ws), str((other / "x.md").resolve()))
    assert d.verdict == "deny"
    assert "outside workspace" in d.reason


def test_home_path_not_anchored_into_workspace(tmp_path: Path) -> None:
    """``~/...`` stays host-absolute (never pulled into the workspace)."""
    ws = tmp_path / "repo"
    ws.mkdir()

    ev = WorkspaceToolOperationSecurity()
    d = ev._check_filesystem(_ctx(ws), "~/.bashrc")
    # Either the dangerous-component deny or the workspace-boundary deny is
    # correct; it must never be allowed.
    assert d.verdict == "deny"
