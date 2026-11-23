"""os_sandbox backend: local OS-primitive sandbox for KVM-less hosts.

Tiers: macOS Seatbelt; Linux bubblewrap + seccomp (full tier); Landlock
(opt-in degraded tier — file-access denial only). Identity path mapping:
guest paths are host paths and background PIDs stay host-visible, so the
shell toolkit's ``kill_process`` / ``tail_background_log`` semantics work
without any pid mapping.
"""

from __future__ import annotations

import atexit
import contextlib
import ctypes
import logging
import os
import platform
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from soothe_deepagents.backends.protocol import (
    FILE_NOT_FOUND,
    INVALID_PATH,
    IS_DIRECTORY,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from soothe_deepagents.backends.sandbox import BaseSandbox

from soothe_nano.config.models import OsLocalSandboxConfig

logger = logging.getLogger(__name__)

__all__ = [
    "OsLocalSandbox",
    "OsSandboxCapabilityError",
    "OsSandboxConfigError",
    "OsSandboxError",
    "OsSandboxTier",
]

OsSandboxTier = Literal["seatbelt", "bwrap", "landlock"]

_BWRAP_PROBE_TIMEOUT = 5.0

# Per-stream output cap for ``execute`` — a backend-level safety net for raw
# callers (tool-layer truncation and the 10 MiB guest-side capture offload in
# ``BaseSandbox`` handle the model-facing paths). Must stay strictly above
# ``BaseSandbox._EXECUTE_CAPTURE_MAX_BYTES`` so offloaded reads are never
# clipped here. When the cap is hit the process group is killed and the
# response carries a truncation note.
_EXECUTE_CAPTURE_CAP_BYTES = 16 * 1024 * 1024

# Seatbelt read-isolation set (parity with the bwrap bind list):
# - ``_SEATBELT_READ_TREES``: system prefixes readable in full. Everything
#   else (other users' data under ``/Users``, ``/private/var/db``, package
#   roots under ``/Applications``, host ``/private/tmp``, ...) is denied.
#   ``/opt`` stands in for the Linux ``/usr/local`` bind (homebrew prefix).
# - ``_SEATBELT_METADATA_ROOTS``: firmlink/volume roots that need
#   ``file-read-metadata`` for path resolution (``/etc`` -> ``/private/etc``,
#   ...). Data reads of anything outside the read trees stay denied.
# - ``/private/var/select``: the shell-selection symlink tree macOS consults
#   when exec'ing ``/bin/sh`` (macOS-specific, no bwrap analog).
# - entropy devices (``/dev/urandom`` ...) are readable: interpreters read
#   them at startup (``_Py_HashRandomization_Init``).
_SEATBELT_METADATA_ROOTS: tuple[str, ...] = (
    "/",
    "/dev",
    "/etc",
    "/opt",
    "/private",
    "/tmp",
    "/Users",
    "/var",
)
_SEATBELT_READ_TREES: tuple[str, ...] = (
    "/Library",
    "/System",
    "/bin",
    "/opt",
    "/private/etc",
    "/private/var/select",
    "/sbin",
    "/usr",
)

# bwrap spawn strategy, resolved once per process (see _bwrap_spawn_prefix).
_BWRAP_SPAWN_PREFIX: list[str] | None = None
_bwrap_prefix_lock = threading.Lock()

# Landlock syscall numbers (identical across supported architectures).
_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_CREATE_RULESET_VERSION = 1

# seccomp(2) syscall numbers and AUDIT_ARCH values per supported arch.
_SECCOMP_NR: dict[str, int] = {"x86_64": 317, "aarch64": 277}
_AUDIT_ARCH: dict[str, int] = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}

_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO_ENOSYS = 0x00050000 | 38  # SECCOMP_RET_ERRNO | ENOSYS

# Namespace/privilege-escape syscalls denied by the seccomp filter. The
# default action is ENOSYS for unknown syscalls: libc falls back gracefully
# for benign newer syscalls (rseq, clone3 fallback, ...) while every denied
# syscall fails outright. Mount-ns + userns capability checks carry the
# boundary; this filter is defense in depth on top (no_new_privs is the
# load-bearing privilege-escalation block and is always applied first).
_SECCOMP_DENY_SYSCALLS: dict[str, tuple[int, ...]] = {
    "x86_64": (
        101,  # ptrace
        155,  # pivot_root
        163,  # acct
        165,  # mount
        166,  # umount2
        167,  # swapon
        168,  # swapoff
        169,  # reboot
        174,  # create_module
        175,  # init_module
        176,  # delete_module
        246,  # kexec_load
        248,  # add_key
        249,  # request_key
        250,  # keyctl
        272,  # unshare
        298,  # perf_event_open
        300,  # fanotify_init
        304,  # open_by_handle_at
        308,  # setns
        310,  # process_vm_readv
        311,  # process_vm_writev
        313,  # finit_module
        320,  # kexec_file_load
        321,  # bpf
        435,  # clone3
    ),
    "aarch64": (
        89,  # acct
        97,  # unshare
        104,  # kexec_load
        105,  # init_module
        106,  # delete_module
        117,  # ptrace
        142,  # reboot
        241,  # perf_event_open
        268,  # setns
        280,  # bpf
        435,  # clone3
        39,  # umount2
        40,  # mount
        41,  # pivot_root
    ),
}


class OsSandboxError(Exception):
    """os_sandbox backend failure."""


class OsSandboxCapabilityError(OsSandboxError):
    """The requested tier's OS prerequisites are missing (fail-loud)."""


class OsSandboxConfigError(OsSandboxError):
    """Invalid backend configuration (unbound workspace, egress surface)."""


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _native_arch() -> str | None:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    return None


def _bwrap_roundtrip(prefix: Sequence[str], proc_args: Sequence[str]) -> bool:
    """One real bwrap round-trip using the session's bind skeleton."""
    if shutil.which("bwrap") is None:
        return False
    if prefix and shutil.which("unshare") is None:
        return False
    argv = [
        *prefix,
        "bwrap",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind-try",
        "/usr/local",
        "/usr/local",
        "--ro-bind-try",
        "/bin",
        "/bin",
        "--ro-bind-try",
        "/lib",
        "/lib",
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--ro-bind-try",
        "/etc",
        "/etc",
        *proc_args,
        "--dev",
        "/dev",
        "true",
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=_BWRAP_PROBE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _bwrap_proc_args(prefix: Sequence[str]) -> list[str]:
    """proc mount strategy for the resolved spawn form.

    A fresh ``--proc`` mount is the default, but bwrap's sysrq-trigger probe
    fails on user-namespace-mounted proc (bwrap < 0.5) — the userns-wrapped
    spawn binds the host proc read-only instead. Visibility is equivalent:
    the PID namespace is never unshared (§5.3), so the process set is the
    same either way.
    """
    if prefix:
        return ["--ro-bind-try", "/proc", "/proc"]
    return ["--proc", "/proc"]


def _bwrap_spawn_prefix() -> list[str]:
    """argv prefix bwrap needs on this host (empty when bwrap runs direct).

    bubblewrap running as euid 0 skips its own user namespace and creates
    the mount namespace directly — EPERM on hosts that are root inside a
    container without CAP_SYS_ADMIN over the initial namespace (a common
    CI/dev-container shape). Wrapping bwrap in
    ``unshare --user --map-root-user`` hands it a userns to operate from.
    Detected empirically (a real round-trip, never a flag check), cached
    per process.
    """
    global _BWRAP_SPAWN_PREFIX
    with _bwrap_prefix_lock:
        if _BWRAP_SPAWN_PREFIX is not None:
            return _BWRAP_SPAWN_PREFIX
        prefix: list[str] = []
        if os.geteuid() == 0 and not _bwrap_roundtrip([], _bwrap_proc_args([])):
            nested = ["unshare", "--user", "--map-root-user"]
            if _bwrap_roundtrip(nested, _bwrap_proc_args(nested)):
                logger.info(
                    "os_sandbox: bwrap requires a userns wrapper on this host "
                    "(root without CAP_SYS_ADMIN over the initial namespace)"
                )
                prefix = nested
        _BWRAP_SPAWN_PREFIX = prefix
        return prefix


def _probe_bwrap() -> bool:
    """Real bwrap round-trip with the spawn form this process would use."""
    prefix = _bwrap_spawn_prefix()
    return _bwrap_roundtrip(prefix, _bwrap_proc_args(prefix))


def _probe_landlock() -> bool:
    """Fork a child that probes landlock_create_ruleset availability."""
    if sys.platform != "linux":
        return False
    pid = os.fork()
    if pid == 0:  # probe child: short-lived, no allocations beyond ctypes
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            ret = libc.syscall(
                ctypes.c_long(_LANDLOCK_CREATE_RULESET),
                ctypes.c_void_p(0),
                ctypes.c_size_t(0),
                ctypes.c_uint(_LANDLOCK_CREATE_RULESET_VERSION),
            )
            os._exit(0 if ret >= 0 else 1)
        except Exception:  # noqa: BLE001 -- probe child must never raise
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status) == 0


# ---------------------------------------------------------------------------
# seccomp filter (parent-side builder — unit-testable)
# ---------------------------------------------------------------------------


def _build_seccomp_bpf(arch: int, denied: Sequence[int]) -> bytes:
    """Classic-BPF seccomp filter: ENOSYS-deny `denied` syscalls and unknown archs.

    Layout: [LD arch][JEQ arch, else deny][LD nr][JEQ nr_i -> deny]*
    [RET allow][RET errno(ENOSYS)].
    """
    n = len(denied)
    ins: list[tuple[int, int, int, int]] = [
        (0x20, 0, 0, 4),  # LD W ABS: arch
        (0x15, 0, n + 2, arch),  # JEQ arch; else -> deny (jf = n + 2)
        (0x20, 0, 0, 0),  # LD W ABS: syscall nr
    ]
    for i, nr in enumerate(denied):
        ins.append((0x15, n - i, 0, nr))  # JEQ nr_i -> deny
    ins.append((0x06, 0, 0, _SECCOMP_RET_ALLOW))
    ins.append((0x06, 0, 0, _SECCOMP_RET_ERRNO_ENOSYS))
    return b"".join(struct.pack("<HBBI", *t) for t in ins)


# ---------------------------------------------------------------------------
# Embedded launchers (run inside the sandbox, before exec of the command)
# ---------------------------------------------------------------------------

_LAUNCHER_SECCOMP = r"""
import ctypes, os, sys
PR_SET_NO_NEW_PRIVS = 38
SECCOMP_SET_MODE_FILTER = 1
argv = sys.argv[1:]
bpf_hex, seccomp_nr = argv[0], argv[1]
rest = argv[2:]
if rest and rest[0] == "--":
    rest = rest[1:]
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
    sys.stderr.write("sandbox launcher: prctl(NO_NEW_PRIVS) failed errno=%d\n" % ctypes.get_errno())
    sys.exit(125)
raw = bytes.fromhex(bpf_hex)
count = len(raw) // 8
class _SF(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]
class _FP(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(_SF))]
filt = (_SF * count).from_buffer_copy(raw)
fprog = _FP(count, filt)
ret = libc.syscall(ctypes.c_long(int(seccomp_nr)), ctypes.c_int(SECCOMP_SET_MODE_FILTER), ctypes.c_int(0), ctypes.byref(fprog))
if ret != 0:
    sys.stderr.write("sandbox launcher: seccomp install failed errno=%d\n" % ctypes.get_errno())
    sys.exit(125)
os.execvp(rest[0], rest)
"""

_LAUNCHER_LANDLOCK = r"""
import ctypes, os, sys
PR_SET_NO_NEW_PRIVS = 38
LANDLOCK_RULE_PATH_BENEATH = 1
EXECUTE = 1 << 0
WRITE_FILE = 1 << 1
READ_FILE = 1 << 2
READ_DIR = 1 << 3
REMOVE_DIR = 1 << 4
REMOVE_FILE = 1 << 5
MAKE_CHAR = 1 << 6
MAKE_DIR = 1 << 7
MAKE_REG = 1 << 8
MAKE_SOCK = 1 << 9
MAKE_FIFO = 1 << 10
MAKE_BLOCK = 1 << 11
MAKE_SYM = 1 << 12
HANDLED = EXECUTE | WRITE_FILE | READ_FILE | READ_DIR | REMOVE_DIR | REMOVE_FILE | MAKE_CHAR | MAKE_DIR | MAKE_REG | MAKE_SOCK | MAKE_FIFO | MAKE_BLOCK | MAKE_SYM
READ_ONLY = READ_FILE | READ_DIR | EXECUTE
READ_WRITE = READ_FILE | READ_DIR | EXECUTE | WRITE_FILE | REMOVE_DIR | REMOVE_FILE | MAKE_DIR | MAKE_REG | MAKE_SOCK | MAKE_FIFO | MAKE_SYM
libc = ctypes.CDLL(None, use_errno=True)
class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]
class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]
if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
    sys.stderr.write("sandbox launcher: prctl(NO_NEW_PRIVS) failed\n")
    sys.exit(125)
attr = _RulesetAttr(HANDLED)
ruleset_fd = libc.syscall(ctypes.c_long(444), ctypes.byref(attr), ctypes.sizeof(attr), ctypes.c_int(0))
if ruleset_fd < 0:
    sys.stderr.write("sandbox launcher: landlock_create_ruleset failed errno=%d\n" % ctypes.get_errno())
    sys.exit(125)
def _allow(tree, access):
    try:
        parent_fd = os.open(tree, os.O_PATH | os.O_CLOEXEC)
    except OSError:
        return
    rule = _PathBeneathAttr(access, parent_fd)
    ret = libc.syscall(ctypes.c_long(445), ruleset_fd, ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH), ctypes.byref(rule), ctypes.c_int(0))
    os.close(parent_fd)
    if ret != 0:
        sys.stderr.write("sandbox launcher: landlock_add_rule failed for %s\n" % tree)
        sys.exit(125)
argv = sys.argv[1:]
workspace, scratch = argv[0], argv[1]
rest = argv[2:]
if rest and rest[0] == "--":
    rest = rest[1:]
for tree in ("/usr", "/lib", "/lib64", "/bin", "/etc", "/opt", "/dev", "/proc", "/sys"):
    _allow(tree, READ_ONLY)
for tree in (workspace, scratch):
    if tree:
        _allow(tree, READ_WRITE)
if libc.syscall(ctypes.c_long(446), ruleset_fd, ctypes.c_int(0)) != 0:
    sys.stderr.write("sandbox launcher: landlock_restrict_self failed\n")
    sys.exit(125)
os.close(ruleset_fd)
os.execvp(rest[0], rest)
"""


# ---------------------------------------------------------------------------
# Tier sessions (argv builders — pure, cross-platform testable)
# ---------------------------------------------------------------------------


def _namespace_interpreter() -> tuple[str, tuple[str, ...]]:
    """Interpreter for the in-namespace launcher (bwrap).

    Prefers the distro python (covered by the /usr bind); falls back to the
    running interpreter with its directory bound read-only.
    """
    plain = Path("/usr/bin/python3")
    if plain.exists():
        return str(plain), ()
    interp = Path(sys.executable).resolve()
    return str(interp), (str(interp.parent),)


def _seatbelt_quote(path: str) -> str:
    """Escape a path for a Seatbelt profile string literal."""
    return path.replace("\\", "\\\\").replace('"', '\\"')


def _seatbelt_ancestors(path: str) -> list[str]:
    """Ancestor directories of ``path`` that need metadata-only reads.

    Tools such as git lstat the whole cwd chain at startup; every ancestor of
    the workspace/scratch roots gets ``file-read-metadata`` (literal) so the
    cwd chain resolves. Directory listings and file data of the ancestors
    stay denied — only the ``lstat`` of the directory entry itself is
    permitted. Paths are resolved first: seatbelt checks firmlink-redirected
    paths (``/var`` -> ``/private/var``) in their resolved form.
    """
    resolved = str(Path(path).resolve())
    return [
        str(parent)
        for parent in Path(resolved).parents
        if str(parent) != "/" and str(parent) not in _SEATBELT_METADATA_ROOTS
    ]


class _SeatbeltSession:
    """macOS tier: static Seatbelt profile + `sandbox-exec` spawn.

    Boundary: writes, network, and signals are denied outside the
    workspace/scratch (deny default); reads are restricted to the system
    trees (bwrap-parity set, see ``_SEATBELT_READ_TREES``), the entropy
    devices, and the workspace/scratch — other users' data, host temp dirs,
    and package roots are unreadable. Path-resolution metadata (firmlink
    roots + workspace ancestors) is allowed because git and friends lstat
    the cwd chain; the root directory itself is listable (getcwd walks
    ``..``), exposing top-level names only.
    """

    def __init__(self, workspace: Path, scratch: Path) -> None:
        self._workspace = workspace
        self._scratch = scratch
        self._profile = self._build_profile()

    def _build_profile(self) -> str:
        # Seatbelt matches firmlink-redirected paths (/var -> /private/var)
        # in their resolved form — resolve before embedding in the profile.
        ws = str(self._workspace.resolve())
        scratch = str(self._scratch.resolve())
        metadata_literals = sorted(
            set(_SEATBELT_METADATA_ROOTS)
            | {a for path in (ws, scratch) for a in _seatbelt_ancestors(path)}
        )
        read_trees = sorted(set(_SEATBELT_READ_TREES) | {ws, scratch})
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process-exec)",
            "(allow process-fork)",
            # path resolution: lstat on firmlink/volume roots and the
            # workspace/scratch ancestor chain; data reads stay denied.
            "(allow file-read-metadata {})".format(
                " ".join(f'(literal "{_seatbelt_quote(p)}")' for p in metadata_literals)
            ),
            # getcwd walks parent directories — readdir of "/" (names only).
            '(allow file-read-data (literal "/"))',
            # system read trees + workspace/scratch (bwrap-parity set).
            "(allow file-read* {})".format(
                " ".join(f'(subpath "{_seatbelt_quote(p)}")' for p in read_trees)
            ),
            # entropy devices read at interpreter startup.
            '(allow file-read-data (literal "/dev/urandom") (literal "/dev/random")'
            ' (literal "/dev/null"))',
            f'(allow file-write* (subpath "{_seatbelt_quote(ws)}")'
            f' (subpath "{_seatbelt_quote(scratch)}"))',
            '(allow file-write-data (literal "/dev/null"))',
        ]
        return "\n".join(lines)

    def build_argv(self, command: str) -> list[str]:
        return ["sandbox-exec", "-p", self._profile, "/bin/sh", "-c", command]


class _BwrapSession:
    """Linux full tier: bwrap namespace + embedded seccomp launcher."""

    def __init__(self, workspace: Path, scratch: Path, *, spawn_prefix: Sequence[str] = ()) -> None:
        self._workspace = workspace
        self._scratch = scratch
        self._spawn_prefix = list(spawn_prefix)
        self._arch = _native_arch() or "x86_64"
        self._bpf = _build_seccomp_bpf(_AUDIT_ARCH[self._arch], _SECCOMP_DENY_SYSCALLS[self._arch])

    def build_argv(self, command: str) -> list[str]:
        interp, extra_binds = _namespace_interpreter()
        argv: list[str] = [
            *self._spawn_prefix,
            "bwrap",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind-try",
            "/usr/local",
            "/usr/local",
            "--ro-bind-try",
            "/bin",
            "/bin",
            "--ro-bind-try",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            "--ro-bind-try",
            "/etc",
            "/etc",
            *_bwrap_proc_args(self._spawn_prefix),
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            str(self._workspace),
            str(self._workspace),
            "--bind",
            str(self._scratch),
            str(self._scratch),
        ]
        for bind_dir in extra_binds:
            argv += ["--ro-bind-try", bind_dir, bind_dir]
        argv += [
            "--die-with-parent",
            "--new-session",
            "--unshare-net",
            interp,
            "-c",
            _LAUNCHER_SECCOMP,
            self._bpf.hex(),
            str(_SECCOMP_NR[self._arch]),
            "--",
            "/bin/sh",
            "-c",
            command,
        ]
        return argv


class _LandlockSession:
    """Linux degraded tier: Landlock file-access rules via embedded launcher."""

    def __init__(self, workspace: Path, scratch: Path) -> None:
        self._workspace = workspace
        self._scratch = scratch

    def build_argv(self, command: str) -> list[str]:
        return [
            sys.executable,
            "-c",
            _LAUNCHER_LANDLOCK,
            str(self._workspace),
            str(self._scratch),
            "--",
            "/bin/sh",
            "-c",
            command,
        ]


# ---------------------------------------------------------------------------
# Scratch cleanup + orphan process-group registry
# ---------------------------------------------------------------------------

_scratch_registry: set[str] = set()
_pgid_registry: set[int] = set()
_lifecycle_lock = threading.Lock()


def _register_scratch(path: str) -> None:
    with _lifecycle_lock:
        _scratch_registry.add(path)


def _unregister_scratch(path: str) -> None:
    with _lifecycle_lock:
        _scratch_registry.discard(path)


@atexit.register
def _cleanup_scratch_dirs() -> None:
    with _lifecycle_lock:
        dirs = list(_scratch_registry)
    for path in dirs:
        shutil.rmtree(path, ignore_errors=True)
        _unregister_scratch(path)


def _pgid_alive(pgid: int) -> bool:
    """True when the process group still has members (signal 0 probe)."""
    try:
        os.killpg(pgid, 0)
    except OSError:
        return False
    return True


def _kill_pgid(pgid: int) -> None:
    """SIGKILL a process group; a vanished group is not an error."""
    with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


@atexit.register
def _kill_live_process_groups() -> None:
    """Last-resort orphan cleanup on interpreter exit.

    Every ``execute`` runs in its own process group (``start_new_session``);
    groups that outlive their command (background children) are killed here
    and by ``OsLocalSandbox.close``. Hard interpreter death (SIGKILL, kernel
    panic) cannot be caught from userspace — the bwrap tier additionally
    carries kernel-level ``--die-with-parent`` for that case; seatbelt and
    landlock have no equivalent, which is the documented residual gap.
    """
    with _lifecycle_lock:
        pgids = list(_pgid_registry)
        _pgid_registry.clear()
    for pgid in pgids:
        _kill_pgid(pgid)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_output(stdout: str, stderr: str, note: str | None = None) -> str:
    parts = [p for p in (stdout, stderr, note) if p]
    return "\n".join(parts)


def _read_bounded(pipe: object, cap: int) -> tuple[bytes, bool]:
    """Drain a pipe up to ``cap`` bytes; never buffer more than the cap.

    Binary chunks are read as they arrive (no line buffering), so a stream
    without newlines still advances. When the cap is hit the reader stops —
    the caller kills the process group to unblock the writer.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = pipe.read(65536)  # type: ignore[attr-defined]
        if not chunk:
            break
        remaining = cap - total
        if len(chunk) > remaining:
            if remaining > 0:
                chunks.append(chunk[:remaining])
            total = cap
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= cap:
            break
    return b"".join(chunks), total >= cap


def _kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(OSError, ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def _posture_for_tier(tier: OsSandboxTier) -> str:
    """Landlock is a declared degraded tier — never ``full``."""
    return "subprocess_only" if tier == "landlock" else "full"


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class OsLocalSandbox(BaseSandbox):
    """Local OS-primitive sandbox backend implementing ``BaseSandbox``.

    Only the four abstract members are implemented; file operations are
    derived by the base class from sandboxed ``execute``. The workspace is
    bound with identity path mapping (guest paths are host paths); upload
    and download resolve paths against the bound roots and reject escapes.
    """

    enable_capture_offload = True

    def __init__(
        self,
        config: OsLocalSandboxConfig,
        *,
        popen: Callable[..., subprocess.Popen[bytes]] | None = None,
    ) -> None:
        self._config = config
        self._id = f"os-sandbox-{uuid.uuid4().hex[:12]}"
        self.default_timeout = config.default_timeout
        self._env_allowlist = tuple(config.env_allowlist)
        self._scratch = tempfile.mkdtemp(prefix="soothe-os-sandbox-")
        _register_scratch(self._scratch)
        self._workspace: Path | None = None
        self.workspace_root: str = config.workspace_root or ""
        if config.workspace_root:
            self.bind_workspace(config.workspace_root)
        self._tier = self._select_tier(config)
        self._popen = popen or subprocess.Popen
        self._session: _SeatbeltSession | _BwrapSession | _LandlockSession | None = None
        self._pgids: set[int] = set()
        logger.info("[Init] os_sandbox backend: id=%s tier=%s", self._id, self._tier)

    # -- identity / introspection ------------------------------------------------

    @property
    def id(self) -> str:
        return self._id

    @property
    def tier(self) -> OsSandboxTier:
        return self._tier

    @property
    def sandbox_posture(self) -> str:
        """Backend-level posture (the agent builder's value is authoritative)."""
        return _posture_for_tier(self._tier)

    # -- workspace binding -------------------------------------------------------

    def bind_workspace(self, host_root: str) -> None:
        """Bind the real host workspace directory (identity mapping).

        Args:
            host_root: Absolute or workspace-relative host directory.

        Raises:
            OsSandboxConfigError: Non-directory root, or rebinding a
                different root (fail-loud, no silent rebind).
        """
        path = Path(host_root).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        if not path.is_dir():
            msg = f"os_sandbox workspace root is not a directory: {path}"
            raise OsSandboxConfigError(msg)
        if self._workspace is not None and path != self._workspace:
            msg = (
                f"os_sandbox workspace already bound to {self._workspace}; "
                f"refusing rebind to {path}"
            )
            raise OsSandboxConfigError(msg)
        self._workspace = path
        self.workspace_root = str(path)
        self._session = None  # rebuild with the bound paths

    def _require_workspace(self) -> Path:
        if self._workspace is None:
            msg = (
                "os_sandbox workspace is not bound — set "
                "sandbox.backend.os_sandbox.workspace_root or let the agent builder bind it"
            )
            raise OsSandboxConfigError(msg)
        return self._workspace

    # -- tier selection ------------------------------------------------------------

    def _select_tier(self, config: OsLocalSandboxConfig) -> OsSandboxTier:
        if sys.platform == "darwin":
            if shutil.which("sandbox-exec") is None:
                msg = "os_sandbox on macOS requires Seatbelt (sandbox-exec) — not found on PATH"
                raise OsSandboxCapabilityError(msg)
            return "seatbelt"
        arch = _native_arch()
        if sys.platform != "linux" or arch is None:
            msg = (
                f"os_sandbox has no supported tier on platform {sys.platform}/{platform.machine()}"
            )
            raise OsSandboxCapabilityError(msg)
        if config.linux_tier == "bwrap":
            if not _probe_bwrap():
                msg = (
                    "os_sandbox linux_tier='bwrap' requires bubblewrap with capable user namespaces"
                )
                raise OsSandboxCapabilityError(msg)
            return "bwrap"
        if config.linux_tier == "landlock":
            if not config.allow_degraded:
                msg = "linux_tier='landlock' requires allow_degraded=true (file-access denial only)"
                raise OsSandboxConfigError(msg)
            if not _probe_landlock():
                msg = "os_sandbox linux_tier='landlock' requires Landlock (kernel >= 5.13)"
                raise OsSandboxCapabilityError(msg)
            return "landlock"
        if _probe_bwrap():
            return "bwrap"
        if config.allow_degraded and _probe_landlock():
            return "landlock"
        msg = (
            "os_sandbox: no usable Linux tier — bwrap probe failed (capable user "
            "namespaces?) and Landlock was not accepted (kernel >= 5.13 + allow_degraded)"
        )
        raise OsSandboxCapabilityError(msg)

    def _ensure_session(self) -> _SeatbeltSession | _BwrapSession | _LandlockSession:
        if self._session is None:
            ws = self._require_workspace()
            scratch = Path(self._scratch)
            if self._tier == "seatbelt":
                self._session = _SeatbeltSession(ws, scratch)
            elif self._tier == "bwrap":
                self._session = _BwrapSession(ws, scratch, spawn_prefix=_bwrap_spawn_prefix())
            else:
                self._session = _LandlockSession(ws, scratch)
        return self._session

    # -- env construction (L2 seam) ------------------------------------------------

    def _build_child_env(self) -> dict[str, str]:
        """Allowlist-only child env; secrets outside the allowlist never cross."""
        env: dict[str, str] = {}
        for key in self._env_allowlist:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        env["HOME"] = str(self._require_workspace())
        env["TMPDIR"] = self._scratch
        return env

    # -- BaseSandbox members -----------------------------------------------------

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Run one command inside the OS sandbox (errors and timeouts as data).

        Output capture is bounded (``_EXECUTE_CAPTURE_CAP_BYTES`` per stream):
        when the cap is hit the process group is killed and the response
        carries a truncation note, so an unbounded writer can neither exhaust
        memory nor stall the timeout. The command runs in its own process
        group (``start_new_session``); groups that outlive the command
        (background children) stay host-visible and are cleaned up by
        ``close`` / interpreter exit.
        """
        self._require_workspace()
        effective = self.default_timeout if timeout is None else int(timeout)
        argv = self._ensure_session().build_argv(command)
        env = self._build_child_env()
        try:
            proc = self._popen(
                argv,
                cwd=self.workspace_root or None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            return ExecuteResponse(output=f"Error: {exc}", exit_code=None)
        pgid = proc.pid
        self._track_pgid(pgid)
        try:
            captured: dict[str, tuple[bytes, bool]] = {}

            def _drain(key: str, pipe: object) -> None:
                captured[key] = _read_bounded(pipe, _EXECUTE_CAPTURE_CAP_BYTES)
                if captured[key][1]:
                    # Cap reached: the writer can never deliver more usable
                    # output — unblock it (and the command) for good.
                    _kill_pgid(pgid)

            readers = [
                threading.Thread(target=_drain, args=("stdout", proc.stdout), daemon=True),
                threading.Thread(target=_drain, args=("stderr", proc.stderr), daemon=True),
            ]
            for reader in readers:
                reader.start()
            notes: list[str] = []
            timed_out = False
            try:
                proc.wait(timeout=effective)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc)
                proc.wait()
                timed_out = True
                notes.append(
                    f"Command exceeded timeout of {effective}s; the process group was killed."
                )
            for reader in readers:
                reader.join()
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None:
                    with contextlib.suppress(OSError, ValueError):
                        pipe.close()
            if any(truncated for _, truncated in captured.values()):
                notes.append(
                    f"Command output exceeded {_EXECUTE_CAPTURE_CAP_BYTES} bytes per stream"
                    " and was truncated; the process group was killed."
                )
            stdout = captured.get("stdout", (b"", False))[0].decode(errors="replace")
            stderr = captured.get("stderr", (b"", False))[0].decode(errors="replace")
            return ExecuteResponse(
                output=_merge_output(stdout, stderr, " ".join(notes) if notes else None),
                exit_code=124
                if timed_out
                else (proc.returncode if proc.returncode is not None else -1),
            )
        finally:
            self._reap_pgid(pgid)

    def upload_files(self, files: Sequence[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, data in files:
            target = self._resolve_in_sandbox(path)
            if target is None:
                responses.append(FileUploadResponse(path=path, error=INVALID_PATH))
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                responses.append(FileUploadResponse(path=path, error=None))
            except OSError as exc:
                responses.append(FileUploadResponse(path=path, error=str(exc)))
        return responses

    def download_files(self, paths: Sequence[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            resolved = self._resolve_in_sandbox(path)
            if resolved is None:
                responses.append(FileDownloadResponse(path=path, content=None, error=INVALID_PATH))
            elif not resolved.exists():
                responses.append(
                    FileDownloadResponse(path=path, content=None, error=FILE_NOT_FOUND)
                )
            elif resolved.is_dir():
                responses.append(FileDownloadResponse(path=path, content=None, error=IS_DIRECTORY))
            else:
                try:
                    responses.append(
                        FileDownloadResponse(path=path, content=resolved.read_bytes(), error=None)
                    )
                except OSError as exc:
                    responses.append(FileDownloadResponse(path=path, content=None, error=str(exc)))
        return responses

    # -- path validation -----------------------------------------------------------

    def _resolve_in_sandbox(self, path: str) -> Path | None:
        """Symlink-safe resolution constrained to the workspace/scratch roots."""
        if not path.startswith("/"):
            return None
        try:
            resolved = Path(path).resolve()
        except OSError:
            return None
        roots = [self._require_workspace()]
        if self._scratch:
            roots.append(Path(self._scratch))
        for root in roots:
            if resolved == root or root in resolved.parents:
                return resolved
        return None

    # -- lifecycle -------------------------------------------------------------------

    def _track_pgid(self, pgid: int) -> None:
        """Register a live process group for orphan cleanup (see close())."""
        with _lifecycle_lock:
            self._pgids.add(pgid)
            _pgid_registry.add(pgid)

    def _reap_pgid(self, pgid: int) -> None:
        """Stop tracking a group once its last member is gone.

        Groups that outlive their command (background children) stay
        tracked — ``close`` and interpreter exit kill them.
        """
        if not _pgid_alive(pgid):
            with _lifecycle_lock:
                self._pgids.discard(pgid)
                _pgid_registry.discard(pgid)

    def _kill_live_groups(self) -> None:
        with _lifecycle_lock:
            pgids = list(self._pgids)
            self._pgids.clear()
        for pgid in pgids:
            _kill_pgid(pgid)
            with _lifecycle_lock:
                _pgid_registry.discard(pgid)

    def close(self) -> None:
        """Kill live sandbox process groups, then remove the scratch dir.

        Idempotent. Killing the groups first means no sandboxed process is
        still writing into the scratch tree while it is removed. Residual
        gap: a hard interpreter crash (SIGKILL) bypasses this and atexit —
        only the bwrap tier carries kernel-level ``--die-with-parent``.
        """
        self._kill_live_groups()
        if not self._scratch:
            return
        shutil.rmtree(self._scratch, ignore_errors=True)
        _unregister_scratch(self._scratch)
        self._scratch = ""
