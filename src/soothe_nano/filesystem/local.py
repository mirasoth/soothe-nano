"""Local filesystem implementation of UnifiedFilesystem."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

import aiofiles
from soothe_deepagents.backends.filesystem import FilesystemBackend
from soothe_deepagents.backends.fs_safety import (
    compute_version_stamp,
    create_backup,
    write_atomic,
)
from soothe_deepagents.backends.protocol import (
    BatchedEditOperation,
    BatchedEditResult,
    DeleteResult,
    EditResult,
    FileData,
    FileInfo,
    GlobResult,
    GrepResult,
    ReadResult,
    WriteResult,
)

from .exceptions import (
    DirectoryNotEmptyError,
    FilesystemError,
    InvalidPathError,
    NotADirectoryError,
    NotAFileError,
    PathNotFoundError,
    PathTraversalError,
    PermissionDeniedError,
)
from .unified import UnifiedFilesystem

logger = logging.getLogger(__name__)


class LocalFilesystem(UnifiedFilesystem):
    """Local filesystem implementation.

    This implementation uses Python's pathlib and standard library
    for filesystem operations. It provides full UnifiedFilesystem
    functionality with local file storage.
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        virtual_mode: bool = True,
        max_file_size_mb: int = 10,
        backup_dir: str | Path = ".backups",
    ) -> None:
        """Initialize local filesystem.

        Args:
            workspace: Root workspace directory.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
            backup_dir: Directory for backup files.
        """
        super().__init__(
            workspace=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        self._backup_dir = Path(backup_dir)
        # Shared deepagents backend owns atomic write / backup / locks / versioned
        # RMW / batched edits. Nano keeps path resolution + exception APIs on top.
        self._backend = FilesystemBackend(
            root_dir=self._workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
            backup_dir=backup_dir,
        )

    def _resolve_path(self, path: str, *, allow_host_absolute: bool = False) -> Path:
        """Resolve path within workspace.

        Args:
            path: Input path.
            allow_host_absolute: When ``True``, host-root absolutes outside the
                workspace (for example ``/Users/...``) resolve to the real path
                instead of being remapped into the sandbox. Used by read-only
                operations (``grep``, ``read``).

        Returns:
            Resolved Path object.

        Raises:
            PathTraversalError: If path escapes workspace.
        """
        from soothe_nano.workspace.workspace_paths import (
            should_use_virtual_path_resolution,
        )

        self._validate_path(path)

        # Handle empty or root paths
        if not path or path.strip() in {"", ".", "/"}:
            return self.workspace

        # Expand user and resolve
        expanded = Path(path).expanduser()

        if expanded.is_absolute():
            resolved = expanded.resolve()
            if self._is_within_workspace(resolved):
                return resolved
            if self.virtual_mode:
                if should_use_virtual_path_resolution(path.strip(), self.workspace):
                    rel_path = path.lstrip("/")
                    virtual = (self.workspace / rel_path).resolve()
                    if not self._is_within_workspace(virtual):
                        raise PathTraversalError(
                            path=path,
                            attempted_path=str(virtual),
                            workspace=str(self.workspace),
                        )
                    return virtual
                if allow_host_absolute:
                    return resolved
                raise PathTraversalError(
                    path=path,
                    attempted_path=str(resolved),
                    workspace=str(self.workspace),
                )
            return resolved

        # Relative path: resolve against workspace
        resolved = (self.workspace / path).resolve()

        # Bounds check only in virtual mode (sandboxed)
        if self.virtual_mode and not self._is_within_workspace(resolved):
            raise PathTraversalError(
                path=path,
                attempted_path=str(resolved),
                workspace=str(self.workspace),
            )

        return resolved

    def _create_backup(self, path: Path) -> Path | None:
        """Create backup of file before modification via deepagents helper."""
        backup_root = (
            self._backup_dir
            if self._backup_dir.is_absolute()
            else self.workspace / self._backup_dir
        )
        return create_backup(path, backup_dir=backup_root)

    def _result_path(self, resolved: Path) -> str:
        """Compute result path string for WriteResult/EditResult.

        Returns workspace-relative path if within workspace,
        otherwise absolute path (for virtual_mode=False case).

        Args:
            resolved: Resolved absolute path.

        Returns:
            Path string for result object.
        """
        if self._is_within_workspace(resolved):
            return str(resolved.relative_to(self.workspace))
        return str(resolved)

    def _compute_version_stamp(self, resolved: Path) -> str | None:
        """Compute a version stamp for optimistic concurrency control."""
        return compute_version_stamp(resolved)

    def _write_atomic(
        self,
        resolved: Path,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
    ) -> None:
        """Write content atomically via temp-file + ``os.replace``."""
        if isinstance(content, str):
            write_atomic(resolved, content, encoding=encoding)
            return
        # Binary path (deepagents helper is text-only).
        import uuid

        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = resolved.parent / f".{resolved.name}.{uuid.uuid4().hex}.tmp"
        try:
            tmp_path.write_bytes(content)
            os.replace(tmp_path, resolved)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def _check_file_size(self, resolved: Path, path: str) -> None:
        """Guard against reading or writing oversized files.

        Raises ``FilesystemError`` if the file exists and exceeds
        ``max_file_size_bytes``.

        Args:
            resolved: Absolute path to check.
            path: Original user-facing path string (for error messages).

        Raises:
            FilesystemError: If the file exceeds the size limit.
        """
        if resolved.exists() and resolved.is_file():
            file_size = resolved.stat().st_size
            if file_size > self.max_file_size_bytes:
                raise FilesystemError(
                    f"File too large: {file_size} bytes (max: {self.max_file_size_bytes})",
                    path=path,
                )

    def _backend_path(self, path: str, resolved: Path) -> str:
        """Path form expected by ``FilesystemBackend`` for this mode."""
        return path if self.virtual_mode else str(resolved)

    def _map_backend_error(self, error: str | None, path: str) -> None:
        """Raise nano typed exceptions from a deepagents ``*.error`` string."""
        if not error:
            return
        lowered = error.lower()
        if "not found" in lowered:
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if "permission" in lowered:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path)
        raise FilesystemError(error, path=path)

    # =======================================================================
    # Path Operations
    # =======================================================================

    def resolve_path(self, path: str, *, allow_host_absolute: bool = False) -> Path:
        """Resolve path relative to workspace."""
        return self._resolve_path(path, allow_host_absolute=allow_host_absolute)

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        try:
            resolved = self._resolve_path(path)
            return resolved.exists()
        except (PathTraversalError, InvalidPathError):
            return False

    def is_file(self, path: str) -> bool:
        """Check if path is a file."""
        try:
            resolved = self._resolve_path(path)
            return resolved.is_file()
        except (PathTraversalError, InvalidPathError):
            return False

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory."""
        try:
            resolved = self._resolve_path(path)
            return resolved.is_dir()
        except (PathTraversalError, InvalidPathError):
            return False

    # =======================================================================
    # Read Operations
    # =======================================================================

    def read(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Read file contents."""
        resolved = self._resolve_path(path, allow_host_absolute=True)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if not resolved.is_file():
            raise NotAFileError(f"Not a file: {path}", path=path)

        # Check file size
        file_size = resolved.stat().st_size
        if file_size > self.max_file_size_bytes:
            raise FilesystemError(
                f"File too large: {file_size} bytes (max: {self.max_file_size_bytes})",
                path=path,
            )

        # Read content
        try:
            with open(resolved, "rb") as f:
                if offset:
                    f.seek(offset)
                content_bytes = f.read(limit) if limit else f.read()
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Read error: {e}", path=path) from e

        # Try to decode as text
        is_binary = False
        try:
            content = content_bytes.decode(encoding)
        except UnicodeDecodeError:
            # Binary file - encode as base64
            import base64

            content = base64.b64encode(content_bytes).decode("ascii")
            is_binary = True

        return ReadResult(
            file_data=FileData(
                content=content,
                encoding="base64" if is_binary else encoding,
            )
        )

    async def aread(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Async read file contents using aiofiles (IG-517)."""
        resolved = self._resolve_path(path, allow_host_absolute=True)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if not resolved.is_file():
            raise NotAFileError(f"Not a file: {path}", path=path)

        # Check file size
        file_size = resolved.stat().st_size
        if file_size > self.max_file_size_bytes:
            raise FilesystemError(
                f"File too large: {file_size} bytes (max: {self.max_file_size_bytes})",
                path=path,
            )

        # Async read content
        try:
            async with aiofiles.open(resolved, "rb") as f:
                if offset:
                    await f.seek(offset)
                content_bytes = await f.read(limit) if limit else await f.read()
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Read error: {e}", path=path) from e

        # Try to decode as text
        is_binary = False
        try:
            content = content_bytes.decode(encoding)
        except UnicodeDecodeError:
            # Binary file - encode as base64
            import base64

            content = base64.b64encode(content_bytes).decode("ascii")
            is_binary = True

        return ReadResult(
            file_data=FileData(
                content=content,
                encoding="base64" if is_binary else encoding,
            )
        )

    # =======================================================================
    # Write Operations
    # =======================================================================

    def write(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Write content to file via deepagents ``FilesystemBackend`` (text) or atomic bytes."""
        resolved = self._resolve_path(path)

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Cannot create directory for {path}: {e}", path=path) from e

        if isinstance(content, bytes):
            backup_path = None
            if backup and resolved.exists():
                backup_path = self._create_backup(resolved)
            try:
                with self._backend.edit_locks.acquire_sync(resolved):
                    self._write_atomic(resolved, content)
            except PermissionError as e:
                raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
            except OSError as e:
                raise FilesystemError(f"Write error: {e}", path=path) from e
            return WriteResult(
                path=self._result_path(resolved),
                backup_path=self._result_path(backup_path) if backup_path else None,
            )

        if encoding.lower().replace("-", "") != "utf8":
            # Non-UTF8 text: encode locally then atomic bytes write.
            data = content.encode(encoding)
            return self.write(path, data, backup=backup)

        backend_path = self._backend_path(path, resolved)
        result = self._backend.write(backend_path, content, backup=backup)
        self._map_backend_error(result.error, path)
        return WriteResult(
            path=self._result_path(resolved),
            backup_path=result.backup_path,
        )

    async def awrite(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Async write via deepagents backend (text) or locked atomic bytes."""
        resolved = self._resolve_path(path)

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Cannot create directory for {path}: {e}", path=path) from e

        self._check_file_size(resolved, path)

        if isinstance(content, bytes) or encoding.lower().replace("-", "") != "utf8":
            data: str | bytes = content if isinstance(content, bytes) else content.encode(encoding)
            backup_path = None
            async with self._backend.edit_locks.acquire(resolved):
                if backup and resolved.exists():
                    backup_path = self._create_backup(resolved)
                try:
                    self._write_atomic(resolved, data)
                except PermissionError as e:
                    raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
                except OSError as e:
                    raise FilesystemError(f"Write error: {e}", path=path) from e
            return WriteResult(
                path=self._result_path(resolved),
                backup_path=self._result_path(backup_path) if backup_path else None,
            )

        backend_path = self._backend_path(path, resolved)
        result = await self._backend.awrite(backend_path, content, backup=backup)
        self._map_backend_error(result.error, path)
        return WriteResult(
            path=self._result_path(resolved),
            backup_path=result.backup_path,
        )

    # =======================================================================
    # Edit Operations
    # =======================================================================

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Replace old_string with new_string via deepagents ``FilesystemBackend``."""
        resolved = self._resolve_path(path)
        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        self._check_file_size(resolved, path)

        backend_path = self._backend_path(path, resolved)
        result = self._backend.edit(
            backend_path, old_string, new_string, replace_all=False, backup=backup
        )
        self._map_backend_error(result.error, path)
        return EditResult(
            path=self._result_path(resolved),
            occurrences=result.occurrences or 1,
            backup_path=result.backup_path,
        )

    async def aedit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace via deepagents ``FilesystemBackend``."""
        resolved = self._resolve_path(path)
        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        self._check_file_size(resolved, path)

        backend_path = self._backend_path(path, resolved)
        result = await self._backend.aedit(
            backend_path, old_string, new_string, replace_all=False, backup=backup
        )
        self._map_backend_error(result.error, path)
        return EditResult(
            path=self._result_path(resolved),
            occurrences=result.occurrences or 1,
            backup_path=result.backup_path,
        )

    def edit_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Replace specific line range in file."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        with self._backend.edit_locks.acquire_sync(resolved):
            with open(resolved, encoding="utf-8") as f:
                lines = f.readlines()

            insert_mode = end_line == start_line - 1
            if insert_mode:
                if start_line < 1 or start_line > len(lines) + 1:
                    raise FilesystemError(
                        f"Invalid line number: {start_line} (file has {len(lines)} lines)",
                        path=path,
                    )
            elif start_line < 1 or end_line > len(lines) or start_line > end_line:
                raise FilesystemError(
                    f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines)",
                    path=path,
                )

            # Create backup
            backup_path = None
            if backup:
                backup_path = self._create_backup(resolved)

            new_lines = new_content.split("\n")
            if new_lines and new_lines[-1] == "":
                new_lines = new_lines[:-1]

            formatted_new_lines = [line + "\n" for line in new_lines]
            if insert_mode:
                result_lines = (
                    lines[: start_line - 1] + formatted_new_lines + lines[start_line - 1 :]
                )
            else:
                result_lines = lines[: start_line - 1] + formatted_new_lines + lines[end_line:]

            self._write_atomic(resolved, "".join(result_lines))

            return EditResult(
                path=self._result_path(resolved),
                occurrences=1,
                backup_path=self._result_path(backup_path) if backup_path else None,
            )

    async def aedit_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace specific line range in file.

        Uses optimistic concurrency: a version stamp is captured before
        reading the file and verified before the atomic write. If an
        external writer modified the file in between, the operation is
        retried once. The final write is atomic (temp file + os.replace).
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Guard against oversized files
        self._check_file_size(resolved, path)

        async with self._backend.edit_locks.acquire(resolved):
            for attempt in range(2):
                # Snapshot version stamp before reading
                stamp_before = self._compute_version_stamp(resolved)

                # Async read lines
                async with aiofiles.open(resolved, encoding="utf-8") as f:
                    content = await f.read()
                lines = content.splitlines(keepends=True)

                insert_mode = end_line == start_line - 1
                if insert_mode:
                    if start_line < 1 or start_line > len(lines) + 1:
                        raise FilesystemError(
                            f"Invalid line number: {start_line} (file has {len(lines)} lines)",
                            path=path,
                        )
                elif start_line < 1 or end_line > len(lines) or start_line > end_line:
                    raise FilesystemError(
                        f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines)",
                        path=path,
                    )

                # Create backup (sync — rare operation)
                backup_path = None
                if backup:
                    backup_path = self._create_backup(resolved)

                # Verify stamp unchanged before write
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying edit_lines",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

                new_lines = new_content.split("\n")
                if new_lines and new_lines[-1] == "":
                    new_lines = new_lines[:-1]

                formatted_new_lines = [line + "\n" for line in new_lines]
                if insert_mode:
                    result_lines = (
                        lines[: start_line - 1] + formatted_new_lines + lines[start_line - 1 :]
                    )
                else:
                    result_lines = lines[: start_line - 1] + formatted_new_lines + lines[end_line:]

                new_full_content = "".join(result_lines)

                # Atomic write back (temp file + os.replace)
                self._write_atomic(resolved, new_full_content)

                return EditResult(
                    path=self._result_path(resolved),
                    occurrences=1,
                    backup_path=self._result_path(backup_path) if backup_path else None,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Edit failed after retry: {path}", path=path)

    def insert_lines(
        self,
        path: str,
        line: int,
        content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Insert content at specific line number."""
        return self.edit_lines(path, line, line - 1, content, backup=backup)

    async def ainsert_lines(
        self,
        path: str,
        line: int,
        content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async insert content at specific line number."""
        return self.insert_lines(path, line, content, backup=backup)

    def delete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Delete specific line range from file."""
        # Delete is equivalent to replacing with empty content
        return self.edit_lines(path, start_line, end_line, "", backup=backup)

    async def adelete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async delete specific line range from file."""
        return self.delete_lines(path, start_line, end_line, backup=backup)

    async def aedit_batched(
        self,
        path: str,
        operations: list[BatchedEditOperation],
        *,
        backup: bool = True,
    ) -> BatchedEditResult:
        """Apply multiple edit operations via deepagents `FilesystemBackend`.

        Raises:
            PathNotFoundError: If file does not exist.
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        self._check_file_size(resolved, path)

        backend_path = path if self.virtual_mode else str(resolved)
        da = await self._backend.aedit_batched(backend_path, operations, backup=backup)
        return BatchedEditResult(
            path=self._result_path(resolved),
            total_lines_changed=da.total_lines_changed,
            operations_applied=da.operations_applied,
            failed_operations=da.failed_operations,
            backup_path=da.backup_path,
            error=da.error,
        )

    def apply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Apply unified diff patch to file with atomic write.

        Reads the current content, applies the patch in-memory, and writes
        the result atomically via temp file + ``os.replace``. A version
        stamp is captured before reading and verified before writing; if
        an external writer modified the file, the operation retries once.

        Falls back to the ``patch`` command-line tool for diffs that
        cannot be applied via the in-memory approach.
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Guard against oversized files
        self._check_file_size(resolved, path)

        with self._backend.edit_locks.acquire_sync(resolved):
            for attempt in range(2):
                # Snapshot version stamp before reading
                stamp_before = self._compute_version_stamp(resolved)

                # Read current content
                with open(resolved, encoding="utf-8") as f:
                    content = f.read()

                # Create backup
                backup_path = None
                if backup:
                    backup_path = self._create_backup(resolved)

                # Verify stamp unchanged before applying patch
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying diff apply",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

                # Apply patch in-memory using the patch command on temp content
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".diff", delete=False, encoding="utf-8"
                ) as diff_file:
                    diff_file.write(diff)
                    diff_file_path = diff_file.name

                import tempfile as _tmpf

                # Create a temp copy of the original content to patch
                with _tmpf.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                ) as content_file:
                    content_file.write(content)
                    content_file_path = content_file.name

                try:
                    subprocess.run(
                        ["patch", "-u", content_file_path, diff_file_path],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    with open(content_file_path, encoding="utf-8") as f:
                        new_content = f.read()
                except subprocess.CalledProcessError as e:
                    raise FilesystemError(
                        f"Failed to apply diff: {e.stderr}",
                        path=path,
                    ) from e
                except FileNotFoundError:
                    raise FilesystemError(
                        "patch command not found. Please install patch.",
                        path=path,
                    )
                finally:
                    # Clean up temp files
                    for tmp in (diff_file_path, content_file_path):
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass

                # Atomic write back
                self._write_atomic(resolved, new_content)

                return EditResult(
                    path=self._result_path(resolved),
                    occurrences=1,
                    backup_path=self._result_path(backup_path) if backup_path else None,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Diff apply failed after retry: {path}", path=path)

    async def aapply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async apply unified diff patch to file with atomic write.

        Delegates to the sync ``apply_diff`` which performs in-memory
        patching followed by an atomic temp-file + ``os.replace`` write.
        Optimistic concurrency (version stamp) is used to detect external
        writers and retry once.
        """
        resolved = self._resolve_path(path)
        async with self._backend.edit_locks.acquire(resolved):
            return self.apply_diff(path, diff, backup=backup)

    # =======================================================================
    # Directory Operations
    # =======================================================================

    def ls(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """List directory contents."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"Directory not found: {path}", path=path)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}", path=path)

        entries = []
        for entry in resolved.iterdir():
            if include_info:
                entries.append(self._get_file_info(entry))
            else:
                entries.append(entry.name)

        return entries

    async def als(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """Async list directory contents."""
        return self.ls(path, include_info=include_info)

    def _get_file_info(self, path: Path) -> FileInfo:
        """Get FileInfo for a path."""
        stat = path.stat()
        from datetime import datetime

        modified_at = datetime.fromtimestamp(stat.st_mtime)

        info: FileInfo = {
            "path": self._result_path(path),
            "is_dir": path.is_dir(),
            "size": stat.st_size,
            "modified_at": modified_at.isoformat(),
        }
        return info

    def mkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Create directory."""
        resolved = self._resolve_path(path)

        try:
            resolved.mkdir(parents=recursive, exist_ok=exist_ok)
        except FileExistsError:
            if not exist_ok:
                raise FilesystemError(f"Directory already exists: {path}", path=path)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e

        return self._get_file_info(resolved)

    async def amkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Async create directory."""
        return self.mkdir(path, recursive=recursive, exist_ok=exist_ok)

    def rmdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Remove directory."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"Directory not found: {path}", path=path)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}", path=path)

        # Check if empty
        if not recursive and any(resolved.iterdir()):
            raise DirectoryNotEmptyError(f"Directory not empty: {path}", path=path)

        # Create backup if needed
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        try:
            if recursive:
                shutil.rmtree(resolved)
            else:
                resolved.rmdir()
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e

        return DeleteResult(
            path=self._result_path(resolved),
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

    async def armdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Async remove directory."""
        return self.rmdir(path, recursive=recursive, backup=backup)

    # =======================================================================
    # File Operations
    # =======================================================================

    def delete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Delete file via deepagents ``FilesystemBackend`` (file-only semantics)."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if not resolved.is_file():
            raise NotAFileError(f"Not a file: {path}", path=path)

        backend_path = self._backend_path(path, resolved)
        result = self._backend.delete(backend_path, backup=backup)
        self._map_backend_error(result.error, path)
        return DeleteResult(
            path=self._result_path(resolved),
            backup_path=result.backup_path,
        )

    async def adelete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Async delete file via deepagents ``FilesystemBackend``."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if not resolved.is_file():
            raise NotAFileError(f"Not a file: {path}", path=path)

        backend_path = self._backend_path(path, resolved)
        result = await self._backend.adelete(backend_path, backup=backup)
        self._map_backend_error(result.error, path)
        return DeleteResult(
            path=self._result_path(resolved),
            backup_path=result.backup_path,
        )

    def info(self, path: str) -> FileInfo:
        """Get file/directory information."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"Path not found: {path}", path=path)

        return self._get_file_info(resolved)

    async def ainfo(self, path: str) -> FileInfo:
        """Async get file/directory information."""
        return self.info(path)

    def copy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Copy file or directory."""
        src_resolved = self._resolve_path(src)
        dst_resolved = self._resolve_path(dst)

        if not src_resolved.exists():
            raise PathNotFoundError(f"Source not found: {src}", path=src)

        if dst_resolved.exists() and not overwrite:
            raise FilesystemError(f"Destination exists: {dst}", path=dst)

        try:
            if src_resolved.is_dir():
                shutil.copytree(src_resolved, dst_resolved, dirs_exist_ok=overwrite)
            else:
                shutil.copy2(src_resolved, dst_resolved)
        except PermissionError as e:
            raise PermissionDeniedError("Permission denied", path=src) from e

        return self._get_file_info(dst_resolved)

    async def acopy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async copy file or directory."""
        return self.copy(src, dst, overwrite=overwrite)

    def move(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Move/rename file or directory."""
        src_resolved = self._resolve_path(src)
        dst_resolved = self._resolve_path(dst)

        if not src_resolved.exists():
            raise PathNotFoundError(f"Source not found: {src}", path=src)

        if dst_resolved.exists() and not overwrite:
            raise FilesystemError(f"Destination exists: {dst}", path=dst)

        try:
            shutil.move(str(src_resolved), str(dst_resolved))
        except PermissionError as e:
            raise PermissionDeniedError("Permission denied", path=src) from e

        return self._get_file_info(dst_resolved)

    async def amove(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async move/rename file or directory."""
        return self.move(src, dst, overwrite=overwrite)

    # =======================================================================
    # Search Operations
    # =======================================================================

    def glob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Glob pattern matching."""
        resolved = self._resolve_path(path)

        if not resolved.is_dir():
            return GlobResult(matches=[], error=f"Not a directory: {path}")

        matches: list[FileInfo] = []
        # Use pathlib's glob for proper ** handling
        try:
            for match in resolved.glob(pattern):
                if match.is_file():
                    matches.append({"path": str(match.relative_to(resolved)), "is_dir": False})
        except OSError:
            pass

        return GlobResult(matches=matches)

    async def aglob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Async glob pattern matching."""
        return await asyncio.to_thread(
            self.glob, pattern, path=path, include_ignored=include_ignored
        )

    def grep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
    ) -> GrepResult | list[str] | str:
        """Search for pattern in files via deepagents public search API.

        Uses ``FilesystemBackend.grep`` (ripgrep + Python fallback). Paths in
        results are normalized to the same workspace-relative / absolute form
        as other LocalFilesystem operations.

        Args:
            pattern: Literal text pattern to search for.
            path: Directory or file to search.
            glob: Optional glob pattern for file filtering.
            output_mode: ``files_with_matches``, ``count``, or ``content``.

        Returns:
            GrepResult, or simplified list[str] / str for files_with_matches / count modes.
        """
        resolved = self._resolve_path(path, allow_host_absolute=True)

        if not resolved.is_dir() and not resolved.is_file():
            return GrepResult(matches=[])

        if self._is_within_workspace(resolved):
            use_backend = self._backend
            backend_path = path if self.virtual_mode else str(resolved)
            normalize_virtual = self.virtual_mode
        else:
            # Host-absolute paths outside the workspace (e.g. log files).
            search_root = resolved.parent if resolved.is_file() else resolved
            use_backend = FilesystemBackend(
                root_dir=search_root,
                virtual_mode=False,
                max_file_size_mb=self.max_file_size_mb,
            )
            backend_path = str(resolved)
            normalize_virtual = False

        da = use_backend.grep(pattern, path=backend_path, glob=glob)
        matches: list[dict[str, object]] = []
        for match in da.matches or []:
            if not isinstance(match, dict):
                continue
            raw_path = str(match.get("path", ""))
            if normalize_virtual:
                norm = raw_path.lstrip("/")
            else:
                try:
                    match_resolved = Path(raw_path)
                    if not match_resolved.is_absolute():
                        match_resolved = (resolved.parent / raw_path).resolve()
                    else:
                        match_resolved = match_resolved.resolve()
                    if self._is_within_workspace(match_resolved):
                        norm = self._result_path(match_resolved)
                    else:
                        norm = str(match_resolved)
                except (OSError, ValueError, RuntimeError):
                    norm = raw_path
            matches.append(
                {
                    "path": norm,
                    "line": int(match.get("line", 0)),
                    "text": str(match.get("text", "")),
                }
            )

        if output_mode == "content":
            return GrepResult(error=da.error, matches=matches, truncated=da.truncated)
        if output_mode == "count":
            return str(len(matches))
        seen: list[str] = []
        for match in matches:
            p = str(match.get("path", ""))
            if p and p not in seen:
                seen.append(p)
        return seen

    async def agrep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
    ) -> GrepResult | list[str] | str:
        """Async search for pattern in files via ``ag`` or ``rg``."""
        return await asyncio.to_thread(
            self.grep,
            pattern,
            path=path,
            glob=glob,
            output_mode=output_mode,
        )
