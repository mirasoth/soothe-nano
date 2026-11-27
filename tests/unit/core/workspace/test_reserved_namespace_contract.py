"""Contract: `.soothe` is the single agent-plane private namespace.

The reserved names cannot be shared across repos (the sync engine lives in
the soothe monorepo), so each side pins the literal with a twin test like
this one. Changing these values is a cross-repo contract change — update
the sync-engine skip list (`soothe.workspace.sync.reserved`) in the same
change.
"""

from __future__ import annotations

from pathlib import Path

from soothe_nano.filesystem.workspace import WorkspaceFilesystem
from soothe_nano.security.operation_guard import (
    _PRIVATE_NAMESPACE_DIR,
    _PRIVATE_STATE_SUBDIRS,
)
from soothe_nano.utils.runtime import get_workspace_subagent_output_dir
from soothe_nano.workspace.workspace_paths import WorkspacePaths, WorkspaceRuntime


class TestReservedNameContract:
    def test_private_namespace_is_soothe(self) -> None:
        assert _PRIVATE_NAMESPACE_DIR == ".soothe"

    def test_framework_state_subdirs_are_the_pinned_set(self) -> None:
        assert _PRIVATE_STATE_SUBDIRS == frozenset(
            {
                "backups",
                "background",
                "foreground",
                "conversation_history",
                "large_tool_results",
                "skills",
            }
        )

    def test_private_namespace_is_hidden_from_listings(self) -> None:
        assert ".soothe" in WorkspaceFilesystem.ESSENTIAL_GLOB_EXCLUDES


class TestBackupDirNesting:
    def test_default_backup_dir_is_in_the_namespace(self, tmp_path: Path) -> None:
        paths = WorkspacePaths(tmp_path)
        resolved = paths.resolve_backup_dir(None)
        assert Path(resolved).parts[-2:] == (".soothe", "backups")

    def test_custom_backup_dir_is_nested_under_the_namespace(self, tmp_path: Path) -> None:
        paths = WorkspacePaths(tmp_path)
        resolved = paths.resolve_backup_dir("my-backups")
        parts = Path(resolved).parts
        assert parts[-2:] == (".soothe", "my-backups")

    def test_explicit_namespace_backup_dir_is_not_double_prefixed(self, tmp_path: Path) -> None:
        paths = WorkspacePaths(tmp_path)
        resolved = paths.resolve_backup_dir(".soothe/keep")
        assert Path(resolved).parts[-2:] == (".soothe", "keep")


class TestSubagentDirUnification:
    def test_workspace_bound_subagent_dir_lands_in_the_namespace(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        ws = tmp_path / "run-1"
        ws.mkdir()
        token = WorkspaceRuntime.set(workspace=ws)
        try:
            target = get_workspace_subagent_output_dir("deep_research")
        finally:
            WorkspaceRuntime.reset(token)
        assert target == ws / ".soothe" / "agents" / "deep_research"
        assert target.is_dir()


class TestProcessWorkspaceRoot:
    def test_fallback_lives_under_soothe_home(self, monkeypatch) -> None:
        from soothe_nano.config import SOOTHE_HOME

        monkeypatch.delenv("SOOTHE_WORKSPACE", raising=False)
        root = WorkspaceRuntime.process_workspace_root()
        assert root == Path(SOOTHE_HOME) / "data" / "tmp" / "workspace"
