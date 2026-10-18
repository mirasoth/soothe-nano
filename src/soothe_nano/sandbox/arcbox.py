"""ArcBox microVM backend: remote shell and file operations via the arcbox SDK.

Implements :class:`soothe_deepagents.backends.sandbox.BaseSandbox`, so all
file operations (``ls``/``read``/``write``/``edit``/``delete``/``glob``/
``grep``) are derived by the base class from guest-side ``execute``. The
guest image must therefore ship ``python3`` and POSIX coreutils.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from soothe_deepagents.backends.protocol import (
    FILE_NOT_FOUND,
    INVALID_PATH,
    IS_DIRECTORY,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from soothe_deepagents.backends.sandbox import BaseSandbox

logger = logging.getLogger(__name__)

__all__ = [
    "ArcBoxBackend",
    "ArcBoxClient",
    "ArcBoxError",
    "ArcBoxFileNotFoundError",
    "ArcBoxIsDirectoryError",
    "ArcBoxTimeoutError",
    "CommandRunResult",
]

_BRIDGE_GRACE_SECONDS = 30.0
"""Extra headroom over the per-command timeout for the sync bridge round-trip."""


class ArcBoxError(Exception):
    """ArcBox adapter failure (SDK error, transport error, or dead sandbox)."""


class ArcBoxTimeoutError(ArcBoxError):
    """The sandbox call exceeded the bridge deadline."""


class ArcBoxFileNotFoundError(ArcBoxError):
    """The requested guest path does not exist."""


class ArcBoxIsDirectoryError(ArcBoxError):
    """The requested guest path is a directory, not a file."""


@dataclass(frozen=True)
class CommandRunResult:
    """Outcome of one guest command (errors as data, not exceptions)."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    error: str | None = None


class ArcBoxClient(Protocol):
    """Sync adapter seam over the async arcbox SDK (injectable for tests)."""

    def run(
        self, command: str, *, cwd: str | None = None, timeout: int | None = None
    ) -> CommandRunResult:
        """Run one guest command; timeouts surface as ``timed_out=True``."""
        ...

    def read_bytes(self, path: str) -> bytes:
        """Read one guest file; raise ``ArcBoxFileNotFoundError`` if missing."""
        ...

    def write_bytes(self, path: str, data: bytes) -> None:
        """Write one guest file, creating or truncating it."""
        ...


class _BackgroundLoop:
    """Dedicated event loop thread bridging sync protocol calls to the async SDK.

    Protocol methods are sync and may be invoked from arbitrary worker
    threads (``asyncio.to_thread``, ``run_in_executor``), so the async SDK
    cannot share the caller's loop. A single daemon loop serves all
    sandboxes in the process.
    """

    _lock = threading.Lock()
    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get(cls) -> asyncio.AbstractEventLoop:
        with cls._lock:
            if cls._loop is None or cls._loop.is_closed():
                cls._loop = asyncio.new_event_loop()
                threading.Thread(
                    target=cls._loop.run_forever,
                    name="arcbox-bridge",
                    daemon=True,
                ).start()
            return cls._loop


def _call_sync(coro: Any, *, timeout: float | None) -> Any:
    """Run ``coro`` on the bridge loop and block for its result."""
    loop = _BackgroundLoop.get()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        msg = f"ArcBox bridge call exceeded {timeout}s"
        raise ArcBoxTimeoutError(msg) from None


def _is_arcbox_error(exc: BaseException) -> bool:
    try:
        from arcbox.errors import ArcBoxError as _SdkArcBoxError

        return isinstance(exc, _SdkArcBoxError)
    except ImportError:
        return False


class _SdkArcBoxClient:
    """``ArcBoxClient`` implementation over the real arcbox SDK (0.1.x).

    The sandbox must already exist; this client only connects to it by id.
    Lifecycle (create/kill) belongs to the caller, per docs/arcbox-backend.md §10.
    """

    def __init__(
        self,
        sandbox_id: str,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        socket_path: str | None = None,
        connect_timeout: float = 60.0,
    ) -> None:
        self._sandbox_id = sandbox_id
        self._api_url = api_url
        self._api_key = api_key
        self._socket_path = socket_path
        self._connect_timeout = connect_timeout
        self._client: Any = None
        self._sandbox: Any = None

    def _ensure_sandbox(self) -> Any:
        if self._sandbox is not None:
            return self._sandbox
        try:
            import arcbox  # noqa: PLC0415 -- optional dependency, lazy by design
        except ImportError as exc:
            raise ArcBoxError(
                "The arcbox SDK is not available. It ships as a core dependency "
                "of soothe-nano (arcbox>=0.1.0); reinstall the package or inject "
                "a custom ArcBoxClient instead."
            ) from exc

        conn_kwargs: dict[str, Any] = {}
        if self._api_url:
            conn_kwargs["api_url"] = self._api_url
        if self._api_key:
            conn_kwargs["api_key"] = self._api_key
        if self._socket_path:
            conn_kwargs["socket_path"] = self._socket_path
        connection = arcbox.Connection(**conn_kwargs) if conn_kwargs else None
        self._client = arcbox.AsyncArcBox(connection)
        self._sandbox = _call_sync(
            self._client.connect(self._sandbox_id, timeout=self._connect_timeout),
            timeout=self._connect_timeout + _BRIDGE_GRACE_SECONDS,
        )
        return self._sandbox

    def run(
        self, command: str, *, cwd: str | None = None, timeout: int | None = None
    ) -> CommandRunResult:
        try:
            sandbox = self._ensure_sandbox()
            result = _call_sync(
                sandbox.commands.run(
                    command,
                    cwd=cwd,
                    timeout=float(timeout) if timeout is not None else None,
                ),
                timeout=(timeout + _BRIDGE_GRACE_SECONDS) if timeout is not None else None,
            )
        except ArcBoxTimeoutError:
            # Bridge deadline: only the waiter coroutine was cancelled — the
            # guest command may still be running (docs/arcbox-backend.md §8). Never claim it
            # was killed; surface as error-as-data with an explicit caveat.
            return CommandRunResult(
                error=(
                    f"Command exceeded the {timeout}s bridge deadline; "
                    "the guest command may still be running"
                ),
            )
        except Exception as exc:  # noqa: BLE001 -- SDK errors surface as data
            if not _is_arcbox_error(exc):
                raise
            return CommandRunResult(error=f"ArcBox command failed: {exc}")
        # SDK timeout kills the process group and reports signal death as data
        # (exit-as-data, not raised); SIGKILL after a requested timeout is
        # indistinguishable from an external kill, so report both faithfully.
        timed_out = timeout is not None and result.signal == "SIGKILL"
        return CommandRunResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            timed_out=timed_out,
            truncated=result.truncated,
        )

    def read_bytes(self, path: str) -> bytes:
        try:
            sandbox = self._ensure_sandbox()
            return _call_sync(sandbox.files.read_bytes(path), timeout=None)
        except Exception as exc:  # noqa: BLE001 -- mapped below
            raise self._map_file_error(exc, path) from exc

    def write_bytes(self, path: str, data: bytes) -> None:
        try:
            sandbox = self._ensure_sandbox()
            _call_sync(sandbox.files.write_bytes(path, data), timeout=None)
        except Exception as exc:  # noqa: BLE001 -- mapped below
            raise self._map_file_error(exc, path) from exc

    @staticmethod
    def _map_file_error(exc: BaseException, path: str) -> ArcBoxError:
        try:
            from arcbox.errors import InvalidArgumentError, NotFoundError

            if isinstance(exc, NotFoundError):
                return ArcBoxFileNotFoundError(path)
            if isinstance(exc, IsADirectoryError):
                return ArcBoxIsDirectoryError(path)
            if isinstance(exc, InvalidArgumentError) and "director" in str(exc).lower():
                return ArcBoxIsDirectoryError(path)
        except ImportError:
            pass
        if isinstance(exc, IsADirectoryError):
            return ArcBoxIsDirectoryError(path)
        if isinstance(exc, ArcBoxError):
            return exc
        return ArcBoxError(f"ArcBox file operation failed on {path}: {exc}")


def _merge_output(stdout: str, stderr: str) -> str:
    """Combine stdout and stderr (stderr appended; no seam when stdout empty)."""
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


class ArcBoxBackend(BaseSandbox):
    """Backend bound to an existing ArcBox sandbox.

    The caller (e.g. a session layer) creates and owns the sandbox and
    injects its id; this backend never creates or destroys VMs. Only the
    four ``BaseSandbox`` abstract members are implemented — all file
    operations are derived from guest-side ``execute``.

    Args:
        sandbox_id: Id of an existing, ready ArcBox sandbox.
        client: Optional ``ArcBoxClient`` (inject a fake for tests);
            defaults to the real arcbox SDK adapter.
        workspace_root: Guest path used as the default command cwd.
        default_timeout: Fallback ``execute`` timeout in seconds.
        api_url: Optional daemon URL (env fallback ``ARCBOX_API_URL``).
        api_key: Optional daemon credential (env fallback ``ARCBOX_API_KEY``).
        socket_path: Optional daemon Unix socket path.
        connect_timeout: Seconds to wait for the first ``connect``.
        enable_capture_offload: Opt in to ``BaseSandbox`` output offload
            once the guest image is verified to ship POSIX shell +
            coreutils; ``None`` keeps the class default (off).
    """

    def __init__(
        self,
        *,
        sandbox_id: str,
        client: ArcBoxClient | None = None,
        workspace_root: str = "/workspace",
        default_timeout: int = 120,
        api_url: str | None = None,
        api_key: str | None = None,
        socket_path: str | None = None,
        connect_timeout: float = 60.0,
        enable_capture_offload: bool | None = None,
    ) -> None:
        if not sandbox_id:
            msg = "ArcBoxBackend requires a non-empty sandbox_id"
            raise ValueError(msg)
        self._sandbox_id = sandbox_id
        self.workspace_root = workspace_root
        self.default_timeout = default_timeout
        self._client = client or _SdkArcBoxClient(
            sandbox_id,
            api_url=api_url,
            api_key=api_key,
            socket_path=socket_path,
            connect_timeout=connect_timeout,
        )
        if enable_capture_offload is not None:
            self.enable_capture_offload = enable_capture_offload

    @property
    def id(self) -> str:
        return self._sandbox_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        effective = self.default_timeout if timeout is None else int(timeout)
        result = self._client.run(command, cwd=self.workspace_root, timeout=effective)
        if result.error is not None:
            return ExecuteResponse(output=f"Error: {result.error}", exit_code=None)
        output = _merge_output(result.stdout, result.stderr)
        exit_code = result.exit_code
        if result.timed_out:
            # Timeout convention (docs/arcbox-backend.md §8): exit_code=124 + note text.
            note = f"Command exceeded timeout of {effective}s; the process group was killed."
            output = f"{output}\n{note}" if output else note
            exit_code = 124
        if result.truncated:
            output = f"{output}\n... (output truncated)" if output else "... (output truncated)"
        return ExecuteResponse(output=output, exit_code=exit_code, truncated=result.truncated)

    def upload_files(self, files: Sequence[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, data in files:
            if not path.startswith("/"):
                responses.append(FileUploadResponse(path=path, error=INVALID_PATH))
                continue
            try:
                self._client.write_bytes(path, data)
                responses.append(FileUploadResponse(path=path, error=None))
            except ArcBoxError as exc:
                logger.debug("ArcBox upload failed for %s: %s", path, exc)
                responses.append(FileUploadResponse(path=path, error=str(exc)))
        return responses

    def download_files(self, paths: Sequence[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            if not path.startswith("/"):
                responses.append(FileDownloadResponse(path=path, content=None, error=INVALID_PATH))
                continue
            try:
                content = self._client.read_bytes(path)
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except ArcBoxFileNotFoundError:
                responses.append(
                    FileDownloadResponse(path=path, content=None, error=FILE_NOT_FOUND)
                )
            except ArcBoxIsDirectoryError:
                responses.append(FileDownloadResponse(path=path, content=None, error=IS_DIRECTORY))
            except ArcBoxError as exc:
                logger.debug("ArcBox download failed for %s: %s", path, exc)
                responses.append(FileDownloadResponse(path=path, content=None, error=str(exc)))
        return responses
