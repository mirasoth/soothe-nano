"""Chrome DevTools Protocol (CDP) discovery utilities.

Provides functions to discover and clean up stale soothe-owned
Chrome processes that would block new launches via SingletonLock.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CDP_PORTS = [9222, 9242, 9223, 9333]
"""Well-known ports to try before falling back to process discovery."""


def _list_chrome_processes() -> list[dict[str, str]]:
    """List Chrome processes with their PID, args, and extracted metadata.

    Returns:
        List of dicts with keys: pid, args, user_data_dir, debug_port.
    """
    processes: list[dict[str, str]] = []
    try:
        result = subprocess.run(
            ["/bin/ps", "ax", "-o", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        logger.debug("Failed to list Chrome processes", exc_info=True)
        return processes

    for raw_line in result.stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped or "--remote-debugging-port=" not in stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) < 2:  # noqa: PLR2004
            continue
        pid_str, args = parts
        udd_match = re.search(r"--user-data-dir=(\S+)", args)
        port_match = re.search(r"--remote-debugging-port=(\d+)", args)
        processes.append(
            {
                "pid": pid_str.strip(),
                "args": args,
                "user_data_dir": udd_match.group(1) if udd_match else "",
                "debug_port": port_match.group(1) if port_match else "",
            }
        )
    return processes


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
    Only kills processes whose ``--user-data-dir`` matches the given path.

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


def _remove_stale_singleton_lock(user_data_dir: str) -> None:
    """Remove the SingletonLock symlink if present."""
    lock_path = Path(user_data_dir) / "SingletonLock"
    try:
        if lock_path.is_symlink() or lock_path.exists():
            lock_path.unlink()
            logger.debug("Removed stale SingletonLock at %s", lock_path)
    except OSError as e:
        logger.debug("Could not remove SingletonLock at %s: %s", lock_path, e)
