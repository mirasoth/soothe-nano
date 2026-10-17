"""Unit tests for the shell toolkit's CommandExecutor seam (host + sandbox)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from soothe_deepagents.backends.protocol import ExecuteResponse

from soothe_nano.sandbox.arcbox import ArcBoxBackend, CommandRunResult
from soothe_nano.toolkits.shell import (
    BackendShellExecutor,
    HostShellExecutor,
    RunCommandShellTool,
    ShellToolkit,
    build_shell_toolkit,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeBackend:
    """Minimal sandbox backend capturing the wrapped command."""

    workspace_root = "/workspace"
    enable_capture_offload = False

    def __init__(self, response: ExecuteResponse) -> None:
        self.response = response
        self.commands: list[str] = []
        self.offload_calls: list[dict[str, Any]] = []

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self.commands.append(command)
        return self.response

    def execute_with_offload(
        self,
        command: str,
        capture_path: str,
        *,
        max_inline_bytes: int,
        timeout: int | None = None,
    ) -> Any:
        self.offload_calls.append(
            {
                "command": command,
                "capture_path": capture_path,
                "max_inline_bytes": max_inline_bytes,
                "timeout": timeout,
            }
        )

        class _Offloaded:
            def __init__(self, response: ExecuteResponse) -> None:
                self.response = response

        return _Offloaded(self.response)


class LocalGuestClient:
    """Guest simulator: real shell execution inside a temp dir (host stand-in)."""

    def __init__(self, root: Path) -> None:
        self.root = str(root)

    def run(
        self, command: str, *, cwd: str | None = None, timeout: int | None = None
    ) -> CommandRunResult:
        try:
            proc = subprocess.run(  # noqa: S602 -- test simulator, fixed inputs
                command,
                shell=True,
                cwd=cwd or self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            # SDK parity: timeout kills the process group; signal death is data.
            return CommandRunResult(stdout="", exit_code=-9, timed_out=True)
        return CommandRunResult(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)

    def read_bytes(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def write_bytes(self, path: str, data: bytes) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)


def make_guest_toolkit(tmp_path: Path) -> ShellToolkit:
    """Toolkit whose five tools execute 'in the guest' (tmp dir stand-in)."""
    backend = ArcBoxBackend(
        sandbox_id="sbx-test",
        client=LocalGuestClient(tmp_path),
        workspace_root=str(tmp_path),
    )
    return ShellToolkit(
        workspace_root=str(tmp_path),
        executor=BackendShellExecutor(backend, workspace_root=str(tmp_path)),
    )


# ---------------------------------------------------------------------------
# HostShellExecutor
# ---------------------------------------------------------------------------


class TestHostShellExecutor:
    def test_success(self) -> None:
        outcome = HostShellExecutor().run("echo hi", cwd=None, timeout=10)
        assert outcome.stdout == "hi\n"
        assert outcome.exit_code == 0
        assert not outcome.timed_out
        assert outcome.error is None

    def test_timeout_is_data(self) -> None:
        outcome = HostShellExecutor().run("sleep 5", cwd=None, timeout=1)
        assert outcome.timed_out is True
        assert outcome.exit_code is None

    def test_oserror_is_data(self) -> None:
        outcome = HostShellExecutor().run("pwd", cwd="/definitely/not/a/dir", timeout=5)
        assert outcome.error is not None
        assert outcome.exit_code is None

    def test_exit_code_passthrough(self) -> None:
        outcome = HostShellExecutor().run("exit 3", cwd=None, timeout=10)
        assert outcome.exit_code == 3


# ---------------------------------------------------------------------------
# BackendShellExecutor
# ---------------------------------------------------------------------------


class TestBackendShellExecutor:
    def test_wraps_with_guest_cwd(self) -> None:
        backend = FakeBackend(ExecuteResponse(output="hi", exit_code=0))
        outcome = BackendShellExecutor(backend).run("echo hi", cwd=None, timeout=5)
        assert backend.commands == ["cd /workspace && echo hi"]
        assert outcome.stdout == "hi"
        assert outcome.exit_code == 0
        assert not outcome.timed_out

    def test_explicit_cwd_wins(self) -> None:
        backend = FakeBackend(ExecuteResponse(output="", exit_code=0))
        BackendShellExecutor(backend).run("ls", cwd="/other", timeout=5)
        assert backend.commands == ["cd /other && ls"]

    def test_exit_124_maps_to_timed_out(self) -> None:
        backend = FakeBackend(
            ExecuteResponse(output="Command exceeded timeout of 5s", exit_code=124)
        )
        outcome = BackendShellExecutor(backend).run("sleep 9", cwd=None, timeout=5)
        assert outcome.timed_out is True

    def test_error_output_maps_to_error(self) -> None:
        backend = FakeBackend(ExecuteResponse(output="Error: sandbox died", exit_code=None))
        outcome = BackendShellExecutor(backend).run("true", cwd=None, timeout=5)
        assert outcome.error == "Error: sandbox died"
        assert outcome.exit_code is None

    def test_nonzero_exit_with_errorish_output_is_stdout(self) -> None:
        backend = FakeBackend(ExecuteResponse(output="Error: boom", exit_code=1))
        outcome = BackendShellExecutor(backend).run("cmd", cwd=None, timeout=5)
        assert outcome.error is None
        assert outcome.exit_code == 1

    def test_backend_errors_never_touch_host_subprocess(self, monkeypatch) -> None:
        """§12.1: sandbox tool errors surface as data; host shell stays untouched."""
        import soothe_nano.toolkits.shell as shell_mod

        def _no_host_shell(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("host subprocess must not run in sandbox mode")

        monkeypatch.setattr(shell_mod, "_run_shell_command_sync", _no_host_shell)
        backend = FakeBackend(ExecuteResponse(output="Error: sandbox died", exit_code=None))
        toolkit = ShellToolkit(executor=BackendShellExecutor(backend))
        tool = {t.name: t for t in toolkit.get_tools()}["run_command"]
        result = tool._run("anything")
        assert result == "Error: sandbox died"

    def test_capture_offload_route(self) -> None:
        backend = FakeBackend(ExecuteResponse(output="ok", exit_code=0))
        backend.enable_capture_offload = True
        outcome = BackendShellExecutor(backend).run("echo ok", cwd=None, timeout=5)
        call = backend.offload_calls[0]
        assert call["capture_path"].startswith("/workspace/.soothe/captures/cmd-")
        assert call["max_inline_bytes"] == 100_000
        assert call["timeout"] == 5
        assert outcome.stdout == "ok"


# ---------------------------------------------------------------------------
# Tools in guest mode (local guest simulator)
# ---------------------------------------------------------------------------


class TestRunCommandGuestMode:
    def test_executes_in_guest_root(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_command"]
        assert isinstance(tool, RunCommandShellTool)
        result = tool._run("pwd")
        assert result.strip() == str(tmp_path)

    def test_output_formatting_matches_host(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_command"]
        host_tool = RunCommandShellTool()
        guest_out = tool._run("echo hello world")
        host_out = host_tool._run("echo hello world")
        assert guest_out == host_out == "hello world"

    def test_timeout_message_matches_host_wording(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_command"]
        result = tool._run("sleep 5", 1)
        assert result.startswith("Error: Command timed out after 1s.")
        assert "use run_background" in result

    def test_nonzero_exit_output_returned_verbatim(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_command"]
        result = tool._run("echo boom >&2; exit 3")
        assert "boom" in result

    def test_host_mode_default_when_no_executor(self, tmp_path: Path) -> None:
        tool = build_shell_toolkit(workspace_root=str(tmp_path)).get_tools()[0]
        assert tool.executor is None
        (tmp_path / "host-marker.txt").write_text("host")
        assert tool._run("cat host-marker.txt") == "host"


class TestRunPythonGuestMode:
    def test_executes_via_guest_python3(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_python"]
        assert tool._run("print(1 + 1)") == "2\n"

    def test_heredoc_survives_quotes(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_python"]
        assert tool._run('print("it\'s $HOME `pwd`")') is not None

    def test_state_does_not_persist_in_guest(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_python"]
        tool._run("x = 42")
        result = tool._run("print(x)")
        assert "NameError" in result or "Error" in result

    def test_host_mode_keeps_repl(self) -> None:
        tool = build_shell_toolkit().get_tools()[1]
        assert tool.executor is None
        assert "persist" in tool.description
        assert tool._run("x = 42") == ""
        assert tool._run("print(x)") == "42\n"

    def test_guest_description_declares_no_persistence(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tool = {t.name: t for t in toolkit.get_tools()}["run_python"]
        assert "do NOT persist" in tool.description


class TestRunBackgroundGuestMode:
    def test_spawn_tail_kill_cycle(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tools = {t.name: t for t in toolkit.get_tools()}
        spawned = tools["run_background"]._run("echo bg-marker; sleep 60")
        assert spawned["pid"] is not None
        assert spawned["status"] == "running"
        log_path = Path(spawned["log_path"])
        assert log_path.is_file()
        assert ".soothe/background/bg-" in str(log_path)

        tail = tools["tail_background_log"]
        marker_seen = False
        for _ in range(50):
            tail_out = tail._run(spawned["pid"], lines=20)
            if "bg-marker" in tail_out:
                marker_seen = True
                break
            time.sleep(0.1)
        assert marker_seen, f"marker never appeared in log: {log_path}"

        kill = tools["kill_process"]
        terminated = kill._run(spawned["pid"])
        assert "terminated" in terminated or "already terminated" in terminated

        gone = kill._run(spawned["pid"])
        assert "not found or already terminated" in gone

    def test_tail_missing_log_reports_not_found(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tools = {t.name: t for t in toolkit.get_tools()}
        result = tools["tail_background_log"]._run(999999)
        assert result.startswith("Error: log file not found")

    @pytest.mark.skipif(sys.platform == "darwin", reason="needs setsid (util-linux)")
    def test_kill_reaps_guest_process_tree(self, tmp_path: Path) -> None:
        """Group kill must reap children, mirroring host killpg semantics."""
        toolkit = make_guest_toolkit(tmp_path)
        tools = {t.name: t for t in toolkit.get_tools()}
        spawned = tools["run_background"]._run("sleep 597; true")
        pid = spawned["pid"]
        time.sleep(0.5)  # let the tree form
        result = tools["kill_process"]._run(pid)
        assert "terminated" in result
        leftover = subprocess.run(  # noqa: S603 -- fixed argv
            ["pgrep", "-f", "sleep 597"],
            capture_output=True,
            timeout=10,
        )
        assert leftover.returncode != 0, "child survived the group kill"

    def test_spawn_failure_returns_error_payload(self, tmp_path: Path) -> None:
        backend = FakeBackend(ExecuteResponse(output="Error: sandbox died", exit_code=None))
        toolkit = ShellToolkit(executor=BackendShellExecutor(backend))
        tools = {t.name: t for t in toolkit.get_tools()}
        result = tools["run_background"]._run("sleep 1")
        assert result["status"] == "error"
        assert result["pid"] is None
        assert "sandbox died" in result["message"]

    def test_nonnumeric_spawn_response_rejected(self, tmp_path: Path) -> None:
        backend = FakeBackend(ExecuteResponse(output="garbage", exit_code=0))
        toolkit = ShellToolkit(executor=BackendShellExecutor(backend))
        tools = {t.name: t for t in toolkit.get_tools()}
        result = tools["run_background"]._run("sleep 1")
        assert result["status"] == "error"


class TestKillProcessGuestMode:
    def test_skips_host_protected_kill_hooks(self, tmp_path: Path) -> None:
        from soothe_nano.toolkits.shell import (
            clear_protected_kill_hooks,
            register_protected_kill_hook,
        )

        def _refuse_all(pid: int) -> str | None:
            return "Error: protected process"

        unregister = register_protected_kill_hook(_refuse_all)
        try:
            toolkit = make_guest_toolkit(tmp_path)
            tools = {t.name: t for t in toolkit.get_tools()}
            result = tools["kill_process"]._run(4194303)
            assert "protected" not in str(result)
        finally:
            unregister()
            clear_protected_kill_hooks()

    def test_invalid_pid_rejected(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tools = {t.name: t for t in toolkit.get_tools()}
        assert "invalid" in tools["kill_process"]._run(0)


class TestToolkitSurface:
    def test_guest_toolkit_names_and_order_unchanged(self, tmp_path: Path) -> None:
        host_names = [t.name for t in build_shell_toolkit().get_tools()]
        guest_names = [t.name for t in make_guest_toolkit(tmp_path).get_tools()]
        assert (
            host_names
            == guest_names
            == [
                "run_command",
                "run_python",
                "run_background",
                "tail_background_log",
                "kill_process",
            ]
        )

    def test_guest_tools_share_one_executor(self, tmp_path: Path) -> None:
        toolkit = make_guest_toolkit(tmp_path)
        tools = toolkit.get_tools()
        executors = [t.executor for t in tools]
        assert all(e is executors[0] for e in executors)
        assert executors[0].workspace_root == str(tmp_path)
