"""Workspace-aware filesystem backends and framework singleton."""

from __future__ import annotations

import logging
from contextvars import Token
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_deepagents.backends.protocol import (
    BackendProtocol,
    DeleteResult,
    EditResult,
    FileData,
    LsResult,
    ReadResult,
    WriteResult,
)

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_DEFAULT_READ_LINE_LIMIT = 2000


def _grep_matches_for_backend(result: Any) -> list[dict[str, Any]]:
    """Normalize LocalFilesystem grep return shapes to GrepMatch dicts."""
    from soothe_deepagents.backends.protocol import GrepResult

    matches: list[dict[str, Any]] = []
    if isinstance(result, GrepResult):
        for match in result.matches or []:
            if isinstance(match, dict):
                matches.append(
                    {
                        "path": match.get("path", ""),
                        "line": int(match.get("line", 0)),
                        "text": match.get("text", ""),
                    }
                )
            else:
                matches.append(
                    {
                        "path": getattr(match, "path", ""),
                        "line": int(getattr(match, "line", getattr(match, "line_number", 0))),
                        "text": getattr(match, "text", getattr(match, "line_content", "")),
                    }
                )
    elif isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                matches.append(item)
            elif isinstance(item, str):
                matches.append({"path": item, "line": 0, "text": ""})
    elif isinstance(result, str) and result:
        for line in result.split("\n"):
            if line:
                matches.append({"path": line, "line": 0, "text": ""})
    return matches


def _read_result_for_path(
    fs: Any,
    normalized: str,
    *,
    offset: int,
    limit: int,
    display_path: str,
) -> ReadResult:
    from soothe_nano.filesystem.exceptions import (
        FilesystemError,
        NotAFileError,
        PathNotFoundError,
    )

    try:
        raw = fs.read(normalized)
    except PathNotFoundError:
        return ReadResult(error=f"File '{display_path}' not found")
    except NotAFileError:
        return ReadResult(error=f"File '{display_path}' not found")
    except FilesystemError as exc:
        return ReadResult(error=str(exc))

    if isinstance(raw, ReadResult):
        if raw.error:
            return raw
        file_data = raw.file_data
        if not file_data:
            return ReadResult(file_data=FileData(content="", encoding="utf-8"))
        content = file_data.get("content", "")
        encoding = file_data.get("encoding", "utf-8")
        if encoding == "base64":
            return ReadResult(file_data=FileData(content=content, encoding="base64"))
        if not content:
            return ReadResult(file_data=FileData(content="", encoding="utf-8"))
        lines = content.splitlines(keepends=True)
        start_idx = max(offset, 0)
        end_idx = min(start_idx + limit, len(lines))
        if start_idx >= len(lines):
            return ReadResult(
                error=(
                    f"Line offset {offset} exceeds file length ({len(lines)} lines). "
                    f"Offset is 0-indexed: use offset={max(len(lines) - 1, 0)} to read the last line."
                ),
            )
        return ReadResult(
            file_data=FileData(content="".join(lines[start_idx:end_idx]), encoding="utf-8")
        )

    # Legacy nano-shaped read (should not appear after cutover)
    return ReadResult(error=f"Unexpected read result for '{display_path}'")


class NormalizedPathBackend:
    """Wrapper that normalizes paths to workspace-relative."""

    def __init__(
        self,
        root_dir: Path,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        self._root_dir = Path(root_dir)
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb

        from soothe_nano.filesystem.workspace import WorkspaceFilesystem

        self._fs = WorkspaceFilesystem(
            workspace=root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    @property
    def cwd(self) -> str:
        return str(self._root_dir)

    @property
    def virtual_mode(self) -> bool:
        return self._virtual_mode

    def _normalize_path(self, path: str) -> str:
        if not path or path.strip() in {"", ".", "/"}:
            return "."

        expanded = Path(path.strip()).expanduser()
        if expanded.is_absolute():
            abs_str = str(expanded.resolve())
            try:
                rel = expanded.resolve().relative_to(self._root_dir.resolve())
            except ValueError:
                if self._virtual_mode:
                    from soothe_nano.workspace.workspace_paths import (
                        should_use_virtual_path_resolution,
                    )

                    if should_use_virtual_path_resolution(path.strip(), self._root_dir):
                        relative = abs_str.lstrip("/")
                        return relative or "."
                    return abs_str
                return abs_str
            if self._virtual_mode:
                return rel.as_posix()
            return abs_str
        return path.strip()

    def resolve_os_path(self, path: str) -> Path:
        normalized = self._normalize_path(path)
        return self._fs.resolve_path(normalized, allow_host_absolute=True)

    def read(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        normalized = self._normalize_path(path)
        line_limit = limit if limit is not None else _DEFAULT_READ_LINE_LIMIT
        return _read_result_for_path(
            self._fs,
            normalized,
            offset=offset,
            limit=line_limit,
            display_path=path,
        )

    async def aread(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        normalized = self._normalize_path(path)
        line_limit = limit if limit is not None else _DEFAULT_READ_LINE_LIMIT
        return _read_result_for_path(
            self._fs,
            normalized,
            offset=offset,
            limit=line_limit,
            display_path=path,
        )

    def write(self, path: str, content: str | bytes) -> WriteResult:
        from soothe_nano.filesystem.exceptions import FilesystemError

        normalized = self._normalize_path(path)
        try:
            result = self._fs.write(normalized, content)
        except FilesystemError as exc:
            return WriteResult(error=str(exc))
        return WriteResult(path=result.path)

    async def awrite(self, path: str, content: str | bytes) -> WriteResult:
        from soothe_nano.filesystem.exceptions import FilesystemError

        normalized = self._normalize_path(path)
        try:
            result = await self._fs.awrite(normalized, content)
        except FilesystemError as exc:
            return WriteResult(error=str(exc))
        return WriteResult(path=result.path)

    def edit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        *,
        edits: list[dict[str, Any]] | None = None,
    ) -> EditResult:
        # Positional order matches BackendProtocol:
        # edit(path, old_string, new_string, replace_all=False).
        # Batch `edits` is a nano extension and must stay keyword-only.
        normalized = self._normalize_path(path)
        try:
            if edits is not None:
                if isinstance(edits, str):
                    return EditResult(
                        error=(
                            "Invalid edits argument (got str); pass "
                            "old_string/new_string positionally or edits=[dict, ...]"
                        )
                    )
                total_occurrences = 0
                for edit_item in edits:
                    if not isinstance(edit_item, dict):
                        return EditResult(
                            error=(
                                f"Invalid edit item (expected dict, got {type(edit_item).__name__})"
                            )
                        )
                    old = edit_item.get("old_string", "")
                    new = edit_item.get("new_string", "")
                    item_replace_all = bool(edit_item.get("replace_all", False))
                    result = self._fs.edit(normalized, old, new, replace_all=item_replace_all)
                    if hasattr(result, "error") and result.error:
                        return EditResult(error=result.error)
                    total_occurrences += int(getattr(result, "occurrences", None) or 1)
                return EditResult(path=normalized, occurrences=total_occurrences)
            if old_string is not None and new_string is not None:
                result = self._fs.edit(normalized, old_string, new_string, replace_all=replace_all)
                if hasattr(result, "error") and result.error:
                    return EditResult(error=result.error)
                return EditResult(
                    path=normalized,
                    occurrences=int(getattr(result, "occurrences", None) or 1),
                )
            return EditResult(error="No edits provided")
        except Exception as e:
            logger.warning("edit error for %s: %s", path, e)
            return EditResult(error=str(e))

    async def aedit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        *,
        edits: list[dict[str, Any]] | None = None,
    ) -> EditResult:
        normalized = self._normalize_path(path)
        try:
            if edits is not None:
                if isinstance(edits, str):
                    return EditResult(
                        error=(
                            "Invalid edits argument (got str); pass "
                            "old_string/new_string positionally or edits=[dict, ...]"
                        )
                    )
                total_occurrences = 0
                for edit_item in edits:
                    if not isinstance(edit_item, dict):
                        return EditResult(
                            error=(
                                f"Invalid edit item (expected dict, got {type(edit_item).__name__})"
                            )
                        )
                    old = edit_item.get("old_string", "")
                    new = edit_item.get("new_string", "")
                    item_replace_all = bool(edit_item.get("replace_all", False))
                    result = await self._fs.aedit(
                        normalized, old, new, replace_all=item_replace_all
                    )
                    if hasattr(result, "error") and result.error:
                        return EditResult(error=result.error)
                    total_occurrences += int(getattr(result, "occurrences", None) or 1)
                return EditResult(path=normalized, occurrences=total_occurrences)
            if old_string is not None and new_string is not None:
                result = await self._fs.aedit(
                    normalized, old_string, new_string, replace_all=replace_all
                )
                if hasattr(result, "error") and result.error:
                    return EditResult(error=result.error)
                return EditResult(
                    path=normalized,
                    occurrences=int(getattr(result, "occurrences", None) or 1),
                )
            return EditResult(error="No edits provided")
        except Exception as e:
            logger.warning("aedit error for %s: %s", path, e)
            return EditResult(error=str(e))

    async def aedit_batched(
        self,
        path: str,
        operations: list[Any],
        *,
        backup: bool = True,
    ) -> Any:
        from soothe_deepagents.backends.protocol import BatchedEditResult

        normalized = self._normalize_path(path)
        try:
            return await self._fs.aedit_batched(normalized, operations, backup=backup)
        except Exception as e:
            logger.warning("aedit_batched error for %s: %s", path, e)
            return BatchedEditResult(path=normalized, error=str(e))

    def ls(self, path: str = ".") -> LsResult:
        normalized = self._normalize_path(path)
        try:
            result = self._fs.ls(normalized, include_info=True)
            entries: list[dict[str, Any]] = []
            if isinstance(result, list) and result:
                for item in result:
                    if isinstance(item, dict):
                        entries.append(
                            {
                                "path": item.get("path", ""),
                                "is_dir": bool(item.get("is_dir", False)),
                                "size": item.get("size", 0),
                                "modified_at": item.get("modified_at"),
                            }
                        )
                    elif isinstance(item, str):
                        entries.append({"path": item, "is_dir": False})
                    else:
                        modified = getattr(item, "modified_at", None)
                        entries.append(
                            {
                                "path": item.path,
                                "is_dir": item.is_dir,
                                "size": item.size,
                                "modified_at": (
                                    modified.isoformat()
                                    if hasattr(modified, "isoformat")
                                    else modified
                                ),
                            }
                        )
            return LsResult(entries=entries)
        except Exception as e:
            logger.warning("ls error for %s: %s", path, e)
            return LsResult(error=str(e), entries=[])

    async def als(self, path: str = ".") -> LsResult:
        normalized = self._normalize_path(path)
        try:
            result = await self._fs.als(normalized, include_info=True)
            entries: list[dict[str, Any]] = []
            if isinstance(result, list) and result:
                for item in result:
                    if isinstance(item, dict):
                        entries.append(
                            {
                                "path": item.get("path", ""),
                                "is_dir": bool(item.get("is_dir", False)),
                                "size": item.get("size", 0),
                                "modified_at": item.get("modified_at"),
                            }
                        )
                    elif isinstance(item, str):
                        entries.append({"path": item, "is_dir": False})
                    else:
                        modified = getattr(item, "modified_at", None)
                        entries.append(
                            {
                                "path": item.path,
                                "is_dir": item.is_dir,
                                "size": item.size,
                                "modified_at": (
                                    modified.isoformat()
                                    if hasattr(modified, "isoformat")
                                    else modified
                                ),
                            }
                        )
            return LsResult(entries=entries)
        except Exception as e:
            logger.warning("als error for %s: %s", path, e)
            return LsResult(error=str(e), entries=[])

    def glob(self, pattern: str, path: str = "/") -> Any:
        from soothe_deepagents.backends.protocol import GlobResult

        normalized = self._normalize_path(path)
        result = self._fs.glob(pattern, path=normalized)
        file_infos: list[dict[str, Any]] = []
        for item in result.matches or []:
            if isinstance(item, dict):
                file_infos.append(
                    {"path": item.get("path", ""), "is_dir": bool(item.get("is_dir", False))}
                )
            else:
                file_infos.append({"path": str(item), "is_dir": False})
        return GlobResult(error=result.error, matches=file_infos)

    async def aglob(self, pattern: str, path: str = "/") -> Any:
        from soothe_deepagents.backends.protocol import GlobResult

        normalized = self._normalize_path(path)
        result = await self._fs.aglob(pattern, path=normalized)
        file_infos: list[dict[str, Any]] = []
        for item in result.matches or []:
            if isinstance(item, dict):
                file_infos.append(
                    {"path": item.get("path", ""), "is_dir": bool(item.get("is_dir", False))}
                )
            else:
                file_infos.append({"path": str(item), "is_dir": False})
        return GlobResult(error=result.error, matches=file_infos)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        output_mode: str = "content",
    ) -> Any:
        """Search files; positional order matches BackendProtocol.grep.

        ``output_mode`` is a nano extension and must stay keyword-only so it cannot
        steal ``glob``. Default is ``content`` because deepagents middleware formats
        tool output itself and expects line matches with text.
        """
        from soothe_deepagents.backends.protocol import GrepResult

        search_path = "." if path is None else path
        normalized = self._normalize_path(search_path)
        try:
            result = self._fs.grep(pattern, path=normalized, glob=glob, output_mode=output_mode)
            if isinstance(result, GrepResult):
                return result
            return GrepResult(error=None, matches=_grep_matches_for_backend(result))
        except Exception as e:
            logger.warning("grep error for %s: %s", search_path, e)
            return GrepResult(error=str(e), matches=None)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        output_mode: str = "content",
    ) -> Any:
        from soothe_deepagents.backends.protocol import GrepResult

        search_path = "." if path is None else path
        normalized = self._normalize_path(search_path)
        try:
            result = await self._fs.agrep(
                pattern, path=normalized, glob=glob, output_mode=output_mode
            )
            if isinstance(result, GrepResult):
                return result
            return GrepResult(error=None, matches=_grep_matches_for_backend(result))
        except Exception as e:
            logger.warning("agrep error for %s: %s", search_path, e)
            return GrepResult(error=str(e), matches=None)

    def delete(self, path: str, *, backup: bool = False) -> DeleteResult:
        _ = backup
        normalized = self._normalize_path(path)
        try:
            self._fs.delete(normalized)
        except Exception as exc:
            return DeleteResult(error=str(exc))
        return DeleteResult(path=normalized)

    async def adelete(self, path: str, *, backup: bool = False) -> DeleteResult:
        _ = backup
        normalized = self._normalize_path(path)
        try:
            await self._fs.adelete(normalized)
        except Exception as exc:
            return DeleteResult(error=str(exc))
        return DeleteResult(path=normalized)

    def download_files(self, paths: list[str]) -> list[Any]:
        from soothe_deepagents.backends.protocol import FileDownloadResponse

        responses: list[Any] = []
        for path in paths:
            try:
                resolved = self.resolve_os_path(path)
                if resolved.is_dir():
                    responses.append(
                        FileDownloadResponse(path=path, content=None, error="is_directory")
                    )
                    continue
                if not resolved.exists() or not resolved.is_file():
                    responses.append(
                        FileDownloadResponse(path=path, content=None, error="file_not_found")
                    )
                    continue
                responses.append(
                    FileDownloadResponse(path=path, content=resolved.read_bytes(), error=None)
                )
            except OSError as exc:
                responses.append(FileDownloadResponse(path=path, content=None, error=str(exc)))
        return responses

    async def adownload_files(self, paths: list[str]) -> list[Any]:
        import asyncio

        return await asyncio.to_thread(self.download_files, paths)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[Any]:
        from soothe_deepagents.backends.protocol import FileUploadResponse

        responses: list[Any] = []
        for path, content in files:
            try:
                resolved = self.resolve_os_path(path)
                if resolved.exists() and resolved.is_dir():
                    responses.append(FileUploadResponse(path=path, error="is_directory"))
                    continue
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_bytes(content)
                responses.append(FileUploadResponse(path=path, error=None))
            except OSError as exc:
                responses.append(FileUploadResponse(path=path, error=str(exc)))
        return responses

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[Any]:
        import asyncio

        return await asyncio.to_thread(self.upload_files, files)

    def exists(self, path: str) -> bool:
        return self._fs.exists(self._normalize_path(path))

    def is_file(self, path: str) -> bool:
        return self._fs.is_file(self._normalize_path(path))

    def is_dir(self, path: str) -> bool:
        return self._fs.is_dir(self._normalize_path(path))


class WorkspaceAwareBackend(BackendProtocol):
    """Filesystem backend that resolves workspace from ContextVar / defaults.

    Pass the instance directly to middleware (`backend=WorkspaceAwareBackend(...)`).
    Do not use the deprecated callable-factory `backend` form; workspace switching
    is handled via ContextVar in `_get_backend` and by `SootheFilesystemMiddleware`.
    """

    def __init__(
        self,
        default_root_dir: Path,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        self._default_root_dir = default_root_dir
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb
        self._default_backend = NormalizedPathBackend(
            root_dir=default_root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    @property
    def virtual_mode(self) -> bool:
        """Sandbox mode fixed at construction (independent of host config objects)."""
        return self._virtual_mode

    def bind_workspace(self, workspace: Path | str) -> None:
        """Bind the active workspace for subsequent filesystem tool calls.

        Called by deepagents ``FilesystemMiddleware`` from tool runtime so nested
        ``task`` children resolve the parent project root without host config objects.
        """
        from soothe_nano.workspace.workspace_runtime import set_workspace_context

        ws_path = Path(workspace).expanduser().resolve()
        set_workspace_context(workspace=ws_path, virtual_mode=self._virtual_mode)

    def _get_backend(self) -> NormalizedPathBackend:
        from soothe_nano.workspace.workspace_policy import resolve_workspace_for_tool_execution
        from soothe_nano.workspace.workspace_runtime import (
            get_workspace_context,
            set_workspace_context,
        )

        current_workspace = get_workspace_context().workspace
        if current_workspace is None:
            # Nested task graphs and some tool hops may lack ContextVar binding;
            # resolve from langgraph configurable / state before process default.
            resolved = resolve_workspace_for_tool_execution(use_langgraph_config=True)
            if resolved is not None:
                current_workspace = Path(resolved).expanduser().resolve()
                set_workspace_context(
                    workspace=current_workspace,
                    virtual_mode=self._virtual_mode,
                )
        if current_workspace:
            return get_workspace_backend(
                workspace=current_workspace,
                virtual_mode=self._virtual_mode,
                max_file_size_mb=self._max_file_size_mb,
            )
        return self._default_backend

    def read(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        return self._get_backend().read(path, offset, limit)

    async def aread(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        return await self._get_backend().aread(path, offset, limit)

    def write(self, path: str, content: str | bytes) -> WriteResult:
        return self._get_backend().write(path, content)

    async def awrite(self, path: str, content: str | bytes) -> WriteResult:
        return await self._get_backend().awrite(path, content)

    def edit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        *,
        edits: list[dict[str, Any]] | None = None,
    ) -> EditResult:
        # Positional order must match BackendProtocol / deepagents middleware:
        # edit(path, old_string, new_string, replace_all=...).
        # Batch `edits` is keyword-only so it cannot steal replace_all's slot.
        if edits is not None:
            return self._get_backend().edit(path, replace_all=replace_all, edits=edits)
        return self._get_backend().edit(
            path, old_string=old_string, new_string=new_string, replace_all=replace_all
        )

    async def aedit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        *,
        edits: list[dict[str, Any]] | None = None,
    ) -> EditResult:
        if edits is not None:
            return await self._get_backend().aedit(path, replace_all=replace_all, edits=edits)
        return await self._get_backend().aedit(
            path, old_string=old_string, new_string=new_string, replace_all=replace_all
        )

    def ls(self, path: str = ".") -> LsResult:
        return self._get_backend().ls(path)

    async def als(self, path: str = ".") -> LsResult:
        return await self._get_backend().als(path)

    def glob(self, pattern: str, path: str = "/") -> Any:
        return self._get_backend().glob(pattern, path)

    async def aglob(self, pattern: str, path: str = "/") -> Any:
        return await self._get_backend().aglob(pattern, path)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        output_mode: str = "content",
    ) -> Any:
        return self._get_backend().grep(pattern, path, glob, output_mode=output_mode)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        output_mode: str = "content",
    ) -> Any:
        return await self._get_backend().agrep(pattern, path, glob, output_mode=output_mode)

    def delete(self, path: str, *, backup: bool = False) -> DeleteResult:
        return self._get_backend().delete(path, backup=backup)

    async def adelete(self, path: str, *, backup: bool = False) -> DeleteResult:
        return await self._get_backend().adelete(path, backup=backup)

    def download_files(self, paths: list[str]) -> list[Any]:
        return self._get_backend().download_files(paths)

    async def adownload_files(self, paths: list[str]) -> list[Any]:
        return await self._get_backend().adownload_files(paths)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[Any]:
        return self._get_backend().upload_files(files)

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[Any]:
        return await self._get_backend().aupload_files(files)


_backend_cache: dict[str, NormalizedPathBackend] = {}


def get_workspace_backend(
    workspace: Path,
    virtual_mode: bool = False,
    max_file_size_mb: int = 10,
) -> NormalizedPathBackend:
    """Get or create a cached NormalizedPathBackend for a workspace."""
    cache_key = f"{workspace}:{virtual_mode}:{max_file_size_mb}"
    if cache_key not in _backend_cache:
        _backend_cache[cache_key] = NormalizedPathBackend(
            root_dir=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
    return _backend_cache[cache_key]


def clear_workspace_backend_cache() -> None:
    """Clear the workspace backend cache."""
    _backend_cache.clear()


class FrameworkFilesystem:
    """Singleton filesystem backend for framework operations."""

    _instance: BackendProtocol | None = None

    @classmethod
    def initialize(
        cls,
        config: SootheConfig,
        policy: object | None = None,
    ) -> BackendProtocol:
        from soothe_nano.workspace.workspace_paths import (
            config_workspace_root,
            max_file_size_mb_for_filesystem_backend,
        )
        from soothe_nano.workspace.workspace_runtime import resolve_process_workspace_root

        configured_root = config_workspace_root(config)
        resolved_workspace = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else resolve_process_workspace_root()
        )
        virtual_mode = not config.security.allow_paths_outside_workspace
        max_file_size_mb = max_file_size_mb_for_filesystem_backend(config)
        cls._instance = WorkspaceAwareBackend(
            default_root_dir=resolved_workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        logger.info(
            "FrameworkFilesystem initialized: root=%s virtual_mode=%s (workspace-aware)",
            resolved_workspace,
            virtual_mode,
        )
        return cls._instance

    @classmethod
    def get(cls) -> BackendProtocol:
        if cls._instance is None:
            raise RuntimeError("FrameworkFilesystem not initialized. Call initialize() first.")
        return cls._instance

    @classmethod
    def set_current_workspace(cls, workspace: Path | str) -> Token:
        from soothe_nano.workspace.workspace_runtime import (
            get_workspace_context,
            set_workspace_context,
        )

        ws_path = Path(workspace) if isinstance(workspace, str) else workspace
        ctx = get_workspace_context()
        return set_workspace_context(workspace=ws_path, virtual_mode=ctx.virtual_mode)

    @classmethod
    def get_current_workspace(cls) -> Path | None:
        from soothe_nano.workspace.workspace_runtime import get_workspace_context

        return get_workspace_context().workspace

    @classmethod
    def clear_current_workspace(cls, token: Token | None = None) -> None:
        from soothe_nano.workspace.workspace_runtime import reset_workspace_context

        reset_workspace_context(token)
