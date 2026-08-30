"""Chrome DevTools Protocol (CDP) discovery utilities.

Provides functions to discover and clean up stale soothe-owned
Chrome processes that would block new launches via SingletonLock.

Process discovery is cross-platform: it prefers `psutil` (no shell,
works identically on Linux and macOS) and falls back to a
platform-aware `ps` invocation via :mod:`subprocess`.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import signal
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CDP_PORTS = [9222, 9242, 9223, 9333]
"""Well-known ports to try before falling back to process discovery."""

# Known Chrome/Chromium/Electron/Edge/Brave executable names (basenames).
# Compared case-insensitively against the OS-reported process name
# (psutil) or the executable path basename (subprocess fallback).
_CHROME_EXE_NAMES = frozenset(
    {
        "google chrome",
        "google chrome helper",
        "google chrome helper (renderer)",
        "google chrome helper (gpu)",
        "google chrome helper (plugin)",
        "chrome",
        "chromium",
        "chromium-browser",
        "chromium-browser-lite",
        "microsoft edge",
        "microsoft edge helper",
        "msedge",
        "edge",
        "electron",
        "electron helper",
        "electron helper (renderer)",
        "electron helper (gpu)",
        "brave",
        "brave-browser",
    }
)


def _exe_name_is_chrome_like(exe_name: str) -> bool:
    """Return True if an executable basename is a known Chrome/Electron name.

    `exe_name` is matched case-insensitively against
    :data:`_CHROME_EXE_NAMES`. A bare `chrome` / `electron` token
    embedded as a *word* in the name also counts so that macOS
    app-bundle names like `Google Chrome Helper (Renderer)` match,
    without false-matching `edge` inside `knowledge-agent`.
    """
    if not exe_name:
        return False
    lowered = exe_name.lower()
    if lowered in _CHROME_EXE_NAMES:
        return True
    # Catch macOS helper variants and localized names without enumerating
    # every permutation: any known basename appearing as a word (bounded
    # by a non-alphanumeric char or string end) in the OS-reported name
    # (e.g. "google chrome helper (renderer)"). Word-bounding avoids
    # matching "edge" inside "knowledge-agent".
    return any(
        re.search(r"(?:^|[^a-z0-9])" + re.escape(name) + r"(?:[^a-z0-9]|$)", lowered)
        for name in ("chrome", "chromium", "electron", "edge", "brave")
    )


def _extract_exe_path_from_args(args: str) -> str:
    """Extract the executable path from a ps cmdline string.

    `ps` output is `"<pid> <exe-and-flags>"` after the PID is
    stripped. The executable may contain spaces (macOS app bundles),
    so we accumulate leading tokens until the first token that starts
    with `-` (a flag). Returns the joined executable path, or `""`.
    """
    tokens = args.split()
    exe_tokens: list[str] = []
    for tok in tokens:
        if tok.startswith("-"):
            break
        exe_tokens.append(tok)
    return " ".join(exe_tokens)


def _is_chrome_like_process(proc_info: dict[str, str]) -> bool:
    """Return True if the process looks like Chrome/Electron.

    A process is relevant if it was launched with
    `--remote-debugging-port` AND its executable name matches a known
    Chrome/Chromium/Electron/Edge/Brave basename. This filters out
    unrelated processes that happen to pass the debugging flag while
    keeping Electron apps that embed CDP.
    """
    args = proc_info.get("args", "")
    if "--remote-debugging-port=" not in args:
        return False
    exe_name = proc_info.get("exe_name", "") or _extract_exe_path_from_args(args)
    return _exe_name_is_chrome_like(exe_name)


def _list_chrome_processes_psutil() -> list[dict[str, str]] | None:
    """List Chrome processes via psutil.

    Returns `None` if psutil is unavailable, so the caller can fall
    back to subprocess. Uses cmdline reconstruction which is portable
    across Linux (/proc) and macOS (libproc).
    """
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return None

    processes: list[dict[str, str]] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline_list = proc.info.get("cmdline") or []
            args = " ".join(cmdline_list)
            exe_name = proc.info.get("name") or ""
            # On macOS (sandbox/SIP) psutil often returns an empty
            # cmdline for Chrome processes, so we cannot require the
            # --remote-debugging-port flag here. Instead we gate on the
            # executable name and parse port/udd opportunistically.
            if not _exe_name_is_chrome_like(exe_name):
                continue
            udd_match = re.search(r"--user-data-dir=(\S+)", args)
            port_match = re.search(r"--remote-debugging-port=(\d+)", args)
            entry: dict[str, str] = {
                "pid": str(proc.info.get("pid", "")),
                "args": args,
                "exe_name": exe_name,
                "user_data_dir": udd_match.group(1) if udd_match else "",
                "debug_port": port_match.group(1) if port_match else "",
            }
            processes.append(entry)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:  # noqa: BLE001 - defensive per-process isolation
            logger.debug("psutil: error reading process %s", proc.pid, exc_info=True)
            continue
    return processes


def _list_chrome_processes_subprocess() -> list[dict[str, str]]:
    """List Chrome processes via a platform-aware `ps` invocation.

    Uses `ps -ax -o pid=,args=` on macOS (BSD ps) and `ps -e -o
    pid=,args=` on Linux (procps). Resolves `ps` via `shutil.which`
    rather than hard-coding `/bin/ps` so it works on systems where ps
    lives in `/usr/bin/ps`.
    """
    processes: list[dict[str, str]] = []
    import shutil

    ps_bin = shutil.which("ps")
    if not ps_bin:
        logger.debug("ps binary not found on PATH")
        return processes

    is_mac = platform.system() == "Darwin"
    # BSD ps (macOS) accepts `ax`; procps (Linux) prefers `-e`. Both
    # support `-o pid=,args=` to suppress headers.
    ps_args = ["ax"] if is_mac else ["-e"]

    try:
        result = subprocess.run(
            [ps_bin, *ps_args, "-o", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        logger.debug("Failed to list Chrome processes via subprocess", exc_info=True)
        return processes

    for raw_line in result.stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) < 2:  # noqa: PLR2004
            continue
        pid_str, args = parts
        entry = {
            "pid": pid_str.strip(),
            "args": args,
            "user_data_dir": "",
            "debug_port": "",
        }
        if not _is_chrome_like_process(entry):
            continue
        udd_match = re.search(r"--user-data-dir=(\S+)", args)
        port_match = re.search(r"--remote-debugging-port=(\d+)", args)
        entry["user_data_dir"] = udd_match.group(1) if udd_match else ""
        entry["debug_port"] = port_match.group(1) if port_match else ""
        processes.append(entry)
    return processes


def _list_chrome_processes() -> list[dict[str, str]]:
    """List Chrome/Electron processes with PID, args, and metadata.

    Tries the platform-aware `ps` subprocess first (yields full
    argv including `--remote-debugging-port` / `--user-data-dir`
    on both Linux and macOS), then falls back to `psutil` which
    works without a shell but may return empty `cmdline` for
    sandboxed processes on macOS. Returns dicts with keys: `pid`,
    `args`, `exe_name`, `user_data_dir`, `debug_port`.
    """
    ps_result = _list_chrome_processes_subprocess()
    if ps_result:
        return ps_result
    psutil_result = _list_chrome_processes_psutil()
    return psutil_result or []


def find_soothe_chrome_processes(user_data_dir: str) -> list[dict[str, str]]:
    """Find Chrome processes launched with a specific user-data-dir.

    Args:
        user_data_dir: The soothe browser profile directory to match.

    Returns:
        List of process info dicts for matching Chrome processes.
    """
    canonical = os.path.realpath(user_data_dir)
    matches = []
    for proc in _list_chrome_processes():
        proc_udd = proc.get("user_data_dir", "")
        if proc_udd and os.path.realpath(proc_udd) == canonical:
            matches.append(proc)
    return matches


def cleanup_stale_chrome(user_data_dir: str) -> int:
    """Kill stale Chrome processes that are using a specific user-data-dir.

    This prevents SingletonLock conflicts when launching a new browser session.
    Only kills processes whose `--user-data-dir` matches the given path.

    Args:
        user_data_dir: The soothe browser profile directory.

    Returns:
        Number of processes killed.
    """
    stale = find_soothe_chrome_processes(user_data_dir)
    killed = 0
    for proc in stale:
        pid = int(proc["pid"])
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
            logger.info(
                "Killed stale Chrome process PID %d (port %s, user-data-dir=%s)",
                pid,
                proc.get("debug_port", "?"),
                proc.get("user_data_dir", "?"),
            )
        except ProcessLookupError:
            logger.debug("Chrome PID %d already gone", pid)
        except PermissionError:
            logger.warning("No permission to kill Chrome PID %d", pid)
    if killed:
        _remove_stale_singleton_lock(user_data_dir)
    return killed


def _pid_is_alive(pid: int) -> bool:
    """Return True if `pid` refers to a running process.

    Uses `os.kill(pid, 0)` for a zero-dependency liveness check that
    works on both Linux and macOS.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — treat as alive so we
        # do not clobber another user's live SingletonLock.
        return True
    return True


def _remove_stale_singleton_lock(user_data_dir: str) -> None:
    """Remove the SingletonLock symlink if it belongs to a dead process.

    Chromium's `SingletonLock` is a symlink whose target is
    `<hostname>-<pid>`. Only remove it when that owning PID is no
    longer alive; otherwise unlinking would corrupt a live session
    on multi-user macOS/Linux hosts.
    """
    lock_path = Path(user_data_dir) / "SingletonLock"
    try:
        if not (lock_path.is_symlink() or lock_path.exists()):
            return
        # Validate ownership before unlinking. If the symlink target
        # encodes a PID and that PID is still running, leave the lock
        # alone to avoid corrupting a live browser session.
        if lock_path.is_symlink():
            target = os.readlink(lock_path)
            owner_pid = _parse_singleton_owner_pid(target)
            if owner_pid is not None and _pid_is_alive(owner_pid):
                logger.debug(
                    "SingletonLock at %s still owned by live PID %d; leaving intact",
                    lock_path,
                    owner_pid,
                )
                return
        lock_path.unlink()
        logger.debug("Removed stale SingletonLock at %s", lock_path)
    except OSError as e:
        logger.debug("Could not remove SingletonLock at %s: %s", lock_path, e)


def _parse_singleton_owner_pid(symlink_target: str) -> int | None:
    """Extract the owning PID from a Chromium SingletonLock symlink target.

    Chromium writes the target as `<hostname>-<pid>`. This extracts
    the trailing integer PID. Returns `None` if no PID can be parsed
    (in which case the caller should NOT assume the lock is stale).
    """
    # Hostnames may contain hyphens, so match the final hyphen-delimited
    # numeric tail.
    match = re.search(r"-(\d+)$", symlink_target)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None
