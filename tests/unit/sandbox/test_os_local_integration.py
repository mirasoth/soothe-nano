"""Env-gated integration tests: real OS-primitive sandbox execution (no fakes).

Skipped unless the platform tier is actually available — macOS Seatbelt,
Linux bubblewrap (full tier), Linux Landlock (degraded tier, opt-in). These
tests execute real subprocesses through the sandbox boundary; keep them
small and fast. Everything that can be faked lives in
``test_os_local_backend.py`` instead.
"""

from __future__ import annotations

import os
import shlex
import socket
import sys
from pathlib import Path

import pytest

from soothe_nano.config.models import OsLocalSandboxConfig
from soothe_nano.sandbox.os_local import (
    OsLocalSandbox,
    _probe_bwrap,
    _probe_landlock,
)

_IS_DARWIN = sys.platform == "darwin"
_IS_LINUX = sys.platform == "linux"
_HAS_SEATBELT = _IS_DARWIN
_HAS_BWRAP = _IS_LINUX and _probe_bwrap()
_HAS_LANDLOCK = _IS_LINUX and _probe_landlock()

requires_seatbelt = pytest.mark.skipif(not _HAS_SEATBELT, reason="Seatbelt tier is macOS-only")
requires_bwrap = pytest.mark.skipif(not _HAS_BWRAP, reason="bubblewrap tier unavailable")
requires_landlock = pytest.mark.skipif(not _HAS_LANDLOCK, reason="Landlock tier unavailable")


def _sandbox(tmp_path: Path, **config_kwargs: object) -> OsLocalSandbox:
    cfg = OsLocalSandboxConfig(workspace_root=str(tmp_path), **config_kwargs)
    return OsLocalSandbox(cfg)


def _in_sandbox_python() -> str:
    """Interpreter readable from every tier's view of the filesystem.

    macOS narrow reads exclude ``$HOME`` (pyenv/venv interpreters) and
    ``/Applications``; homebrew and CommandLineTools interpreters live in
    the allowed trees.
    """
    if _IS_LINUX:
        return "/usr/bin/python3"
    for candidate in (
        "/opt/homebrew/bin/python3",
        "/Library/Developer/CommandLineTools/usr/bin/python3",
    ):
        if os.path.exists(candidate):
            return candidate
    return "/usr/bin/python3"


class TestSeatbeltIntegration:
    """Real sandbox-exec round-trips on macOS (narrow read, narrow write)."""

    @requires_seatbelt
    def test_write_read_inside_workspace(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        write = sandbox.execute("echo marker > in-ws.txt")
        assert write.exit_code == 0, write.output
        assert (tmp_path / "in-ws.txt").read_text().strip() == "marker"

    @requires_seatbelt
    def test_write_outside_workspace_denied(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        outside = tmp_path.parent / "seatbelt-escape-probe.txt"
        response = sandbox.execute(f"echo x > {shlex.quote(str(outside))}")
        assert response.exit_code != 0
        assert not outside.exists()

    @requires_seatbelt
    def test_dev_null_writable(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        response = sandbox.execute("echo x > /dev/null")
        assert response.exit_code == 0, response.output

    @requires_seatbelt
    def test_network_denied_by_default(self, tmp_path: Path) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            code = (
                "import socket\n"
                "try:\n"
                f"    socket.create_connection(('127.0.0.1', {port}), timeout=2)\n"
                "    print('CONNECTED')\n"
                "except OSError as exc:\n"
                "    print('BLOCKED', exc)\n"
            )
            sandbox = _sandbox(tmp_path)
            response = sandbox.execute(
                f"{shlex.quote(_in_sandbox_python())} -c {shlex.quote(code)}"
            )
            assert "CONNECTED" not in response.output
            assert "BLOCKED" in response.output
        finally:
            listener.close()

    @requires_seatbelt
    def test_read_outside_allow_set_denied(self, tmp_path: Path) -> None:
        """Read isolation parity: a home file is unreadable inside the sandbox."""
        sandbox = _sandbox(tmp_path)
        probe = Path.home() / ".soothe-os-sandbox-read-probe.txt"
        if tmp_path.is_relative_to(Path.home()) or Path.home().is_relative_to(tmp_path):
            pytest.skip("home and workspace overlap on this host")
        probe.write_text("host-secret")
        try:
            response = sandbox.execute(f"cat {shlex.quote(str(probe))}")
            assert response.exit_code != 0, response.output
            assert "host-secret" not in response.output
        finally:
            probe.unlink(missing_ok=True)

    @requires_seatbelt
    def test_system_tools_run(self, tmp_path: Path) -> None:
        """git and a python interpreter still work under the narrowed read set."""
        sandbox = _sandbox(tmp_path)
        response = sandbox.execute(
            f"cd {shlex.quote(str(tmp_path))} && git init -q . && git config user.email t@t"
            " && git config user.name t && echo x > a && git add a && git commit -qm i"
            " && git log --oneline | head -1"
        )
        assert response.exit_code == 0, response.output
        py = sandbox.execute(f"{shlex.quote(_in_sandbox_python())} -c 'print(\"py-ok\")'")
        assert py.exit_code == 0, py.output
        assert "py-ok" in py.output

    @requires_seatbelt
    def test_env_secret_never_crosses_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOOTHE_TEST_SECRET", "sentinel-value")
        sandbox = _sandbox(tmp_path)
        response = sandbox.execute('echo "secret=${SOOTHE_TEST_SECRET:-absent}"')
        assert "absent" in response.output
        assert "sentinel-value" not in response.output

    @requires_seatbelt
    def test_timeout_kills_process_group(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        response = sandbox.execute("sleep 30", timeout=2)
        assert response.exit_code == 124
        assert "exceeded timeout of 2s" in response.output

    @requires_seatbelt
    def test_upload_download_and_escape_rejection(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        path = str(tmp_path / "roundtrip.txt")
        assert sandbox.upload_files([(path, b"payload")])[0].error is None
        assert sandbox.download_files([path])[0].content == b"payload"

        escape = str(tmp_path.parent / "escape.txt")
        assert sandbox.upload_files([(escape, b"x")])[0].error is not None
        assert sandbox.download_files([escape])[0].error is not None

    @requires_seatbelt
    def test_close_removes_scratch(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        scratch = sandbox._scratch
        assert Path(scratch).is_dir()
        sandbox.close()
        assert not Path(scratch).exists()


class TestBwrapIntegration:
    """Real bwrap + seccomp round-trips on Linux (full tier, unshare-net)."""

    @requires_bwrap
    def test_write_read_inside_workspace(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        assert sandbox.tier == "bwrap"
        write = sandbox.execute("echo marker > in-ws.txt")
        assert write.exit_code == 0, write.output
        assert (tmp_path / "in-ws.txt").read_text().strip() == "marker"

    @requires_bwrap
    def test_write_outside_workspace_denied(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        response = sandbox.execute("echo x > /var/tmp/bwrap-escape-probe.txt")
        assert response.exit_code != 0
        assert not Path("/var/tmp/bwrap-escape-probe.txt").exists()

    @requires_bwrap
    def test_timeout_kills_process_group(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path)
        response = sandbox.execute("sleep 30", timeout=2)
        assert response.exit_code == 124
        assert "exceeded timeout of 2s" in response.output


class TestLandlockIntegration:
    """Real Landlock round-trips on Linux (degraded tier — opt-in only)."""

    @requires_landlock
    def test_tier_and_posture(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path, linux_tier="landlock", allow_degraded=True)
        assert sandbox.tier == "landlock"
        assert sandbox.sandbox_posture == "subprocess_only"

    @requires_landlock
    def test_write_read_inside_workspace(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path, linux_tier="landlock", allow_degraded=True)
        write = sandbox.execute("echo marker > in-ws.txt")
        assert write.exit_code == 0, write.output
        assert (tmp_path / "in-ws.txt").read_text().strip() == "marker"

    @requires_landlock
    def test_write_outside_workspace_denied(self, tmp_path: Path) -> None:
        sandbox = _sandbox(tmp_path, linux_tier="landlock", allow_degraded=True)
        response = sandbox.execute("echo x > /var/tmp/landlock-escape-probe.txt")
        assert response.exit_code != 0
        assert not Path("/var/tmp/landlock-escape-probe.txt").exists()
