# os_sandbox Backend (Local OS Primitives)

**Status**: implemented (v2 — read-side parity, bounded capture, orphan
cleanup). Design record and integrator guide for
`OsLocalSandbox` — the sandbox backend that gives the agent's shell plane a
real OS-level isolation boundary on hosts **without hardware virtualization**
(no `/dev/kvm`, no nested virtualization). macOS uses Seatbelt
(`sandbox-exec`); Linux uses bubblewrap mount-namespaces plus a seccomp-bpf
deny-list (full tier) or Landlock (declared degraded tier).

Design: [RFC-CORE-011](../../../.platonic/specs/coreagent/RFC-CORE-011-os-local-sandbox-backend.md) ·
Implementation guide: [IG-CORE-007](../../../.platonic/impl/coreagent/IG-CORE-007-os-local-sandbox-backend.md).

Isolation-capability integration suite:
`tests/integration/test_os_sandbox_isolation.py` (run with
`pytest tests/integration/ --run-integration`; executes real commands
through every tier the host provides — verified on macOS Seatbelt and on
Linux bubblewrap in a root-without-CAP_SYS_ADMIN container).

Like the ArcBox backend this is a *remote-execution backend*: the sandbox
provides a command environment and the workspace filesystem; reasoning, tool
decisions, and credentials stay on the host. Unlike ArcBox there is **no
second OS** — guest paths are host paths and guest PIDs are host PIDs.

## 1. Overview

- `OsLocalSandbox(BaseSandbox)` is constructed from
  `sandbox.backend.os_sandbox` config via the existing factory (`type:
  "os_sandbox"`), or injected programmatically.
- It implements only `BaseSandbox`'s four abstract members — `id`,
  `execute`, `upload_files`, `download_files`. `ls` / `read` / `write` /
  `edit` / `glob` / `grep` / `delete` are derived by `BaseSandbox` from
  sandboxed `execute`.
- **Identity path mapping**: the workspace directory is bound as-is
  (guest path == host path). No path rewriting exists anywhere in the stack.
- **Host-visible PIDs**: the PID namespace is never unshared.
  `run_background` children stay enumerable; `kill_process` and
  `tail_background_log` semantics are identical to host mode.
- Construction failures (`OsSandboxCapabilityError`) and build-time
  failures propagate — **there is no fallback to host execution** (§8).
- Model credentials never enter the backend or the sandboxed child env (§6).

## 2. Tier matrix

| Platform | Tier | Mechanism | Posture |
|---|---|---|---|
| macOS | `seatbelt` (only) | `sandbox-exec` profile: `(deny default)`, narrow read (bwrap-parity set), narrow write, no network | `full` |
| Linux | `bwrap` (full) | mount-ns (`--bind` ws, `--ro-bind` system trees, `--tmpfs /tmp`, `--dev`, `--unshare-net`) + in-namespace launcher: `PR_SET_NO_NEW_PRIVS` → seccomp deny-list → `exec` | `full` |
| Linux | `landlock` (degraded) | Landlock ruleset: read/write confined to workspace + scratch, read-only on system trees | `subprocess_only` |

Tier selection (`linux_tier`):

- `auto` (default): probe bwrap first (a real `bwrap` round-trip — the only
  trustworthy capable-userns probe); if unavailable and `allow_degraded` is
  set, Landlock; otherwise `OsSandboxCapabilityError`.
- `bwrap` / `landlock`: pin a tier; a missing prerequisite is a loud
  capability error. `landlock` additionally requires `allow_degraded: true`
  — a declared degradation is never silent.

## 3. Seatbelt v2 boundary (macOS)

The profile is regenerated per session from the template:

```
(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow file-read-metadata (literal "/") ...root + workspace ancestors...)
(allow file-read-data (literal "/"))
(allow file-read* (subpath "/usr") ...system trees + workspace/scratch...)
(allow file-read-data (literal "/dev/urandom") (literal "/dev/random") (literal "/dev/null"))
(allow file-write* (subpath "<resolved workspace>") (subpath "<resolved scratch>"))
(allow file-write-data (literal "/dev/null"))
```

- **Reads are narrowed to the bwrap-parity set** (`_SEATBELT_READ_TREES`):
  `/usr`, `/bin`, `/sbin`, `/System`, `/Library`, `/opt`, `/private/etc`,
  `/private/var/select` plus the workspace/scratch. Everything else — other
  users' data under `/Users`, `/private/var/db`, package roots under
  `/Applications`, host `/private/tmp` — is denied, matching the bwrap bind
  list's effective read set. `/opt` stands in for the Linux `/usr/local`
  bind (homebrew prefix).
- **Writes** are denied everywhere except the workspace and the session
  scratch directory; both subpaths use `Path.resolve()`-ed real paths
  (firmlink resolution: `/tmp` → `/private/tmp`, `/var` → `/private/var` —
  unresolved subpath literals never match, seatbelt checks the resolved
  path).
- **Network and signals** are denied by the root `(deny default)` rule.
- `/dev/null` write-data is allowed so standard redirects keep working;
  `/dev/urandom`/`/dev/random` are readable because interpreters seed from
  them at startup (`_Py_HashRandomization_Init`).
- The command runs under `/bin/sh -c` (zsh refuses to start under
  deny-default).

macOS-specific allowances the parity set needs:

- `file-read-metadata` (literal) on the firmlink/volume roots
  (`/etc`, `/tmp`, `/var`, `/private`, `/Users`, ...) and on every ancestor
  of the workspace/scratch: path resolution and tools like git `lstat` the
  whole cwd chain. This leaks only the `lstat` of those directory entries
  (existence/mtime), never listings or file data.
- `file-read-data (literal "/")`: `getcwd` walks `..` — the root directory
  is listable, exposing top-level names only.
- `file-read* (subpath "/private/var/select")`: the shell-selection symlink
  tree macOS consults when exec'ing `/bin/sh`.

The v1 read-side trade-off (broad reads) is closed: the SIGABRT mystery was
the missing `/` readdir and `/private/var/select` read, not firmlink
resolution as first suspected.

## 4. Linux full tier: bwrap + seccomp

`_BwrapSession` builds the argv (pure, unit-tested):

- `--ro-bind` / `--ro-bind-try` of `/usr`, `/usr/local`, `/bin`, `/lib`,
  `/lib64`, `/etc`; `--proc /proc`; `--dev /dev`; `--tmpfs /tmp`.
- `--bind` (read-write, **identity**) of the workspace and scratch.
- `--die-with-parent --unshare-net`.
- **No `--new-session`**: `start_new_session=True` on the Popen already
  detaches the whole tree from the host terminal's session, and an inner
  `setsid` would move sandboxed children out of the tracked process group —
  `close()`/timeout `killpg` could no longer reach them.
- **No `--unshare-pid`** — see §1 (host-visible PIDs).

The final argv element is an embedded Python launcher (`_LAUNCHER_SECCOMP`,
run under the namespace's interpreter) that:

1. sets `PR_SET_NO_NEW_PRIVS` first — the load-bearing
   privilege-escalation block;
2. installs the seccomp-bpf filter via `seccomp(2)` (ctypes);
3. `os.execvp`s `/bin/sh -c <command>`.

### Root-in-container hosts (userns wrapper)

bubblewrap running as euid 0 skips its own user namespace and creates the
mount namespace directly — `EPERM` on hosts that are root inside a
container without `CAP_SYS_ADMIN` over the initial namespace (a common
dev/CI container shape). The backend detects this empirically (a real
bwrap round-trip, never a flag check, cached per process) and wraps bwrap
in `unshare --user --map-root-user`. The userns-wrapped spawn binds the
host `/proc` read-only instead of mounting a fresh proc (bwrap < 0.5's
sysrq-trigger probe fails on userns-mounted proc); visibility is
equivalent because the PID namespace is never unshared. The capability
probe and every later spawn use the same resolved form — the probe can
never pass while the spawn would fail.

### Seccomp filter shape

An **arch-aware deny-list** (not an allowlist): unknown syscalls return
`ENOSYS` (libc falls back gracefully for benign newer syscalls like `rseq`),
unknown architectures are denied, and the denied set — namespace and
privilege escapes (`unshare`, `setns`, `mount`, `umount2`, `pivot_root`,
`ptrace`, `clone3`, `bpf`, module loading, `perf_event_open`, ...) — fails
outright. The mount-ns/userns capability checks carry the boundary; seccomp
is defense in depth on top of `no_new_privs`.

The BPF program is built parent-side (`_build_seccomp_bpf`) — layout and
jump targets are unit-testable on every platform — and shipped to the
launcher as hex.

## 5. Landlock degraded tier

`_LandlockSession` runs a launcher (`sys.executable -c`) that applies a
Landlock ruleset (kernel ≥ 5.13, probed by forking a child that calls
`landlock_create_ruleset`): read/write confined to workspace + scratch,
read-only on the system trees, then execs the command. No filesystem view,
no network restriction, no process isolation — hence opt-in
(`allow_degraded`) and always reported as `sandbox_posture =
subprocess_only`.

## 6. Environment and credentials

The child env is constructed from an exact allowlist
(`env_allowlist`, default `PATH`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TERM`,
`TMPDIR`, `HOME`) with two overrides: `HOME` = workspace root, `TMPDIR` =
session scratch. No wholesale inheritance: host-env secrets outside the
allowlist never cross the boundary. Network egress is default-deny on every
tier; the egress relay is a follow-up spec and `egress.enabled=true` is a
loud config-time failure today.

## 7. Workspace binding

The workspace root is bound at construction when `workspace_root` is set,
otherwise injected by the agent builder (`_bind_os_sandbox_workspace`) from
`WorkspaceResolver.effective_tool_workspace` — the same root the host
backend resolves, never the process CWD. Rebinding a different root is a
loud `OsSandboxConfigError`; a non-directory root likewise. `upload_files` /
`download_files` resolve paths symlink-safely against the bound roots and
reject escapes with `INVALID_PATH`.

## 8. Fail-loud invariants

- Configured sandbox that cannot engage (probe failure) ⇒
  `OsSandboxCapabilityError` at construction — never host execution.
- Builder-level: construction failures abort the agent build with the
  original error (the ArcBox-era silent host fallback is removed).
- `sandbox.enabled=false` combined with `security.hard_deny_severities`
  excluding `"critical"` requires `sandbox.acknowledge_no_isolation: true`
  — the two risk-relaxing knobs must never combine silently.

## 9. Posture reporting

`OsLocalSandbox.sandbox_posture` reports the backend tier
(`full` for seatbelt/bwrap, `subprocess_only` for Landlock). The **agent
builder's** `sandbox_posture` is authoritative: any tool placed `host` or
`shuttle` (executing in the agent process, outside the kernel boundary)
forces `subprocess_only` even on a full-tier backend. On the default
placement table this is the expected steady state; the build log lists the
host-process tools explicitly.

```json
{
  "sandbox_posture": "subprocess_only",
  "engine": "bwrap",
  "host_placement_tools": ["search_tools", "search_skills", "invoke_skill"]
}
```

## 10. Config reference

```yaml
sandbox:
  enabled: true
  backend:
    type: os_sandbox
    os_sandbox:
      workspace_root: null       # null = builder binds the effective tool workspace
      linux_tier: auto           # auto | bwrap | landlock
      allow_degraded: false      # gate for the Landlock tier
      default_timeout: 120
      env_allowlist: [PATH, LANG, LC_ALL, LC_CTYPE, TERM, TMPDIR, HOME]
      egress:
        enabled: false           # must stay false (relay is a follow-up)
```

## 11. Output capture and process lifecycle

**Bounded output capture** (`execute`): stdout/stderr are drained by daemon
reader threads capped at `_EXECUTE_CAPTURE_CAP_BYTES` (16 MiB) per stream —
strictly above `BaseSandbox._EXECUTE_CAPTURE_MAX_BYTES` (10 MiB guest-side
offload window) so offloaded reads are never clipped. When a cap is hit the
reader kills the process group (an unbounded writer can neither exhaust
memory nor stall the timeout) and the response appends a truncation note.
Timeouts keep the `exit_code=124` contract and kill the group first, then
drain.

**Process-group lifecycle** (P2): every `execute` runs in its own process
group (`start_new_session`). Groups that outlive their command (background
children — deliberately host-visible, §1) are tracked in a registry and
killed by `close()` and by an atexit handler (processes die before the
scratch tree is removed). Hard interpreter death (SIGKILL) bypasses both —
only the bwrap tier carries kernel-level `--die-with-parent` for that case;
seatbelt and landlock have no `PDEATHSIG` equivalent, which is the
documented residual gap.

## 12. Limitations

- **No egress relay yet** — network is default-deny with no approved-egress
  path (RFC-CORE-011 §5.5 defines the seam; the proxy is follow-up).
- **Landlock tier** is file-access denial only — no filesystem view, no
  network or process isolation.
- **Hard-crash orphans on seatbelt/landlock** (§11): a SIGKILL of the host
  interpreter can leave background groups running (bwrap's
  `--die-with-parent` covers its tier).
- **Seatbelt metadata leak** (§3): `lstat` of firmlink roots and workspace
  ancestors (existence/mtime of directory entries) plus top-level names of
  `/` — the price of path resolution and `getcwd` under deny-default.
- **Not a VM**: same kernel, same filesystem, same PIDs as the host. The
  boundary is syscall/mount/policy-level, appropriate for containing
  agent-generated command behavior, not for running untrusted code with
  hostile kernel-exploit capability (that is ArcBox/microVM's tier).
