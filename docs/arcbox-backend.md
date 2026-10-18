# ArcBox Sandbox Backend

**Status**: implemented (phase 1 + phase 2). Design record and integrator guide
for `ArcBoxBackend` — the sandbox backend that moves nano's execution surface
(shell + workspace file operations) into an ArcBox Linux microVM while the agent
loop and model calls stay on the host.

This is a *remote-execution backend*, not "Soothe inside the VM": the guest
provides a Linux command environment and the workspace filesystem; all reasoning,
tool decisions and credentials stay on the host.

## 1. Overview

- `ArcBoxBackend(BaseSandbox)` is injected through the existing backend seam:
  `create_nano_agent(config, backend=ArcBoxBackend(sandbox_id=...))`. Without
  injection, behavior is unchanged.
- It implements only `BaseSandbox`'s four abstract members — `id`, `execute`,
  `upload_files`, `download_files`. `ls` / `read` / `write` / `edit` / `glob` /
  `grep` / `delete` are derived by `BaseSandbox` from guest `execute`.
- The builder wraps a bare sandbox into `CompositeBackend(default=sandbox,
  routes=host)` so framework state survives VM teardown (§2, §6).
- The caller (e.g. a session layer) owns the sandbox lifecycle; the backend only
  *connects* to an existing `sandbox_id` and never creates or destroys a VM
  (§10).
- Model credentials never enter the backend or the guest (§11). ArcBox failures
  are errors, never a fallback to host execution.

Injected backend ⇒ **sandbox execution mode** (§6): the shell group is re-routed,
the file surface collapses onto the middleware tools, and every tool gets a
placement (§7).

## 2. Architecture

```text
┌────────────────────────── host (trusted) ────────────────────────────┐
│  SootheNanoAgent                                                     │
│    ├── LLM client ───────────────────────► provider (key on host)    │
│    ├── LangGraph loop + middleware                                   │
│    └── CompositeBackend                                              │
│          ├── default = ArcBoxBackend ──► /workspace/**               │
│          └── routes  = host backend  ──► /memories, /.soothe,        │
│                                          /large_tool_results,        │
│                                          /conversation_history       │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ arcbox SDK (UDS / gRPC)
                                   ▼
┌────────────────────────── ArcBox Linux microVM ──────────────────────┐
│  command execution · shell · toolchains · /workspace files           │
│  no agent loop · no model credentials · no host framework state      │
└──────────────────────────────────────────────────────────────────────┘
```

Guest-side paths such as `/workspace/.soothe/background/bg-*.log` fall through to
the sandbox default by design — only the four absolute prefixes route home.

### Invariants

1. **One shell.** Only the `shell` group (`run_command`, `run_python`,
   `run_background`, `tail_background_log`, `kill_process`) is visible; the
   middleware's built-in `execute` stays hidden — two shells with different
   output formats and timeout governance must never co-exist.
2. **One file surface.** The middleware FS tools are the single source (§9); no
   duplicate registration of same-named tools.
3. **One workspace.** Guest shell and file tools see the same `/workspace`.
4. **Framework state on host.** memory / skills / `.soothe` / offload artifacts
   survive sandbox teardown.
5. **No model credentials in the guest** — not in env, cmd, template, image,
   snapshot, tool args, or tool results.
6. **Fail closed.** Guest unavailable ⇒ error-as-data, never host execution.

## 3. Quick start

```python
from soothe_nano import create_nano_agent
from soothe_nano.config import SootheConfig
from soothe_nano.sandbox import ArcBoxBackend

# 1. The caller creates the sandbox with the arcbox SDK and waits for READY (omitted)
sandbox = ArcBoxBackend(
    sandbox_id="sbx-...",                # id of an already-ready ArcBox sandbox
    workspace_root="/workspace",          # guest default cwd
    default_timeout=120,                  # fallback execute timeout (seconds)
)

# 2. Inject it; the backend is wrapped automatically at build time,
#    no need to assemble a CompositeBackend by hand
agent = create_nano_agent(SootheConfig(), backend=sandbox)
```

- Without an explicit `client`, the real arcbox SDK adapter is used; daemon
  connection settings (`api_url` / `api_key` / `socket_path`) fall back to the
  `ARCBOX_API_URL` / `ARCBOX_API_KEY` environment variables.
- **In tests, inject a custom client** — any object implementing the
  `ArcBoxClient` protocol (`run` / `read_bytes` / `write_bytes`). No daemon
  required.
- A `CompositeBackend` supplied by the caller is trusted as-is (not re-wrapped).

## 4. Backend contract

`src/soothe_nano/sandbox/{__init__,arcbox,placement}.py`.

```python
class ArcBoxBackend(BaseSandbox):
    def __init__(self, *, sandbox_id: str, client=None, workspace_root="/workspace",
                 default_timeout=120, api_url=None, api_key=None, socket_path=None,
                 connect_timeout=60.0, enable_capture_offload=None): ...
    @property
    def id(self) -> str: ...
    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse: ...
    def upload_files(self, files) -> list[FileUploadResponse]: ...
    def download_files(self, paths) -> list[FileDownloadResponse]: ...
```

- `_ArcBoxSdkAdapter` isolates the SDK: `run` / `read_bytes` / `write_bytes`,
  translating SDK failures into `ArcBoxError` subclasses. SDK types never cross
  the adapter.
- **Guest image hard requirement:** `python3` + POSIX coreutils (`setsid`,
  `kill -- -PGID`, `tail`, `nohup`, `grep`, `sed`). `BaseSandbox` derives
  `read` / `edit` / `grep` from `python3 -c` inside the guest — without an
  interpreter they fail, not just `execute`. The daemon default template has no
  python3; use `docker/templates/{e2e,prod}/Dockerfile` (§12).
- `upload_files` / `download_files` accept absolute paths only; relative paths
  return `invalid_path` (upstream convention).
- `enable_capture_offload` is **opt-in** (default off). When on, large output
  lands in a guest file with head/tail preview and the exit code is preserved;
  the hard cap is `_EXECUTE_CAPTURE_MAX_BYTES` (10 MiB), not a constructor knob.
  Never hand-roll character truncation at the backend — it loses exit codes.

## 5. Backend protocol facts

Contract facts from `soothe-deepagents`' `BackendProtocol`:

| Item | Fact |
|---|---|
| `execute` | keyword-only `timeout: int \| None`; introspected — `float` or positional breaks per-command timeouts |
| `ExecuteResponse` | `output`, `exit_code: int \| None`, `truncated`; **no timeout field** |
| errors | returned as `error` strings, not raised; `NotImplementedError` only for unimplemented capabilities |
| `exit_code is None` | status unknown — must not be read as failure or not-found |
| results | `Read/Write/Edit/Ls/Grep/Glob/Delete*Result`; `read` returns raw content (line numbers are added by the middleware) |
| async | sync is primitive; `a*` variants default to `asyncio.to_thread` |

## 6. Sandbox execution mode (build time)

Detected by `SandboxBackendProtocol` on the resolved backend. Backend resolution
runs **before** tool resolution: shell re-binding and placement finalization both
depend on it.

| Item | Behavior |
|---|---|
| backend wrapping | Bare sandbox wrapped into `CompositeBackend`: `/memories`, `/.soothe`, `/large_tool_results`, `/conversation_history` route to the host backend; everything else (including guest `/workspace/.soothe/...`) routes to the sandbox. Framework state survives VM teardown. A composite passed in by the caller is trusted as-is. |
| `shell` group | `run_command` / `run_python` / `run_background` / `tail_background_log` / `kill_process` are re-routed to `backend.execute()` through an injected `CommandExecutor` seam (`execute` + `execute_with_offload`): host mode wraps the existing subprocess path (`HostShellExecutor`, semantics unchanged), sandbox mode passes the backend (`BackendShellExecutor`). Single code path; tool names and schemas unchanged; safety guards, timeout clamping and output formatting are shared. |
| file tools | The `file_ops` toolkit group is retired: `FilesystemMiddleware`'s tools are the single file surface in every mode, guest-side under sandbox (§9). |
| FS allowlist | `FILESYSTEM_TOOLS_SANDBOX` — base FS primitives plus the line-edit family (`file_info` / `edit_lines` / `insert_lines` / `delete_lines` / `apply_diff`); readonly modes use `FILESYSTEM_TOOLS_ASK`. The upstream built-in `execute` stays hidden — the guest shell has exactly one entry point, `run_command`. `read_file` must always be present (middleware rejects otherwise). |
| permissions | Dropped entirely under sandbox (a guest backend cannot express host write-denial); readonly enforcement falls back to the tool allowlist, with a warning under ask/plan/bypass. |
| planner subagent | The composite backend is threaded into `resolve_subagents`; planner recon tools bind to it with the guest workspace root. Host mode unchanged. |
| GP subagent | Controlled by `agent.runtime.general_purpose_subagent`: `off` / `full` / `readonly` (write-deny degrades to the read-only tool surface) / `per_step`; under sandbox, no variant carries host permissions. |
| undeclared-tool gate | Custom / MCP / plugin tools with no declared placement are **rejected at build time** by default (fail-closed) — see §7. |

## 7. Tool placement model

`sandbox/placement.py`. Under sandbox mode **every** tool is assigned a placement,
resolved at build time and inspectable via `builder.placement_report`.

| placement | meaning |
|---|---|
| `protocol` | FS primitive — the middleware reaches the guest directly through the backend |
| `guest` | semantics migrated to a guest command (shell group, via `backend.execute()`) |
| `shuttle` | byte transfer: guest path args download to a host temp dir → the original implementation runs → `file_write` outcomes upload back → temp paths leaked into the result are remapped to guest paths |
| `host` | no workspace coupling — runs as-is |
| `deny` | fail-closed — not registered (raises by default; with `on_deny: drop` it is removed with a warning) |

Resolution order: `sandbox.placement_overrides` (config) > explicit declaration
(`@tool(placement=...)` / `ToolMeta.placement`) > default derivation by
category / `outcome_type` (FS primitive ⇒ `protocol`; `code_exec` ⇒ `guest`;
`file_read` / `file_write` ⇒ `shuttle`; otherwise `host`) > **registry miss ⇒
`deny`**.

```yaml
sandbox:
  on_deny: raise                # default; "drop" removes + warns
  max_shuttle_bytes: 33554432   # per-shuttle size cap (default 32 MiB)
  placement_overrides:          # ops-level per-tool declaration (highest priority)
    my_reviewed_host_tool: host
```

Notes:

- Pure metadata catalog tools (`search_tools` / `search_skills` / `invoke_skill`
  / `search_mcp_tools` / `mcp_resources_list`) infer to `host`.
- Custom / MCP / plugin tools are fail-closed: undeclared and unregistered tools
  never reach the model.
- Shuttle copies are snapshots — no cross-call linear consistency, write-back is
  explicit, and transfers over `max_shuttle_bytes` error out instead of silently
  shipping large datasets.

## 8. Execution semantics

- **Timeouts.** Two strictly distinct cases: the SDK's real server-side timeout
  kills the guest process group and maps to the `exit_code=124` convention; a
  bridge deadline (command timeout + 30s margin, waiter cancelled) claims nothing
  — it reports "the guest command may still be running". Never conflate them.
- **Background jobs.** `setsid` detaches into its own process group; the log
  lives at `<guest workspace>/.soothe/background/bg-<pid>.log`;
  `tail_background_log` uses guest `tail -n <count>` (one bounded round-trip);
  `kill_process` reaps `kill -- -PGID`, falling back to a single pid.
- **Error mapping.** exit code → `exit_code`; stdout + stderr → `output`;
  truncation → `truncated=True`; sandbox not ready / SDK / transport errors →
  `ExecuteResponse(output="Error: ...", exit_code=None)`; unsupported capability
  → `NotImplementedError` (middleware converts it to an error ToolMessage).
- `default_timeout` falls back to 120s; `FilesystemMiddleware`'s
  `max_execute_timeout` ceiling (3600s) is always greater than it.
- **No auto-retry** of non-idempotent commands; no global serialization.
  `BaseSandbox` file ops are one `execute` per operation, so concurrent writes to
  the same guest file race — writes go through the harness edit-lock path.

## 9. File-tool unification (phase 2)

The `file_ops` toolkit group is retired: the middleware FS surface is the single
source of file tools in every mode — one allowlist, one middleware, only the
backend differs between host and sandbox.

- `FILESYSTEM_TOOLS_AGENT` absorbs the surgical family (`file_info`,
  `edit_lines`, `insert_lines`, `delete_lines`, `apply_diff`); subagents inherit
  the same allowlist through their own FS middleware.
- `tools.file_ops.enabled=False` gates the surgical family directly on the
  middleware allowlist (`delete` excluded — base mutating surface, matching
  pre-unification behavior).
- `toolkits/file_ops.py` is deleted; `build_filesystem_tools` lives in
  `toolkits/filesystem_tools.py`, the surgical name constants in
  `agent/interaction_mode.py`.

## 10. Lifecycle, configuration, dependencies

- Caller: create sandbox (ArcBox SDK) → wait READY → inject backend → run agent
  → stop / remove sandbox on session close.
- `arcbox>=0.1.0,<0.2.0` is a **core dependency** (not an optional extra). The
  SDK is imported lazily — `soothe_nano.sandbox` imports fine without it, and
  instantiation produces an actionable error. No lockfile exists in this repo, so
  version safety rests on the upper bound plus CI compatibility runs.
- `api_url` / `api_key` / `socket_path` (env: `ARCBOX_API_URL` /
  `ARCBOX_API_KEY`) are **daemon** credentials for the host→daemon control plane.
  They are never model credentials and never reach the guest.
- Trust boundary: the ArcBox daemon UDS relies on socket permissions only, and
  any holder of a backend instance can run arbitrary guest commands. This phase
  targets trusted single-user hosts; backend instances must not be exposed to
  untrusted plugins.

## 11. Credentials and security boundaries

- `api_key` is only an **ArcBox daemon credential** (control-plane auth from host
  to daemon), not a model API key. **Model credentials never enter the backend
  and are never serialized into the VM** — a unit test pins the constructor
  surface (`test_constructor_surface_holds_no_model_credentials`).
- Backend errors always follow **error-as-data** (`ExecuteResponse(error=...)` /
  mapped `ArcBoxError`); exception paths never touch the host `subprocess`.
- No silent fallback: if the guest is unavailable that is an error — execution
  never degrades to the host.
- Command output is untrusted input to the agent; existing tool-result handling
  applies. The daemon socket is never exposed to the VM.

## 12. Verification status

- Unit (no daemon): `tests/unit/sandbox/test_arcbox_backend.py` (backend contract
  + invariants), `tests/unit/sandbox/test_placement.py` (placement + shuttle
  reverse mapping), `tests/unit/toolkits/test_shell_executor.py` (executor seam;
  error paths never touch host `subprocess`),
  `tests/unit/agent/test_builder_sandbox.py` (composite routing, four interaction
  modes × sandbox, placement gate, hidden `execute`, GP variants).
- Real-machine E2E: `tests/integration/test_arcbox_e2e.py` — 15 tests, opt-in:

  ```bash
  uv run pytest tests/integration/test_arcbox_e2e.py --run-integration
  ```

  Requires a local ArcBox daemon; it skips cleanly without one. The template is
  selected via `ARCBOX_E2E_TEMPLATE`, defaulting to `soothe-nano-prod`
  (production guest image: python 3.12 bookworm + setsid/procps/coreutils; the
  daemon default template has **no python3** and is rejected by the image
  pre-check). Template definition `docker/templates/prod/Dockerfile` (root
  runtime — ArcBox default); CI publishes it on release as
  `registry.cn-hangzhou.aliyuncs.com/lacogito/soothe-nano-vm-prod`. Local
  registration:

  ```bash
  abctl sandbox template build soothe-nano-prod \
    --from-dockerfile docker/templates/prod/Dockerfile
  ```
- Coverage: image prerequisites, execute / timeout (124) semantics, FS↔shell
  workspace sharing both directions, glob/grep/edit/delete round-trip, capture
  offload with preserved exit code, no sandbox leaks, stopped-sandbox
  error-as-data, credential-free guest environment, agent-build acceptance.

## 13. Known limitations and deferred work

- Running tool *code* inside the VM (guest tool runtime) is not supported — only
  tool *effects* land in the guest. Separate RFC.
- Host sandbox manager, session authorization / RBAC, egress policy, quotas and
  audit logging are out of scope for this phase.
- Guest background logs are not pruned inside the VM for the VM's lifetime.
- Shuttle transfers are snapshots (see §7).
- Cross-version safety for `BaseSandbox` (semi-private import path) relies on an
  existence check plus the `soothe-deepagents` floor.
- Within the nano 2.0.0 release train this capability ships under `[Unreleased]`.

## 14. References

- Upstream (`soothe-deepagents`): `backends.sandbox.BaseSandbox`,
  `backends.composite.CompositeBackend`, `backends.protocol.BackendProtocol`.
- ArcBox: <https://github.com/arcboxlabs/arcbox>
