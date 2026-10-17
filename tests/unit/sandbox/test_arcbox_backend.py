"""Unit tests for the ArcBox sandbox backend (no daemon, no SDK)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from soothe_nano.sandbox.arcbox import (
    ArcBoxBackend,
    ArcBoxError,
    ArcBoxFileNotFoundError,
    ArcBoxIsDirectoryError,
    CommandRunResult,
)


class FakeClient:
    """Scriptable ``ArcBoxClient`` returning canned ``CommandRunResult``s."""

    def __init__(self, result: CommandRunResult) -> None:
        self.result = result
        self.run_calls: list[dict[str, Any]] = []

    def run(
        self, command: str, *, cwd: str | None = None, timeout: int | None = None
    ) -> CommandRunResult:
        self.run_calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return self.result

    def read_bytes(self, path: str) -> bytes:
        raise ArcBoxFileNotFoundError(path)

    def write_bytes(self, path: str, data: bytes) -> None:
        raise ArcBoxError(f"write failed: {path}")


class LocalGuestClient:
    """Guest simulator: real ``sh``/``python3`` execution inside a temp root.

    Implements the ``ArcBoxClient`` seam over a local subprocess so the
    ``BaseSandbox``-derived file operations are exercised end-to-end.
    """

    def __init__(self, root: Path) -> None:
        self.root = str(root)

    def run(
        self, command: str, *, cwd: str | None = None, timeout: int | None = None
    ) -> CommandRunResult:
        proc = subprocess.run(  # noqa: S602 -- test simulator, fixed inputs
            command,
            shell=True,
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandRunResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )

    def read_bytes(self, path: str) -> bytes:
        target = Path(path)
        if not target.exists():
            raise ArcBoxFileNotFoundError(path)
        if target.is_dir():
            raise ArcBoxIsDirectoryError(path)
        return target.read_bytes()

    def write_bytes(self, path: str, data: bytes) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def make_backend(client: Any, workspace_root: str = "/workspace") -> ArcBoxBackend:
    return ArcBoxBackend(sandbox_id="sbx-test", client=client, workspace_root=workspace_root)


class TestExecuteMapping:
    def test_merges_stdout_stderr(self) -> None:
        client = FakeClient(CommandRunResult(stdout="out", stderr="err", exit_code=0))
        response = make_backend(client).execute("true")
        assert response.output == "out\nerr"
        assert response.exit_code == 0
        assert response.truncated is False

    def test_stdout_only_has_no_seam(self) -> None:
        client = FakeClient(CommandRunResult(stdout="out", exit_code=1))
        response = make_backend(client).execute("false")
        assert response.output == "out"
        assert response.exit_code == 1

    def test_error_as_data(self) -> None:
        client = FakeClient(CommandRunResult(error="ArcBox command failed: dead sandbox"))
        response = make_backend(client).execute("true")
        assert response.output == "Error: ArcBox command failed: dead sandbox"
        assert response.exit_code is None

    def test_timeout_uses_exit_code_124_convention(self) -> None:
        client = FakeClient(CommandRunResult(stdout="partial", exit_code=-9, timed_out=True))
        response = make_backend(client, workspace_root="/ws").execute("sleep 99", timeout=7)
        assert response.exit_code == 124
        assert "partial" in response.output
        assert "exceeded timeout of 7s" in response.output

    def test_truncated_note_appended(self) -> None:
        client = FakeClient(CommandRunResult(stdout="big", exit_code=0, truncated=True))
        response = make_backend(client).execute("yes")
        assert response.truncated is True
        assert response.output.endswith("... (output truncated)")

    def test_default_timeout_and_cwd_forwarded(self) -> None:
        client = FakeClient(CommandRunResult(stdout="", exit_code=0))
        backend = make_backend(client, workspace_root="/ws")
        backend.execute("pwd")
        call = client.run_calls[0]
        assert call["cwd"] == "/ws"
        assert call["timeout"] == backend.default_timeout

        backend.execute("pwd", timeout=9)
        assert client.run_calls[1]["timeout"] == 9


class TestUploadDownload:
    def test_upload_and_download_roundtrip(self, tmp_path: Path) -> None:
        backend = make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))
        uploads = backend.upload_files([(str(tmp_path / "a.txt"), b"alpha")])
        assert uploads[0].error is None

        downloads = backend.download_files([str(tmp_path / "a.txt")])
        assert downloads[0].error is None
        assert downloads[0].content == b"alpha"

    def test_upload_creates_parent_dirs(self, tmp_path: Path) -> None:
        backend = make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))
        deep = tmp_path / "nested" / "dir" / "file.txt"
        response = backend.upload_files([(str(deep), b"x")])
        assert response[0].error is None
        assert deep.read_bytes() == b"x"

    def test_relative_path_is_invalid(self, tmp_path: Path) -> None:
        from soothe_deepagents.backends.protocol import INVALID_PATH

        backend = make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))
        assert backend.upload_files([("relative.txt", b"x")])[0].error == INVALID_PATH
        assert backend.download_files(["relative.txt"])[0].error == INVALID_PATH

    def test_download_missing_file_maps_not_found(self, tmp_path: Path) -> None:
        from soothe_deepagents.backends.protocol import FILE_NOT_FOUND

        backend = make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))
        assert backend.download_files([str(tmp_path / "nope.txt")])[0].error == FILE_NOT_FOUND

    def test_download_directory_maps_is_directory(self, tmp_path: Path) -> None:
        from soothe_deepagents.backends.protocol import IS_DIRECTORY

        backend = make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))
        assert backend.download_files([str(tmp_path)])[0].error == IS_DIRECTORY

    def test_upload_error_is_data(self) -> None:
        client = FakeClient(CommandRunResult())
        backend = make_backend(client, workspace_root="/ws")
        response = backend.upload_files([("/ws/x.txt", b"x")])
        assert response[0].error is not None


class TestBaseSandboxContract:
    """File operations derived by ``BaseSandbox`` from guest ``execute``."""

    @staticmethod
    def backend(tmp_path: Path) -> ArcBoxBackend:
        return make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))

    def test_write_read_roundtrip(self, tmp_path: Path) -> None:
        backend = self.backend(tmp_path)
        path = str(tmp_path / "notes.txt")
        assert backend.write(path, "line-1\nline-2\n").error is None
        result = backend.read(path)
        assert result.error is None
        assert result.file_data is not None
        assert "line-1" in result.file_data["content"]

    def test_edit_and_delete(self, tmp_path: Path) -> None:
        backend = self.backend(tmp_path)
        path = str(tmp_path / "doc.txt")
        backend.write(path, "alpha beta\n")
        edited = backend.edit(path, "alpha", "gamma")
        assert edited.error is None
        content = backend.read(path).file_data["content"]
        assert "gamma beta" in content
        assert backend.delete(path).error is None
        assert backend.read(path).error is not None

    def test_glob(self, tmp_path: Path) -> None:
        backend = self.backend(tmp_path)
        (tmp_path / "src").mkdir()
        backend.write(str(tmp_path / "src" / "one.py"), "needle_here\n")
        backend.write(str(tmp_path / "src" / "two.py"), "nothing\n")

        globbed = backend.glob("*.py", path=str(tmp_path / "src"))
        assert globbed.error is None
        assert len(globbed.matches) == 2

    @pytest.mark.skipif(sys.platform == "darwin", reason="guest grep -Z is GNU-only")
    def test_grep(self, tmp_path: Path) -> None:
        backend = self.backend(tmp_path)
        (tmp_path / "src").mkdir()
        backend.write(str(tmp_path / "src" / "one.py"), "needle_here\n")
        backend.write(str(tmp_path / "src" / "two.py"), "nothing\n")

        grepped = backend.grep("needle", path=str(tmp_path))
        assert grepped.error is None
        assert any("one.py" in m["path"] for m in grepped.matches)

    def test_ls(self, tmp_path: Path) -> None:
        backend = self.backend(tmp_path)
        backend.write(str(tmp_path / "f.txt"), "x")
        result = backend.ls(str(tmp_path))
        assert result.error is None
        assert any("f.txt" in str(entry) for entry in result.entries)


class TestProtocolCompliance:
    def test_is_sandbox_backend_protocol(self) -> None:
        from soothe_deepagents.backends.protocol import SandboxBackendProtocol

        assert isinstance(make_backend(FakeClient(CommandRunResult())), SandboxBackendProtocol)

    def test_execute_accepts_timeout(self) -> None:
        from soothe_deepagents.backends.protocol import execute_accepts_timeout

        assert execute_accepts_timeout(ArcBoxBackend) is True

    def test_id_property(self) -> None:
        assert make_backend(FakeClient(CommandRunResult())).id == "sbx-test"

    def test_empty_sandbox_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="sandbox_id"):
            ArcBoxBackend(sandbox_id="")

    def test_supports_execution_via_composite_default(self) -> None:
        from soothe_deepagents.backends.composite import CompositeBackend
        from soothe_deepagents.middleware.filesystem import supports_execution

        sandbox = make_backend(FakeClient(CommandRunResult()))
        composite = CompositeBackend(default=sandbox, routes={})
        assert supports_execution(composite) is True


class TestBridgeLoop:
    def test_bridge_deadline_does_not_claim_kill(self, monkeypatch) -> None:
        """Bridge timeouts surface as errors with a still-running caveat (§10.2)."""
        import asyncio

        from soothe_nano.sandbox.arcbox import (
            ArcBoxTimeoutError,
            _SdkArcBoxClient,
        )

        client = _SdkArcBoxClient("sbx-test")

        class _FakeSandbox:
            class commands:  # noqa: N801 -- mirrors SDK attribute access
                @staticmethod
                def run(*args, **kwargs):
                    return asyncio.sleep(30)

        monkeypatch.setattr(_SdkArcBoxClient, "_ensure_sandbox", lambda self: _FakeSandbox)

        def _raise_bridge_timeout(coro, timeout=None):
            coro.close()
            raise ArcBoxTimeoutError("bridge deadline")

        monkeypatch.setattr("soothe_nano.sandbox.arcbox._call_sync", _raise_bridge_timeout)
        result = client.run("sleep 99", timeout=5)
        assert result.timed_out is False
        assert "may still be running" in (result.error or "")

        backend = ArcBoxBackend(
            sandbox_id="sbx-test",
            client=FakeClient(result),
        )
        response = backend.execute("sleep 99", timeout=5)
        assert response.exit_code is None  # NOT the 124 kill convention
        assert "may still be running" in response.output

    def test_call_sync_times_out_and_cancels(self) -> None:
        import asyncio

        from soothe_nano.sandbox.arcbox import ArcBoxTimeoutError, _call_sync

        async def hang() -> None:
            await asyncio.sleep(30)

        with pytest.raises(ArcBoxTimeoutError):
            _call_sync(hang(), timeout=0.05)

    def test_call_sync_returns_value(self) -> None:
        import asyncio

        from soothe_nano.sandbox.arcbox import _call_sync

        async def quick() -> str:
            await asyncio.sleep(0)
            return "done"

        assert _call_sync(quick(), timeout=5) == "done"


class TestLazyImports:
    def test_package_importable_without_sdk_use(self) -> None:
        """Importing the sandbox package never requires the arcbox SDK."""
        import soothe_nano.sandbox as pkg

        for name in ("ArcBoxBackend", "ArcBoxClient", "ArcBoxError"):
            assert getattr(pkg, name) is not None

    def test_arcbox_sdk_missing_gives_install_guidance(self, monkeypatch) -> None:
        """A missing arcbox SDK surfaces as ArcBoxError pointing at the core dep (§8.3)."""
        from soothe_nano.sandbox.arcbox import ArcBoxError, _SdkArcBoxClient

        monkeypatch.setitem(sys.modules, "arcbox", None)
        client = _SdkArcBoxClient("sbx-test")
        with pytest.raises(ArcBoxError, match="core dependency"):
            client._ensure_sandbox()


class TestSandboxInvariants:
    """§12.1 / §12.3 invariants that hold without a daemon."""

    def test_default_timeout_within_middleware_cap(self) -> None:
        """§7.2-8: default_timeout must stay under the middleware execute cap."""
        import inspect

        from soothe_deepagents.middleware.filesystem import FilesystemMiddleware

        cap = inspect.signature(FilesystemMiddleware.__init__).parameters[
            "max_execute_timeout"
        ].default
        assert ArcBoxBackend(sandbox_id="sbx-x", client=FakeClient(CommandRunResult())).default_timeout <= cap

    def test_constructor_surface_holds_no_model_credentials(self) -> None:
        """§12.1: the backend never accepts or stores model-provider credentials."""
        import inspect

        params = set(inspect.signature(ArcBoxBackend.__init__).parameters)
        assert params <= {
            "self",
            "sandbox_id",
            "client",
            "workspace_root",
            "default_timeout",
            "api_url",
            "api_key",  # ArcBox daemon transport credential — host-only
            "socket_path",
            "connect_timeout",
            "enable_capture_offload",
        }

    def test_file_tools_and_shell_share_guest_workspace(self, tmp_path: Path) -> None:
        """§12.3-4: middleware-derived writes are visible to guest shell, and vice versa."""
        backend = make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))
        assert backend.write(f"{tmp_path}/w.txt", "written-by-fs").error is None
        assert "written-by-fs" in backend.execute("cat w.txt").output

        assert backend.execute("echo shell-marker > r.txt").exit_code == 0
        read = backend.read(f"{tmp_path}/r.txt")
        assert "shell-marker" in read.file_data["content"]

    def test_concurrent_writes_do_not_corrupt(self, tmp_path: Path) -> None:
        """§10.4 smoke: parallel writes to one path end in a complete, uncorrupted state."""
        from concurrent.futures import ThreadPoolExecutor

        backend = make_backend(LocalGuestClient(tmp_path), workspace_root=str(tmp_path))
        path = f"{tmp_path}/race.txt"
        payloads = [f"writer-{i}\n" * 50 for i in range(8)]

        def write(payload: str) -> None:
            assert backend.write(path, payload).error is None

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, payloads))

        content = backend.read(path).file_data["content"]
        # One writer's payload wins wholesale: 50 identical lines, no
        # interleaved fragments. Line-wise comparison — the read transport
        # strips the trailing newline, so exact-payload matching is brittle.
        lines = content.splitlines()
        assert len(lines) == 50
        assert len(set(lines)) == 1
        assert lines[0] in {f"writer-{i}" for i in range(8)}
        assert "\x00" not in content
