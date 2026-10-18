"""Tests for unified WorkspaceContext (RFC-621)."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.workspace.workspace_runtime import WorkspaceRuntime


def test_default_context() -> None:
    ctx = WorkspaceRuntime.get()
    assert ctx.workspace is None
    assert ctx.virtual_mode is False
    assert ctx.virtual_home is None


def test_set_and_get_context() -> None:
    token = WorkspaceRuntime.set(workspace=Path("/project"), virtual_mode=False)
    ctx = WorkspaceRuntime.get()
    assert ctx.workspace == Path("/project")
    assert ctx.virtual_mode is False
    assert ctx.virtual_home is None
    WorkspaceRuntime.reset(token)


def test_set_with_virtual_mode() -> None:
    token = WorkspaceRuntime.set(workspace=Path("/project"), virtual_mode=True)
    ctx = WorkspaceRuntime.get()
    assert ctx.workspace == Path("/project")
    assert ctx.virtual_mode is True
    assert ctx.virtual_home == Path("/project/.soothe")
    WorkspaceRuntime.reset(token)


def test_reset_restores_previous() -> None:
    token1 = WorkspaceRuntime.set(workspace=Path("/first"), virtual_mode=False)
    token2 = WorkspaceRuntime.set(workspace=Path("/second"), virtual_mode=True)

    ctx = WorkspaceRuntime.get()
    assert ctx.workspace == Path("/second")

    WorkspaceRuntime.reset(token2)
    ctx = WorkspaceRuntime.get()
    assert ctx.workspace == Path("/first")

    WorkspaceRuntime.reset(token1)


def test_reset_without_token_clears() -> None:
    WorkspaceRuntime.set(workspace=Path("/project"), virtual_mode=True)
    WorkspaceRuntime.reset()
    ctx = WorkspaceRuntime.get()
    assert ctx.workspace is None
    assert ctx.virtual_mode is False
