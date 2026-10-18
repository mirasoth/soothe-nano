"""WorkspaceAwareBackend resolves stream workspace before process default."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from soothe_nano.workspace.workspace_filesystem import (
    WorkspaceAwareBackend,
    WorkspaceBackendRegistry,
)
from soothe_nano.workspace.workspace_runtime import WorkspaceRuntime


@pytest.fixture(autouse=True)
def _clear_backend_cache() -> None:
    WorkspaceBackendRegistry.clear()
    WorkspaceRuntime.reset()
    yield
    WorkspaceBackendRegistry.clear()
    WorkspaceRuntime.reset()


def test_get_backend_uses_contextvar_workspace(tmp_path: Path) -> None:
    default = tmp_path / "default-root"
    default.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")

    backend = WorkspaceAwareBackend(default_root_dir=default, virtual_mode=False)
    token = WorkspaceRuntime.set(workspace=project, virtual_mode=False)
    try:
        result = backend.glob("**/*.py")
        error = getattr(result, "error", None)
        matches = getattr(result, "matches", None) or []
        text = error or str(matches)
        assert "soothe-workspace" not in text
        assert any("a.py" in str(m) for m in matches) or (
            isinstance(matches, list) and len(matches) >= 1
        )
    finally:
        WorkspaceRuntime.reset(token)


def test_bind_workspace_sets_context_for_tool_hops(tmp_path: Path) -> None:
    default = tmp_path / "default-root"
    default.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    backend = WorkspaceAwareBackend(default_root_dir=default, virtual_mode=False)
    WorkspaceRuntime.reset()
    backend.bind_workspace(project)
    assert WorkspaceRuntime.get().workspace == project.resolve()
    assert WorkspaceRuntime.get().virtual_mode is False
    resolved = backend._get_backend()
    assert resolved._root_dir.resolve() == project.resolve()


def test_get_backend_falls_back_to_langgraph_configurable(tmp_path: Path) -> None:
    default = tmp_path / "default-root"
    default.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "b.py").write_text("y = 2\n", encoding="utf-8")

    backend = WorkspaceAwareBackend(default_root_dir=default, virtual_mode=False)
    with patch(
        "soothe_nano.workspace.workspace_policy.WorkspaceResolver.resolve_tool_execution",
        return_value=project,
    ):
        resolved = backend._get_backend()
    assert resolved._root_dir.resolve() == project.resolve()
