"""Foreground session markers for in-flight run_command (cancel drain)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from soothe_nano.toolkits.shell import (
    PROCESS_META_SCHEMA,
    _register_foreground_session,
    _run_shell_command_sync,
    _unregister_foreground_session,
    marker_meta_path,
    process_start_token,
)


def test_register_and_unregister_foreground_session(tmp_path: Path) -> None:
    path = _register_foreground_session(4242, cwd=str(tmp_path), command="sleep 1")
    assert path is not None
    assert path.name == "fg-4242.session"
    assert path.is_file()
    assert "sleep 1" in path.read_text(encoding="utf-8")
    _unregister_foreground_session(path)
    assert not path.exists()


def test_foreground_session_writes_ownership_sidecar(tmp_path: Path) -> None:
    """The spawn-time ownership sidecar (``.meta``) is written and removed.

    The host drain refuses to kill a process group named by a marker unless
    the sidecar's pid/pgid/start-time identity matches the live process —
    marker names are agent-writable input.
    """
    path = _register_foreground_session(4343, cwd=str(tmp_path), command="sleep 1")
    assert path is not None
    meta_path = marker_meta_path(path)
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["schema"] == PROCESS_META_SCHEMA
    assert meta["pid"] == 4343
    _unregister_foreground_session(path)
    assert not path.exists()
    assert not meta_path.exists()


def test_process_start_token_for_live_process() -> None:
    """The start-time token resolves for a live PID (platform permitting)."""
    token = process_start_token(os.getpid())
    # None is acceptable on unsupported platforms; never an empty string.
    assert token is None or token != ""


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
        patch("soothe_nano.toolkits.shell.subprocess.Popen", return_value=fake_proc),
        patch(
            "soothe_nano.toolkits.shell._register_foreground_session",
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
