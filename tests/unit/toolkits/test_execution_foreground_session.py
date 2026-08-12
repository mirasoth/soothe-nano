"""Foreground session markers for in-flight run_command (cancel drain)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from soothe_nano.toolkits.execution import (
    _register_foreground_session,
    _run_shell_command_sync,
    _unregister_foreground_session,
)


def test_register_and_unregister_foreground_session(tmp_path: Path) -> None:
    path = _register_foreground_session(4242, cwd=str(tmp_path), command="sleep 1")
    assert path is not None
    assert path.name == "fg-4242.session"
    assert path.is_file()
    assert "sleep 1" in path.read_text(encoding="utf-8")
    _unregister_foreground_session(path)
    assert not path.exists()


def test_run_shell_command_sync_writes_and_clears_session(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 5151
    fake_proc.stdout = None
    fake_proc.returncode = 0
    fake_proc.communicate.return_value = ("ok\n", "")

    session_holder: dict[str, Path | None] = {"path": None}

    real_register = _register_foreground_session

    def _tracking_register(pid: int, *, cwd: str | None, command: str):
        path = real_register(pid, cwd=cwd, command=command)
        session_holder["path"] = path
        assert path is not None and path.is_file()
        return path

    with (
        patch("soothe_nano.toolkits.execution.subprocess.Popen", return_value=fake_proc),
        patch(
            "soothe_nano.toolkits.execution._register_foreground_session",
            side_effect=_tracking_register,
        ),
    ):
        completed = _run_shell_command_sync(
            "echo ok",
            cwd=str(tmp_path),
            timeout=5,
            max_output_chars=None,
        )

    assert completed.stdout == "ok\n"
    assert session_holder["path"] is not None
    assert not session_holder["path"].exists()
