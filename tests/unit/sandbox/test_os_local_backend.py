"""Unit tests for the os_sandbox local OS-primitive backend (no real exec)."""

from __future__ import annotations

import io
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from soothe_nano.config.models import OsLocalSandboxConfig
from soothe_nano.sandbox import os_local
from soothe_nano.sandbox.os_local import (
    OsLocalSandbox,
    OsSandboxConfigError,
    _build_seccomp_bpf,
    _BwrapSession,
    _LandlockSession,
    _posture_for_tier,
    _SeatbeltSession,
)


class FakePopen:
    """Recording Popen double for execute-semantics tests."""

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.stdout = io.BytesIO(b"out")
        self.stderr = io.BytesIO(b"err")
        # sentinel pid beyond any real pid_max: tracking/kill probes can
        # never hit a live process group
        self.pid = 999_999_904
        self.waits: list[int | None] = []
        self.timeout_at: int | None = None
        self.killed = False
        self.returncode = 0

    def wait(self, timeout: int | None = None) -> int:
        self.waits.append(timeout)
        # Only the first, timed wait raises — the post-kill wait
        # must succeed for the 124 contract.
        if (
            timeout is not None
            and self.timeout_at is not None
            and len(self.waits) >= self.timeout_at
        ):
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode

    def kill(self) -> None:  # pragma: no cover - only reached via killpg override
        self.killed = True


def make_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    **cfg_kwargs: Any,
) -> OsLocalSandbox:
    monkeypatch.setattr(os_local, "_probe_bwrap", lambda: True)
    monkeypatch.setattr(os_local, "_probe_landlock", lambda: True)
    cfg = OsLocalSandboxConfig(workspace_root=str(tmp_path), **cfg_kwargs)
    return OsLocalSandbox(cfg)


class TestBuildSeccompBpf:
    def test_layout_and_jump_targets(self) -> None:
        arch = 0xC000003E
        denied = (272, 308, 435)
        raw = _build_seccomp_bpf(arch, denied)
        assert len(raw) % 8 == 0
        ins = [struct.unpack("<HBBI", raw[i : i + 8]) for i in range(0, len(raw), 8)]
        # [LD arch][JEQ arch][LD nr][JEQ nr]*[RET allow][RET errno]
        assert len(ins) == 3 + len(denied) + 2
        assert ins[0][0] == 0x20 and ins[0][3] == 4  # LD W ABS arch
        assert ins[1][0] == 0x15 and ins[1][3] == arch
        assert ins[2][0] == 0x20 and ins[2][3] == 0  # LD W ABS nr
        allow_idx = 3 + len(denied)
        deny_idx = allow_idx + 1
        # arch mismatch jumps to the deny ret
        assert ins[1][2] == deny_idx - 2  # jf offset from instruction 1
        for i, nr in enumerate(denied):
            assert ins[3 + i][3] == nr
            assert ins[3 + i][0] == 0x15
            assert ins[3 + i][1] == deny_idx - (3 + i) - 1  # jt offset to deny
        assert ins[allow_idx][0] == 0x06 and ins[allow_idx][3] == 0x7FFF0000
        assert ins[deny_idx][0] == 0x06
        assert ins[deny_idx][3] == 0x00050000 | 38  # ERRNO | ENOSYS

    def test_empty_deny_list_still_blocks_unknown_archs(self) -> None:
        raw = _build_seccomp_bpf(0xC00000B7, ())
        ins = [struct.unpack("<HBBI", raw[i : i + 8]) for i in range(0, len(raw), 8)]
        assert len(ins) == 5
        # allow at idx 3, deny at idx 4
        assert ins[3][3] == 0x7FFF0000
        assert ins[4][3] == 0x00050000 | 38


class TestDenyTables:
    def test_numbers_unique_per_arch(self) -> None:
        for numbers in os_local._SECCOMP_DENY_SYSCALLS.values():
            assert len(numbers) == len(set(numbers))

    def test_namespace_escapes_denied_on_both_arches(self) -> None:
        # unshare / setns / mount / pivot_root / ptrace / clone3
        x86 = set(os_local._SECCOMP_DENY_SYSCALLS["x86_64"])
        arm = set(os_local._SECCOMP_DENY_SYSCALLS["aarch64"])
        assert 272 in x86 and 97 in arm  # unshare
        assert 308 in x86 and 268 in arm  # setns
        assert 165 in x86 and 40 in arm  # mount
        assert 155 in x86 and 41 in arm  # pivot_root
        assert 101 in x86 and 117 in arm  # ptrace
        assert 435 in x86 and 435 in arm  # clone3

    def test_seccomp_nr_and_audit_arch_covered(self) -> None:
        assert set(os_local._SECCOMP_NR) == {"x86_64", "aarch64"}
        assert set(os_local._AUDIT_ARCH) == {"x86_64", "aarch64"}


class TestLauncherSources:
    def test_seccomp_launcher_sets_no_new_privs_before_filter(self) -> None:
        source = os_local._LAUNCHER_SECCOMP
        prctl_pos = source.index("prctl")
        seccomp_pos = source.index("syscall(")
        assert prctl_pos < seccomp_pos
        assert "NO_NEW_PRIVS" in source
        assert "execvp" in source

    def test_landlock_launcher_restricts_self_before_exec(self) -> None:
        source = os_local._LAUNCHER_LANDLOCK
        assert source.index("444") < source.index("445") < source.index("446")
        assert "prctl" in source
        assert "execvp" in source


class TestSeatbeltProfile:
    def test_profile_shape(self, tmp_path: Path) -> None:
        session = _SeatbeltSession(tmp_path.resolve(), Path("/private/tmp/scratch"))
        profile = session._profile
        assert "(deny default)" in profile
        assert f'(subpath "{tmp_path.resolve()}")' in profile
        assert '(subpath "/private/tmp/scratch")' in profile
        assert '(literal "/dev/null")' in profile

    def test_reads_are_narrow_bwrap_parity(self, tmp_path: Path) -> None:
        """Read isolation parity with the bwrap bind set (no broad reads)."""
        session = _SeatbeltSession(tmp_path.resolve(), Path("/private/tmp/scratch"))
        profile = session._profile
        # no broad read allowance (a bare "(allow file-read*)" would match every path)
        assert "(allow file-read*)" not in profile
        for tree in os_local._SEATBELT_READ_TREES:
            assert f'(subpath "{tree}")' in profile, tree
        # workspace + scratch appear in the narrowed read line (derived reads need it)
        read_line = next(
            line for line in profile.splitlines() if line.startswith("(allow file-read*")
        )
        assert f'(subpath "{tmp_path.resolve()}")' in read_line
        assert '(subpath "/private/tmp/scratch")' in read_line
        # entropy devices readable (interpreter startup)
        assert '(literal "/dev/urandom")' in profile

    def test_metadata_roots_and_ancestors_are_literal(self, tmp_path: Path) -> None:
        session = _SeatbeltSession(tmp_path.resolve(), Path("/private/tmp/scratch"))
        profile = session._profile
        metadata_line = next(
            line for line in profile.splitlines() if line.startswith("(allow file-read-metadata")
        )
        for root in os_local._SEATBELT_METADATA_ROOTS:
            assert f'(literal "{root}")' in metadata_line, root
        # every ws/scratch ancestor gets a metadata literal (git lstats the cwd chain)
        for ancestor in os_local._seatbelt_ancestors(str(tmp_path.resolve())):
            assert f'(literal "{ancestor}")' in metadata_line, ancestor

    def test_profile_quotes_paths(self, tmp_path: Path) -> None:
        quoted = tmp_path / 'we"ird'
        quoted.mkdir()
        session = _SeatbeltSession(quoted, Path("/private/tmp/scratch"))
        assert 'we\\"ird' in session._profile  # quote escaped, profile still parses

    def test_build_argv(self, tmp_path: Path) -> None:
        session = _SeatbeltSession(tmp_path.resolve(), Path("/private/tmp/scratch"))
        argv = session.build_argv("echo hi")
        assert argv[0] == "sandbox-exec"
        assert argv[1] == "-p"
        assert argv[2] is session._profile
        assert argv[3:] == ["/bin/sh", "-c", "echo hi"]


class TestBwrapArgv:
    def test_argv_shape(self, tmp_path: Path) -> None:
        ws = tmp_path.resolve()
        session = _BwrapSession(ws, ws / "scratch")
        argv = session.build_argv("echo hi")
        assert argv[0] == "bwrap"
        joined = " ".join(argv)
        assert f"--bind {ws} {ws}" in joined  # identity bind
        assert "--die-with-parent" in argv
        # no inner setsid: sandboxed children stay in the Popen session so
        # close()/timeout killpg reaches them (start_new_session already
        # detaches the tree from the host terminal session)
        assert "--new-session" not in argv
        assert "--unshare-net" in argv
        assert "--unshare-pid" not in argv  # background PIDs stay host-visible
        assert "--clearenv" not in argv  # env applied at Popen, not bwrap
        # launcher wiring: <interp> -c LAUNCHER <bpf_hex> <seccomp_nr> -- /bin/sh -c cmd
        launcher_idx = argv.index("-c") + 1
        assert argv[launcher_idx] is os_local._LAUNCHER_SECCOMP
        bpf_hex = argv[launcher_idx + 1]
        seccomp_nr = argv[launcher_idx + 2]
        assert seccomp_nr == str(os_local._SECCOMP_NR[session._arch])
        assert bytes.fromhex(bpf_hex) == session._bpf
        assert argv[launcher_idx + 3] == "--"
        assert argv[launcher_idx + 4 :] == ["/bin/sh", "-c", "echo hi"]

    def test_read_only_system_binds(self, tmp_path: Path) -> None:
        ws = tmp_path.resolve()
        argv = _BwrapSession(ws, ws / "scratch").build_argv("true")
        assert "--ro-bind" in argv
        assert "/usr" in argv
        # /tmp is a private tmpfs, not the host one
        tmpfs_idx = argv.index("--tmpfs")
        assert argv[tmpfs_idx + 1] == "/tmp"
        # direct spawn mounts a fresh proc
        proc_idx = argv.index("--proc")
        assert argv[proc_idx + 1] == "/proc"

    def test_nested_spawn_prefix_wraps_bwrap_and_ro_binds_proc(self, tmp_path: Path) -> None:
        ws = tmp_path.resolve()
        prefix = ["unshare", "--user", "--map-root-user"]
        session = _BwrapSession(ws, ws / "scratch", spawn_prefix=prefix)
        argv = session.build_argv("true")
        assert argv[:3] == prefix
        assert argv[3] == "bwrap"
        bwrap_args = argv[3:]
        assert "--proc" not in bwrap_args  # bwrap < 0.5 cannot mount proc in a userns
        ro_proc = ["--ro-bind-try", "/proc", "/proc"]
        assert any(bwrap_args[i : i + 3] == ro_proc for i in range(len(bwrap_args) - 2))


class TestBwrapSpawnPrefix:
    """Root-in-container detection: direct first, userns wrapper fallback."""

    def test_non_root_uses_direct_without_probing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os_local.os, "geteuid", lambda: 1000)
        monkeypatch.setattr(
            os_local,
            "_bwrap_roundtrip",
            lambda *a, **k: pytest.fail("non-root must never probe"),
        )
        monkeypatch.setattr(os_local, "_BWRAP_SPAWN_PREFIX", None)
        assert os_local._bwrap_spawn_prefix() == []

    def test_root_direct_failure_falls_back_to_nested(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[object, ...]] = []

        def _fake_roundtrip(prefix: object, proc_args: object) -> bool:
            calls.append((tuple(prefix), tuple(proc_args)))  # type: ignore[arg-type]
            return len(tuple(prefix)) > 0  # direct fails, nested succeeds

        monkeypatch.setattr(os_local.os, "geteuid", lambda: 0)
        monkeypatch.setattr(os_local, "_bwrap_roundtrip", _fake_roundtrip)
        monkeypatch.setattr(os_local, "_BWRAP_SPAWN_PREFIX", None)
        assert os_local._bwrap_spawn_prefix() == ["unshare", "--user", "--map-root-user"]
        # direct attempt used the fresh-proc form; nested used the ro-bind form
        assert calls[0] == ((), ("--proc", "/proc"))
        assert calls[1][0] == ("unshare", "--user", "--map-root-user")

    def test_nested_failure_keeps_empty_prefix_and_probe_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os_local.os, "geteuid", lambda: 0)
        monkeypatch.setattr(os_local, "_bwrap_roundtrip", lambda *a, **k: False)
        monkeypatch.setattr(os_local, "_BWRAP_SPAWN_PREFIX", None)
        assert os_local._bwrap_spawn_prefix() == []
        assert os_local._probe_bwrap() is False

    def test_probe_uses_the_resolved_spawn_form(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os_local, "_bwrap_spawn_prefix", lambda: ["unshare", "--user"])
        monkeypatch.setattr(
            os_local,
            "_bwrap_roundtrip",
            lambda prefix, proc_args: (
                tuple(prefix) == ("unshare", "--user")
                and tuple(proc_args) == ("--ro-bind-try", "/proc", "/proc")
            ),
        )
        assert os_local._probe_bwrap() is True


class TestLandlockArgv:
    def test_argv_shape(self, tmp_path: Path) -> None:
        ws = tmp_path.resolve()
        scratch = ws / "scratch"
        argv = _LandlockSession(ws, scratch).build_argv("echo hi")
        assert argv[:3] == [sys.executable, "-c", os_local._LAUNCHER_LANDLOCK]
        assert argv[3:5] == [str(ws), str(scratch)]
        assert argv[5] == "--"
        assert argv[6:] == ["/bin/sh", "-c", "echo hi"]


class TestEnvAllowlist:
    def test_only_allowlisted_keys_cross(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("SECRET_TOKEN", "leak-me")
        monkeypatch.setenv("API_KEY_SENTINEL", "leak-me-too")
        backend = make_backend(monkeypatch, tmp_path)
        env = backend._build_child_env()
        assert env["PATH"] == "/usr/bin"
        assert "SECRET_TOKEN" not in env
        assert "API_KEY_SENTINEL" not in env

    def test_home_and_tmpdir_overridden(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/someone")
        backend = make_backend(monkeypatch, tmp_path)
        env = backend._build_child_env()
        assert env["HOME"] == str(tmp_path.resolve())
        assert env["TMPDIR"] == backend._scratch

    def test_custom_allowlist(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("CUSTOM_VAR", "x")
        backend = make_backend(monkeypatch, tmp_path, env_allowlist=["CUSTOM_VAR"])
        env = backend._build_child_env()
        assert env["CUSTOM_VAR"] == "x"
        assert "PATH" not in env


class TestBindWorkspace:
    def test_bind_resolves_and_sets_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        assert backend.workspace_root == str(tmp_path.resolve())

    def test_rebind_same_root_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        backend.bind_workspace(str(tmp_path))

    def test_rebind_different_root_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(OsSandboxConfigError, match="refusing rebind"):
            backend.bind_workspace(str(other))

    def test_bind_non_directory_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        target = tmp_path / "file.txt"
        target.write_text("x")
        with pytest.raises(OsSandboxConfigError, match="not a directory"):
            backend.bind_workspace(str(target))

    def test_execute_before_binding_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(os_local, "_probe_bwrap", lambda: True)
        backend = OsLocalSandbox(OsLocalSandboxConfig())
        with pytest.raises(OsSandboxConfigError, match="not bound"):
            backend.execute("true")


class TestPathResolution:
    def test_relative_path_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        assert backend._resolve_in_sandbox("relative.txt") is None

    def test_outside_path_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        assert backend._resolve_in_sandbox("/etc/hosts") is None

    def test_symlink_escape_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        escape = tmp_path.parent / "soothe-escape-target.txt"
        escape.write_text("secret")
        try:
            (tmp_path / "escape-link").symlink_to(escape)
            assert backend._resolve_in_sandbox(str(tmp_path / "escape-link")) is None
        finally:
            escape.unlink(missing_ok=True)

    def test_in_workspace_path_resolved(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        assert backend._resolve_in_sandbox(str(tmp_path / "a.txt")) == tmp_path.resolve() / "a.txt"

    def test_upload_download_roundtrip(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        ups = backend.upload_files([(str(tmp_path / "nested" / "new.txt"), b"payload")])
        assert ups[0].error is None
        downs = backend.download_files([str(tmp_path / "nested" / "new.txt")])
        assert downs[0].content == b"payload"
        assert downs[0].error is None

    def test_upload_escape_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        ups = backend.upload_files([("/etc/soothe-escape", b"x")])
        assert ups[0].error is not None
        assert not Path("/etc/soothe-escape").exists()

    def test_download_missing_and_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        (tmp_path / "dir").mkdir()
        downs = backend.download_files([str(tmp_path / "missing.txt"), str(tmp_path / "dir")])
        assert downs[0].error is not None
        assert downs[1].error is not None


class TestPosture:
    def test_landlock_is_degraded(self) -> None:
        assert _posture_for_tier("landlock") == "subprocess_only"

    def test_full_tiers_report_full(self) -> None:
        assert _posture_for_tier("seatbelt") == "full"
        assert _posture_for_tier("bwrap") == "full"


class TestExecuteSemantics:
    def _make_with_popen(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake: FakePopen
    ) -> OsLocalSandbox:
        monkeypatch.setattr(os_local, "_probe_bwrap", lambda: True)
        # fake pids must never touch real process groups
        monkeypatch.setattr(os_local, "_pgid_alive", lambda pgid: False)
        monkeypatch.setattr(os_local, "_kill_pgid", lambda pgid: None)

        def _popen(argv: list[str], **kwargs: Any) -> FakePopen:
            fake.argv = argv
            fake.kwargs = kwargs
            return fake

        cfg = OsLocalSandboxConfig(workspace_root=str(tmp_path))
        return OsLocalSandbox(cfg, popen=_popen)

    def test_env_and_cwd_forwarded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        fake = FakePopen([])
        backend = self._make_with_popen(monkeypatch, tmp_path, fake)
        response = backend.execute("true")
        assert response.exit_code == 0
        assert response.output == "out\nerr"
        assert fake.kwargs["cwd"] == str(tmp_path.resolve())
        assert fake.kwargs["env"]["HOME"] == str(tmp_path.resolve())
        assert fake.kwargs["start_new_session"] is True
        # binary pipes: bounded readers decode, they do not rely on text mode
        assert "text" not in fake.kwargs

    def test_timeout_uses_exit_code_124_convention(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakePopen([])
        fake.timeout_at = 1
        monkeypatch.setattr(
            os_local, "_kill_process_group", lambda proc: setattr(proc, "killed", True)
        )
        backend = self._make_with_popen(monkeypatch, tmp_path, fake)
        response = backend.execute("sleep 99", timeout=7)
        assert response.exit_code == 124
        assert "exceeded timeout of 7s" in response.output
        assert fake.killed is True

    def test_default_timeout_forwarded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake = FakePopen([])
        backend = self._make_with_popen(monkeypatch, tmp_path, fake)
        backend.execute("true")
        assert fake.waits == [120]

    def test_output_capped_with_truncation_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """P0: an unbounded writer is capped, killed, and flagged."""
        monkeypatch.setattr(os_local, "_EXECUTE_CAPTURE_CAP_BYTES", 8)
        fake = FakePopen([])
        fake.stdout = io.BytesIO(b"x" * 20)
        backend = self._make_with_popen(monkeypatch, tmp_path, fake)
        kills: list[int] = []
        monkeypatch.setattr(os_local, "_kill_pgid", lambda pgid: kills.append(pgid))
        response = backend.execute("cat /dev/zero")
        stdout_only = response.output.split("\n")[0]
        assert len(stdout_only) <= 8
        assert stdout_only == "x" * 8
        assert "truncated" in response.output
        assert "process group was killed" in response.output
        assert kills == [fake.pid]  # the reader kills the group on cap

    def test_popen_oserror_as_error_data(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise OSError("no bwrap binary")

        monkeypatch.setattr(os_local, "_probe_bwrap", lambda: True)
        cfg = OsLocalSandboxConfig(workspace_root=str(tmp_path))
        backend = OsLocalSandbox(cfg, popen=_boom)
        response = backend.execute("true")
        assert response.exit_code is None
        assert response.output.startswith("Error:")


class TestFactory:
    def test_os_sandbox_dispatch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from soothe_nano.config.models import SandboxBackendConfig
        from soothe_nano.sandbox import create_sandbox_backend

        monkeypatch.setattr(os_local, "_probe_bwrap", lambda: True)
        config = SandboxBackendConfig(
            type="os_sandbox", os_sandbox=OsLocalSandboxConfig(workspace_root=str(tmp_path))
        )
        backend = create_sandbox_backend(config)
        assert isinstance(backend, OsLocalSandbox)
        assert backend.workspace_root == str(tmp_path.resolve())

    def test_missing_subconfig_rejected(self) -> None:
        from soothe_nano.config.models import SandboxBackendConfig
        from soothe_nano.sandbox import create_sandbox_backend

        with pytest.raises(ValueError, match="requires sandbox.backend.os_sandbox"):
            create_sandbox_backend(SandboxBackendConfig(type="os_sandbox"))

    def test_capability_error_propagates_from_factory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from soothe_nano.config.models import SandboxBackendConfig
        from soothe_nano.sandbox import create_sandbox_backend

        monkeypatch.setattr(os_local, "_probe_bwrap", lambda: False)
        monkeypatch.setattr(os_local, "_probe_landlock", lambda: False)
        if sys.platform == "darwin":
            pytest.skip("darwin always resolves the seatbelt tier")
        config = SandboxBackendConfig(
            type="os_sandbox", os_sandbox=OsLocalSandboxConfig(workspace_root=str(tmp_path))
        )
        with pytest.raises(os_local.OsSandboxCapabilityError):
            create_sandbox_backend(config)


class TestClose:
    def test_close_is_idempotent(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        backend = make_backend(monkeypatch, tmp_path)
        scratch = backend._scratch
        assert Path(scratch).is_dir()
        backend.close()
        assert not Path(scratch).exists()
        assert backend._scratch == ""
        backend.close()  # no raise

    def test_close_kills_live_process_groups(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """P2: background groups that outlived their command die on close."""
        backend = make_backend(monkeypatch, tmp_path)
        kills: list[int] = []
        monkeypatch.setattr(os_local, "_kill_pgid", lambda pgid: kills.append(pgid))
        monkeypatch.setattr(os_local, "_pgid_alive", lambda pgid: True)
        # sentinel pgids beyond any real pid_max: a leaked entry can never
        # hit a live process group
        pgid_a, pgid_b = 999_999_901, 999_999_902
        backend._track_pgid(pgid_a)
        backend._track_pgid(pgid_b)
        assert {pgid_a, pgid_b} <= os_local._pgid_registry
        backend.close()
        assert sorted(kills) == [pgid_a, pgid_b]
        assert backend._pgids == set()
        assert pgid_a not in os_local._pgid_registry and pgid_b not in os_local._pgid_registry

    def test_reap_keeps_groups_with_live_members(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A group that still has background members stays tracked (P2)."""
        backend = make_backend(monkeypatch, tmp_path)
        pgid = 999_999_903
        monkeypatch.setattr(os_local, "_pgid_alive", lambda pgid: True)
        backend._track_pgid(pgid)
        backend._reap_pgid(pgid)  # command exited, group still alive
        assert pgid in backend._pgids
        monkeypatch.setattr(os_local, "_pgid_alive", lambda pgid: False)
        backend._reap_pgid(pgid)  # last member gone
        assert pgid not in backend._pgids


class TestBoundedReader:
    def test_read_bounded_caps_and_flags(self) -> None:
        pipe = io.BytesIO(b"x" * 100)
        data, truncated = os_local._read_bounded(pipe, 40)
        assert data == b"x" * 40
        assert truncated is True

    def test_read_bounded_small_stream_not_truncated(self) -> None:
        pipe = io.BytesIO(b"hello")
        data, truncated = os_local._read_bounded(pipe, 40)
        assert data == b"hello"
        assert truncated is False

    def test_read_bounded_exact_cap_is_truncated(self) -> None:
        pipe = io.BytesIO(b"x" * 40)
        data, truncated = os_local._read_bounded(pipe, 40)
        assert data == b"x" * 40
        assert truncated is True

    def test_capture_cap_exceeds_guest_offload_window(self) -> None:
        """The backend cap must never clip the 10 MiB guest-side offload."""
        from soothe_deepagents.backends import sandbox as _sd_sandbox

        assert os_local._EXECUTE_CAPTURE_CAP_BYTES > _sd_sandbox._EXECUTE_CAPTURE_MAX_BYTES
