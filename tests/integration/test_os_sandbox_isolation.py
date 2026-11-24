"""Isolation-capability integration tests for the os_sandbox backend.

Executes real commands through every OS-primitive tier available on the
current host (RFC-CORE-011 §5.9): macOS Seatbelt, Linux bubblewrap+seccomp
(full tier), Linux Landlock (degraded tier, kernel >= 5.13). Tiers the host
cannot provide are skipped, never silently approximated.

Run (nano repo root)::

    uv run pytest tests/integration/test_os_sandbox_isolation.py --run-integration

Tier notes:
- ``bwrap`` runs inside a private mount namespace: host paths outside the
  bind set simply do not exist in the sandbox view (an "outside write"
  either fails on the read-only binds or lands in the private tmpfs — the
  host filesystem is untouched either way).
- ``landlock`` has no network or process isolation: network and background
  expectations are adjusted per tier and the divergence is asserted
  explicitly, not hidden.
"""

from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from soothe_nano.config.models import OsLocalSandboxConfig
from soothe_nano.sandbox.os_local import (
    OsLocalSandbox,
    _probe_bwrap,
    _probe_landlock,
)

pytestmark = pytest.mark.integration


def _available_tiers() -> list[str]:
    import shutil

    tiers: list[str] = []
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        tiers.append("seatbelt")
    if sys.platform == "linux" and _probe_bwrap():
        tiers.append("bwrap")
    if sys.platform == "linux" and _probe_landlock():
        tiers.append("landlock")
    return tiers


TIERS = _available_tiers()
"""Tiers that actually engaged on this host (probed, not assumed)."""


def _make_sandbox(tier: str, tmp_path: Path) -> OsLocalSandbox:
    kwargs: dict[str, object] = {"workspace_root": str(tmp_path)}
    if tier == "bwrap":
        kwargs["linux_tier"] = "bwrap"
    elif tier == "landlock":
        kwargs["linux_tier"] = "landlock"
        kwargs["allow_degraded"] = True
    sandbox = OsLocalSandbox(OsLocalSandboxConfig(**kwargs))
    assert sandbox.tier == tier
    return sandbox


@pytest.fixture(
    params=TIERS
    or [
        pytest.param(
            "__none__", marks=pytest.mark.skip(reason="no os_sandbox tier available on this host")
        )
    ]
)
def sandbox(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[OsLocalSandbox]:
    """One sandbox instance per (test, tier) with a fresh workspace."""
    if request.param == "__none__":
        pytest.skip("no os_sandbox tier available on this host")
    box = _make_sandbox(request.param, tmp_path)
    yield box
    box.close()


def _process_dead(pid: int, timeout: float = 3.0) -> bool:
    """True when ``pid`` is gone or an unreaped zombie (both mean: not running)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        state = proc.stdout.strip()
        if not state or state.startswith("Z"):
            return True
        time.sleep(0.1)
    return False


def _in_sandbox_python() -> str:
    """Interpreter that exists inside every tier's view of the filesystem.

    macOS narrow reads exclude ``$HOME`` (pyenv/venv interpreters) and
    ``/Applications``; homebrew and CommandLineTools interpreters live in
    the allowed read trees. Linux keeps the /usr bind.
    """
    if sys.platform == "linux":
        return "/usr/bin/python3"
    for candidate in (
        "/opt/homebrew/bin/python3",
        "/Library/Developer/CommandLineTools/usr/bin/python3",
    ):
        if os.path.exists(candidate):
            return candidate
    return "/usr/bin/python3"


class TestFilesystemBoundary:
    def test_write_inside_workspace_reaches_host(self, sandbox: OsLocalSandbox) -> None:
        response = sandbox.execute("echo marker > in-ws.txt && cat in-ws.txt")
        assert response.exit_code == 0, response.output
        host_path = Path(sandbox.workspace_root) / "in-ws.txt"
        assert host_path.read_text().strip() == "marker"

    def test_host_written_file_reaches_sandbox(self, sandbox: OsLocalSandbox) -> None:
        (Path(sandbox.workspace_root) / "from-host.txt").write_text("host-side")
        response = sandbox.execute("cat from-host.txt")
        assert response.exit_code == 0, response.output
        assert "host-side" in response.output

    def test_write_outside_workspace_never_reaches_host(
        self, sandbox: OsLocalSandbox, tmp_path: Path
    ) -> None:
        """Sandbox-external writes must not touch the host filesystem.

        seatbelt/landlock deny the write outright; bwrap diverts ``/tmp``
        into a private tmpfs (the write may "succeed" inside the sandbox
        view while the host path stays untouched — isolation via view).
        """
        sibling = tmp_path.parent / "os-sandbox-itest-sibling.txt"
        try:
            response = sandbox.execute(f"echo x > {shlex.quote(str(sibling))}")
            assert not sibling.exists()
            if sandbox.tier != "bwrap":
                assert response.exit_code != 0, response.output
        finally:
            sibling.unlink(missing_ok=True)

    def test_write_to_system_tree_denied(self, sandbox: OsLocalSandbox) -> None:
        """/etc is readable but never writable in any tier's view."""
        probe = Path("/etc/os-sandbox-itest-escape.txt")
        try:
            response = sandbox.execute(f"echo x > {shlex.quote(str(probe))}")
            assert response.exit_code != 0, response.output
        finally:
            probe.unlink(missing_ok=True)
        assert not probe.exists()

    def test_directory_creation_outside_workspace_denied(self, sandbox: OsLocalSandbox) -> None:
        probe = Path("/etc/os-sandbox-itest-dir")
        try:
            response = sandbox.execute(f"mkdir {shlex.quote(str(probe))}")
            assert response.exit_code != 0, response.output
        finally:
            if probe.exists():
                probe.rmdir()
        assert not probe.exists()

    def test_dev_null_writable(self, sandbox: OsLocalSandbox) -> None:
        response = sandbox.execute("echo x > /dev/null")
        assert response.exit_code == 0, response.output

    def test_capture_offload_works(self, sandbox: OsLocalSandbox) -> None:
        """Shell tools rely on capture offload, whose wrapper uses >/dev/null."""
        response = sandbox.execute_with_offload(
            "mkdir -p .soothe/captures && echo offload-ok > .soothe/captures/cmd.log",
            ".soothe/captures/cmd.log",
            max_inline_bytes=100_000,
        )
        assert response.response.exit_code == 0, response.response.output
        assert "Permission denied" not in response.response.output

    def test_read_outside_allow_set_denied(self, sandbox: OsLocalSandbox, tmp_path: Path) -> None:
        """Read isolation parity across tiers: a home file is unreadable.

        seatbelt denies it (EPERM), bwrap never mounts it (ENOENT), landlock
        denies it (the home tree is not in the allowed set) — every tier
        fails the read, only the failure mode differs.
        """
        home = Path.home()
        if tmp_path.is_relative_to(home) or home.is_relative_to(tmp_path):
            pytest.skip("home and workspace overlap on this host")
        probe = home / ".soothe-os-sandbox-itest-read-probe.txt"
        probe.write_text("host-secret")
        try:
            response = sandbox.execute(f"cat {shlex.quote(str(probe))}")
            assert response.exit_code != 0, response.output
            assert "host-secret" not in response.output
        finally:
            probe.unlink(missing_ok=True)


class TestNetworkBoundary:
    def test_connect_to_host_listener_blocked(self, sandbox: OsLocalSandbox) -> None:
        if sandbox.tier == "landlock":
            pytest.skip("landlock provides no network isolation (degraded tier)")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            code = (
                "import socket\n"
                "try:\n"
                f"    socket.create_connection(('127.0.0.1', {port}), timeout=3)\n"
                "    print('CONNECTED')\n"
                "except OSError as exc:\n"
                "    print('BLOCKED', type(exc).__name__, exc)\n"
            )
            response = sandbox.execute(
                f"{shlex.quote(_in_sandbox_python())} -c {shlex.quote(code)}"
            )
            assert "CONNECTED" not in response.output, response.output
            assert "BLOCKED" in response.output, response.output
        finally:
            listener.close()


class TestEnvHygiene:
    def test_env_secret_never_crosses(
        self, sandbox: OsLocalSandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOOTHE_SANDBOX_ITEST_SECRET", "sentinel-9f3a")
        response = sandbox.execute('echo "secret=${SOOTHE_SANDBOX_ITEST_SECRET:-absent}"')
        assert "absent" in response.output, response.output
        assert "sentinel-9f3a" not in response.output

    def test_home_is_workspace_and_tmpdir_is_scratch(self, sandbox: OsLocalSandbox) -> None:
        home = sandbox.execute("echo $HOME").output.strip()
        tmpdir = sandbox.execute("echo $TMPDIR").output.strip()
        assert home == sandbox.workspace_root
        assert tmpdir == sandbox._scratch
        assert Path(tmpdir).is_dir()

    def test_cwd_is_workspace(self, sandbox: OsLocalSandbox) -> None:
        response = sandbox.execute("pwd")
        assert response.exit_code == 0, response.output
        assert response.output.strip() == sandbox.workspace_root


class TestProcessLifecycle:
    def test_timeout_kills_whole_process_group(
        self, sandbox: OsLocalSandbox, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "bg.pid"
        command = f"sleep 300 & echo $! > {shlex.quote(str(pid_file))}; wait"
        response = sandbox.execute(command, timeout=2)
        assert response.exit_code == 124, response.output
        assert "exceeded timeout of 2s" in response.output
        child_pid = int(pid_file.read_text().strip())
        # The background child shares the killed process group.
        assert _process_dead(child_pid), f"child {child_pid} survived the group kill"

    def test_background_pid_is_host_visible_and_killable(
        self, sandbox: OsLocalSandbox, tmp_path: Path
    ) -> None:
        """Identity PID mapping: sandboxed background PIDs are host PIDs.

        RFC-CORE-011 §5.3: no PID namespace unshare — ``kill_process`` and
        ``tail_background_log`` semantics are identical to host mode.
        """
        pid_file = tmp_path / "bg.pid"
        command = f"nohup sleep 300 >/dev/null 2>&1 & echo $! > {shlex.quote(str(pid_file))}"
        response = sandbox.execute(command)
        assert response.exit_code == 0, response.output
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)  # alive and visible from the host process
        except ProcessLookupError:
            pytest.fail(f"background pid {pid} is not host-visible (tier={sandbox.tier})")
        os.kill(pid, signal.SIGKILL)
        assert _process_dead(pid)

    def test_close_kills_background_process_groups(
        self, sandbox: OsLocalSandbox, tmp_path: Path
    ) -> None:
        """P2: groups that outlive their command die when the sandbox closes."""
        pid_file = tmp_path / "bg.pid"
        command = f"nohup sleep 300 >/dev/null 2>&1 & echo $! > {shlex.quote(str(pid_file))}"
        response = sandbox.execute(command)
        assert response.exit_code == 0, response.output
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # alive while the sandbox is open
        sandbox.close()
        assert _process_dead(pid), f"background pid {pid} survived close (tier={sandbox.tier})"

    def test_unbounded_output_capped_and_killed(self, sandbox: OsLocalSandbox) -> None:
        """P0: an unbounded writer is capped, killed, and flagged."""
        code = "import sys; sys.stdout.write('x' * 20_000_000)"
        response = sandbox.execute(
            f"{shlex.quote(_in_sandbox_python())} -c {shlex.quote(code)}", timeout=60
        )
        assert "truncated" in response.output, response.output[-200:]
        assert "process group was killed" in response.output, response.output[-200:]
        # far below the 20 MB the writer attempted
        assert len(response.output) < 20_000_000


class TestPathEscape:
    def test_upload_download_escape_rejected(self, sandbox: OsLocalSandbox) -> None:
        for escape in ("/etc/os-sandbox-itest-escape.txt", "../escape.txt", "relative.txt"):
            assert sandbox.upload_files([(escape, b"x")])[0].error is not None, escape
            assert sandbox.download_files([escape])[0].error is not None, escape

    def test_symlink_escape_rejected(self, sandbox: OsLocalSandbox, tmp_path: Path) -> None:
        outside = tmp_path.parent / "os-sandbox-itest-symlink-target.txt"
        outside.write_text("outside")
        try:
            link = tmp_path / "escape-link"
            link.symlink_to(outside)
            assert sandbox.download_files([str(link)])[0].error is not None
            assert sandbox.upload_files([(str(link), b"x")])[0].error is not None
            assert outside.read_text() == "outside"  # untouched
        finally:
            outside.unlink(missing_ok=True)


class TestKernelFilters:
    """bwrap full tier: the in-namespace launcher's kernel hardening is live."""

    def test_no_new_privs_and_seccomp_active(self, sandbox: OsLocalSandbox) -> None:
        if sandbox.tier != "bwrap":
            pytest.skip("kernel-filter assertions apply to the bwrap full tier only")
        response = sandbox.execute("grep -E 'NoNewPrivs|Seccomp' /proc/self/status")
        assert response.exit_code == 0, response.output
        assert "NoNewPrivs:" in response.output
        assert "1" in response.output.split("NoNewPrivs:")[1].split()[0]
        assert "Seccomp:" in response.output
        assert "2" in response.output.split("Seccomp:")[1].split()[0]

    def test_namespace_escape_syscall_denied(self, sandbox: OsLocalSandbox) -> None:
        if sandbox.tier != "bwrap":
            pytest.skip("seccomp deny-list assertions apply to the bwrap full tier only")
        code = (
            "import ctypes\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "r = libc.unshare(0x00040000)\n"
            "print('unshare rc=%d errno=%d' % (r, ctypes.get_errno()))\n"
        )
        response = sandbox.execute(f"{shlex.quote(_in_sandbox_python())} -c {shlex.quote(code)}")
        assert "rc=0" not in response.output, response.output
        # Denied syscalls surface as ENOSYS(38) from the filter, or EPERM(1)
        # from the kernel if the userns policy rejects first.
        assert "errno=38" in response.output or "errno=1" in response.output, response.output


class TestPosture:
    def test_tier_reports_expected_posture(self, sandbox: OsLocalSandbox) -> None:
        expected = "subprocess_only" if sandbox.tier == "landlock" else "full"
        assert sandbox.sandbox_posture == expected

    def test_capability_probe_made_a_real_decision(self) -> None:
        """The tier list is probe-derived, not hardcoded per platform."""
        if sys.platform == "darwin":
            assert "seatbelt" in TIERS
        if sys.platform == "linux":
            assert "bwrap" in TIERS or "landlock" in TIERS or TIERS == []
