# soothe-nano ArcBox Sandbox Backend 设计文档

-   **状态**：Draft / RFC（已按 `soothe-nano` 与 `soothe-deepagents@0.8.6`
    实际源码校订）
-   **目标仓库**：[mirasoth/soothe-nano](https://github.com/mirasoth/soothe-nano)
-   **相关仓库**：[mirasoth/soothe-deepagents](https://github.com/mirasoth/soothe-deepagents)、[mirasoth/flowjet](https://github.com/mirasoth/flowjet)、[arcboxlabs/arcbox](https://github.com/arcboxlabs/arcbox)
-   **设计范围**：在 `soothe-nano` 中将 Agent 的 shell
    与工作区文件操作委托给 ArcBox Linux microVM；Agent Loop
    和模型调用继续留在宿主机侧。
-   **本阶段原则**：最小可用集成，暂不实现独立 Sandbox
    Manager，不引入复杂的多租户授权、网络策略控制面或通用远程执行平台。

> **代码基准**：本文所有行号与签名均来自 `soothe-nano` 工作区源码 +
> `soothe-deepagents==0.8.6`（实机 `import` 验证 `BaseSandbox`、
> `CompositeBackend`、`ExecuteResponse` 等）。升级依赖时需复核。

## 1. 摘要

本 RFC 为 `soothe-nano` 设计一个可注入的 `ArcBoxBackend`，使基于
DeepAgents 的 Agent Loop 在宿主机运行，而命令执行和工作区文件操作发生在
ArcBox 提供的 Linux microVM 中。

核心方案：

1.  复用 `soothe-nano` 已有的 `backend` 注入点，实现
    `soothe_deepagents.backends.sandbox.BaseSandbox` 子类。
2.  `ArcBoxBackend` **只需实现四个成员**（`id`、`execute`、`upload_files`、
    `download_files`）；`ls`/`read`/`write`/`edit`/`delete`/`glob`/`grep`
    全部由 `BaseSandbox` 用 guest 内 `execute` 派生，无需自行实现。
3.  注入必须**同时重路由 `shell` 组、收缩 `file_ops` 组、扩充 FS
    allowlist**：`shell` 与 `file_ops` 两个工具组默认在宿主机上自建执行
    路径，注入 Backend 不会自动改变它们——`shell` 组保留注册并把实现
    重路由到 `backend.execute()`（placement=`guest`，工具名/schema 不变），
    `file_ops` 组禁用并由中间件同名工具补位；否则会退化成"命令在宿主机、
    文件在 VM"的最坏组合。
4.  采用 `CompositeBackend(default=ArcBoxBackend, routes={框架态前缀: 宿主机
    Backend})`，让工作区落 VM、memory / skills / `.soothe` 框架态留宿主机。
5.  LLM API Key 只供宿主机上的 Soothe 模型客户端使用，不写入 ArcBox 的
    `env`、启动命令、模板、工作区文件或 VM 镜像。
6.  第一阶段由调用方（例如 Flowjet Session 层）创建、持有和销毁
    Sandbox，并把 `sandbox_id` 对应的 Backend 注入 nano。

这是一种**远程执行 Backend**，不是把 Soothe Agent 安装进 VM。VM 仅提供
Linux 命令执行环境和工作区文件系统。

## 2. 背景与当前架构

### 2.1 调用链

``` text
Flowjet Server
  └── soothe / soothe-nano agent entrypoint
        └── soothe-nano AgentBuilder
              ├── resolve_tools()            ← 独立于 backend，自建宿主机后端
              │     ├── shell      (subprocess, host)
              │     └── file_ops   (NormalizedPathBackend, host)
              └── soothe-deepagents create_deep_agent(backend=resolved_backend)
                    ├── Agent / LangGraph loop（宿主机）
                    ├── FilesystemMiddleware  ← 用注入的 backend
                    ├── MemoryMiddleware / SkillsMiddleware ← 同一个 backend
                    └── subagents / MCP / skills
```

### 2.2 soothe-nano 已有的扩展点（已核对源码）

`/Users/.../soothe-nano/src/soothe_nano/agent/builder.py`：

| 事实 | 位置 | 说明 |
|---|---|---|
| `build(..., backend: BackendProtocol \| None = None)` | L83 | 唯一注入点 |
| `resolved_backend = backend or self._initialize_backend(resolved_policy)` | **L187** | 在 L127 `resolve_tools()` **之后**计算 |
| `_initialize_backend` → `FrameworkFilesystem.initialize(...)` | L498-507 | 默认返回 `WorkspaceAwareBackend`（宿主机） |
| `create_deep_agent(..., backend=resolved_backend, ...)` | L315 | 传给 harness |
| per-step 只读 GP subagent 的 `FilesystemMiddleware(backend=..., _permissions=ask_permissions())` | L296-300 | 仅 `gp_mode == "per_step"` |

工厂入口有两个，都接受并转发 `backend`：`create_nano_agent()`
（`builder.py:510-541`）与 `create_dual_mode_nano_agent()`
（`agent/dual_mode.py:248-283`）。

### 2.3 ⚠️ 阻塞性现状问题

这四条不是"待盘点"，而是**按"注入一个 Backend 即可"的朴素做法直接实现
就会踩到**的问题。

#### (A) `shell` 与 `file_ops` 工具组完全绕过 Backend

`src/soothe_nano/utils/resolver.py`：

-   L387-394 `shell` 组 → `build_shell_toolkit(workspace_root=resolved_cwd)`，
    工具内部 `_run_shell_command_sync` 直接
    `subprocess.Popen(command, shell=True, cwd=cwd, ...)`
    （`toolkits/shell.py:552`）。源码注释直言
    *"Host-execution tools do not require a sandbox backend."*（L410）。
-   L424-425 `file_ops` 组 → `_build_soothe_file_tools()`，内部
    `get_workspace_backend(...)` 自建 `NormalizedPathBackend`。

`config/models.py:441 ShellToolsConfig.enabled`（组原名 `execution`）默认 `True`，
`file_ops` 亦默认启用。因此**注入 ArcBox Backend 后，Agent 会同时拥有三套
工具**：VM 内的文件工具（来自 `FilesystemMiddleware`）、宿主机
`run_command`、宿主机 `file_ops`，路径语义互相冲突。

#### (B) `execute` 工具在 nano 中**从不暴露** —— 注入 sandbox 后仍然没有 shell

`src/soothe_nano/agent/interaction_mode.py`：

``` python
FILESYSTEM_TOOLS_AGENT = ["ls","read_file","write_file","edit_file","delete","glob","grep"]
"""Built-in FS tools for AGENT mode (no sandbox ``execute``)."""   # 原文注释
FILESYSTEM_TOOLS_ASK  = ["ls","read_file","file_info","glob","grep"]   # PLAN 同
```

三个 allowlist **都不含 `execute`**。`builder.py:238-242,319` 把它作为
`filesystem_tools=` 传给 `create_deep_agent`，最终落到
`FilesystemMiddleware(tools=normalized_filesystem_tools)`
（`graph.py:1043`）→ `_enabled_tools = frozenset(allowlist)`
（`middleware/filesystem.py:1629-1634`）→ 过滤时
`unsupported = {n for n in tool_names if n in _ALL_FS_TOOL_NAMES
and n not in self._enabled_tools}`（同文件 3409-3413）→ **`execute` 被隐藏**。

后果（比 (A) 更严重）：注入 ArcBox Backend 只会让**文件**工具进 VM，
**shell 一个都不会进 VM**；模型只能继续用宿主机 `run_command`。
即 RFC 的头号目标「shell 在 VM 内执行」**完全落空**，且形成最坏组合——
命令在宿主机、文件在 VM，两者看到的是不同文件系统。

修法（**toolkit 路线**，见 §7.1）：不依赖中间件自带的 `execute` 工具承担
VM shell——它被 allowlist 挡着，且暴露它会与重路由后的 `run_command` 形成
双 shell。改为让 `shell` 工具组保持注册、其实现重路由到
`backend.execute()`（placement=`guest`，§7.5.3）。`execute` 保持隐藏（现状）。

连带：`FILESYSTEM_TOOLS_AGENT` 也不含 `file_info`、`edit_lines`、
`insert_lines`、`delete_lines`、`apply_diff`——这些今天由 `file_ops`
工具组提供。sandbox 模式下禁用 `file_ops` 后，allowlist 需一并追加这五个。

#### (C) `FrameworkFilesystem` 单例旁路 → 注入 Backend 后 RuntimeError

`builder.py:187` 传了 `backend` 就**不会**调用 `_initialize_backend`，
`FrameworkFilesystem._instance` 保持 `None`；而以下位置无条件调用
`FrameworkFilesystem.get()`，而 `get()` 在 `_instance is None` 时
**`raise RuntimeError`**（`workspace/workspace_filesystem.py:799-800`）：

-   `middleware/workspace_context.py:28`
-   `toolkits/_internal/backend_ops.py:45`
-   `resolve/_resolver_tools.py:318`

#### (D) `permissions` + `execute` 在中间件构造期互斥

`soothe_deepagents/middleware/filesystem.py:1579-1591` 的完整条件：

``` python
if (_permissions
        and isinstance(self.backend, BackendProtocol)
        and supports_execution(self.backend)
        and not _all_paths_scoped_to_routes(_permissions, self.backend)):
    raise NotImplementedError(...)
```

nano 在**三种模式**下都会传非空 `fs_permissions`（`builder.py:243-247`：
ask / plan / bypass），`per_step` 只读 subagent 亦然（`builder.py:296-300`）。
注意逃生口 `_all_paths_scoped_to_routes`：若所有 permission 路径都落在
`CompositeBackend` 的 route 前缀内，则不抛——这正是 §6.4 采用 Composite
的第二个收益。

### 2.4 ArcBox 能力边界

ArcBox 提供 sandbox 生命周期 API、命令执行 API、文件传输/路径操作 API 与
快照 API；daemon 经本机 Unix Domain Socket 暴露 gRPC。Sandbox V1 需要支持
嵌套虚拟化的环境（当前文档：Apple Silicon M3+、macOS 15+、VZ 后端）。

具体 Python SDK 类名、方法签名和错误类型以锁定的 `arcbox` 版本为准。
本文不臆造 SDK 方法名；Backend 侧只假定 SDK 能提供三个能力：**执行命令**、
**按路径读字节**、**按路径写字节**（见 §6.2）。

## 3. 目标与非目标

### 3.1 目标

-   保持模型调用与 Agent Loop 在宿主机。
-   Agent 可见的**唯一** shell 与文件工具集运行在 ArcBox microVM 内。
-   `create_nano_agent(config, backend=ArcBoxBackend(...))` 接入，未注入时行为不变。
-   一个 Backend 实例绑定一个既有 `sandbox_id`。
-   `ExecuteResponse` / `*Result(error=...)` 语义与 harness 完全一致。
-   通过 `CompositeBackend` 保证框架态（memory / skills / `.soothe`）不随 VM 销毁而丢失。
-   有单元测试（无 daemon）与真实 ArcBox 环境的 opt-in 集成测试。
-   LLM API Key 不进入 VM。

### 3.2 非目标（第一阶段不做）

-   不把 Soothe / LangGraph loop 放进 VM。
-   不开发独立的宿主机 Sandbox Manager 服务。
-   不实现通用远程执行协议、集群调度或多宿主机管理。
-   不重构工具系统、MCP、subagent、memory 或模型提供商路由。
-   不实现多租户身份、细粒度 RBAC、网络出口代理和策略控制面。
-   不承诺 ArcBox 快照是 Agent Session / LangGraph 状态的完整替代品。
-   **不把工具实现代码搬进 VM**（§7.5.1 语义 B / §7.5.7 Guest Tool
    Runtime）。第一阶段只保证"效果落在 VM"，工具的 Python 实现仍在宿主机。

## 4. 设计原则

1.  **Agent loop 外置**：模型推理与工具决策由宿主机 Soothe 执行。
2.  **单一工作区真相源**：同一时刻只允许一套 shell 与文件工具可见。
3.  **显式注入、默认兼容**：未注入时保持 `WorkspaceAwareBackend` 行为。
4.  **最小依赖**：`arcbox` 为可选依赖；不使用 ArcBox 的 Claude Agent 封装。
5.  **不传递模型凭证**：Backend 不接受 `api_key` 参数。
6.  **复用 `BaseSandbox`**：不在 nano 内复制一套文件协议实现。
7.  **错误可见**：VM 未就绪、超时、SDK 错误、文件不存在转换为明确错误，
    **不静默回退到宿主机**。
8.  **工具语义不变**：工具名与模型可见参数不变，只换执行后端。

## 5. 目标架构

``` text
┌────────────────────── Flowjet Server / trusted host ─────────────────────┐
│  Session lifecycle                                                        │
│    ├── create ArcBox Sandbox (ArcBox SDK) → retain sandbox_id             │
│    └── create_nano_agent(config, backend=ArcBoxBackend(...))              │
│                                                                           │
│  SootheNanoAgent                                                          │
│    ├── LLM Client ───────────────────────► LLM Provider (key on host)     │
│    ├── Agent / LangGraph loop                                             │
│    └── CompositeBackend                                                   │
│          ├── default  = ArcBoxBackend  ──► /workspace/**                  │
│          └── routes   = host backend   ──► /memories/**, /.soothe/**      │
└──────────────────────────────────────────┬────────────────────────────────┘
                                           │ ArcBox local SDK / gRPC (UDS)
                                           ▼
┌──────────────────────────── ArcBox Linux microVM ─────────────────────────┐
│  command execution · shell · toolchains · /workspace files                │
│  No Soothe Agent Loop; no LLM API key; no host framework state            │
└───────────────────────────────────────────────────────────────────────────┘
```

### 5.1 请求流程

一次 `run_command` 工具调用（sandbox 模式，toolkit 路线）：

1.  模型在宿主机生成工具调用（工具名与 schema 与非 sandbox 模式完全相同）。
2.  工具实现先走原有前置：banned-command 安全守卫、
    `clamp_execute_timeout`、runtime workspace 解析（全部原样保留）。
3.  sandbox 分支把命令交给 `backend.execute_with_offload(command, timeout=...)`
    —— `CompositeBackend` 转发到 `ArcBoxBackend.execute`。
4.  Backend 调 ArcBox execution API，在 VM 中运行命令。
5.  结果映射为 `ExecuteResponse(output, exit_code, truncated)`；offload
    生效时大输出落 guest 文件、只回 head/tail 预览，`exit_code` 保留。
6.  工具按既有格式拼装结果，进入 Agent 上下文，宿主机继续下一轮模型调用。

（中间件自带的 `execute` 工具保持隐藏，见 §7.1(二)。）

一次文件工具调用（`read_file` / `write_file` / `edit_file` / `edit_lines` /
`apply_diff` / `glob` / `grep` / `ls` / `delete`）：

1.  中间件调用 `backend.read` / `write` / `edit` / …。
2.  `BaseSandbox` 把这些调用翻译成 guest 内 POSIX 命令（或 SDK 原生文件 API，
    若 override）。
3.  guest 内 shell 与文件工具看到同一份 `/workspace`。

## 6. 组件设计

### 6.1 `ArcBoxBackend`

新增模块：

``` text
src/soothe_nano/sandbox/
  __init__.py        # 导出 ArcBoxBackend（懒加载 + 友好报错）
  arcbox.py          # ArcBoxBackend + _ArcBoxSdkAdapter
```

> **不放进 `src/soothe_nano/backends/`。** 该目录已被"协议持久化后端"
> 占用（`durability/` `memory/` `persistence/` `vector_store/`），
> 与 `BackendProtocol` 无关，混放会造成语义冲突。

``` python
from soothe_deepagents.backends.sandbox import BaseSandbox

class ArcBoxBackend(BaseSandbox):
    # 镜像确认含 POSIX shell + coreutils 后置 True，
    # 让大输出走 capture-offload（落文件 + head/tail 预览），
    # 比自造字符截断更贴近 harness 语义。
    enable_capture_offload = True

    def __init__(
        self,
        *,
        sandbox_id: str,
        client: object | None = None,      # 可注入 SDK adapter（测试用 fake）
        workspace_root: str = "/workspace",
        default_timeout: int = 120,        # 协议要求 int，不是 float
    ) -> None: ...

    # 注意：不要加 max_output_bytes 之类的自造截断旋钮。
    # BaseSandbox 没有这个参数（LocalShellBackend 的 max_output_bytes 是本
    # 地实现专属）；大输出应交给 enable_capture_offload（§9.3）。

    # —— BaseSandbox 要求的四个抽象成员 ——
    @property
    def id(self) -> str: ...                                     # 返回 sandbox_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse: ...

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]: ...

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]: ...
```

**只需这四个。** `BaseSandbox` 免费提供
`ls/als`、`read/aread`、`write/awrite`、`edit/aedit`、`delete/adelete`、
`grep/agrep`、`glob/aglob`、`execute_with_offload/aexecute_with_offload`
（实测 `BaseSandbox.__abstractmethods__ == {"download_files", "execute",
"id", "upload_files"}`，`soothe-deepagents==0.8.6`）。

> **ArcBox 镜像的隐含硬要求**：这些派生能力不是纯 shell——
> `_READ_COMMAND_TEMPLATE` / `_EDIT_COMMAND_TEMPLATE` / grep 脚本都以
> `python3 -c "…"` 在 guest 内执行（`sandbox.py:202,365`）。因此 guest 镜像
> **必须预装 python3**，否则 `read` / `edit` / `grep` 全部失效，
> 而不仅仅是 `execute` 不可用。这一点必须写进 ArcBox template 验收项。

`upload_files` / `download_files` 的路径参数按上游惯例**必须是绝对路径**
（参照 `LangSmithSandbox`：非 `/` 开头返回 `FileOperationError` 的
`invalid_path`），`ArcBoxBackend` 应保持同一约定。

若 ArcBox SDK 提供原生文件 API，可参照 `LangSmithSandbox`
（`soothe_deepagents/backends/langsmith.py`）只 override `read` / `write`，
但必须保持与基类一致的语义：`_write_preflight`、二进制转 base64、
`MAX_OUTPUT_BYTES` + `TRUNCATION_MSG`、"Line offset N exceeds file length
(M lines)" 文案。

### 6.2 Backend Protocol 事实表（已核对 `soothe-deepagents==0.8.6`）

协议文件：`soothe_deepagents/backends/protocol.py`。

| 项 | 事实 |
|---|---|
| 文件系统方法名 | `ls` / `read` / `write` / `edit` / `glob` / `grep` / `delete` |
| **不存在**的方法名 | `ls_info`、`read_file`、`write_file`、`edit_file`、`glob_info`、`grep_raw` |
| `read` 签名 | `read(file_path, offset=0, limit=2000) -> ReadResult` |
| `write` 签名 | `write(file_path, content, *, backup=False) -> WriteResult`（`backup` 仅关键字） |
| `edit` 签名 | `edit(file_path, old_string, new_string, replace_all=False, *, backup=False)` |
| `execute` 签名 | `execute(command, *, timeout: int \| None = None) -> ExecuteResponse`（**必须关键字、必须 `int`**） |
| `ExecuteResponse` | `output: str`、`exit_code: int \| None`、`truncated: bool`（**无 timeout 字段**） |
| `ReadResult` | `error: str \| None`、`file_data: FileData \| None`；`FileData = {content, encoding}` |
| 其余 Result | `LsResult{error, entries}`、`GrepResult{error, matches, truncated}`、`GlobResult{error, matches, truncated}`、`WriteResult{error, path, backup_path}`、`EditResult{error, path, occurrences, backup_path}`、`DeleteResult{error, path, backup_path}` |
| `FileUploadResponse` | `path: str`、`error: FileOperationError \| str \| None` |
| `FileDownloadResponse` | `path: str`、`content: bytes \| None`、`error: ...` |
| 错误约定 | **错误作为 `error` 字符串返回，不抛异常**；未实现能力才 `NotImplementedError` |
| `exit_code is None` | 表示后端无法确定状态，**不得当成 not-found** |
| 异步 | sync 为原语，`a*` 变体默认 `asyncio.to_thread`；`aedit_batched` 只有异步版 |
| 能力探测 | `isinstance(backend, SandboxBackendProtocol)`；`_supports_delete` 比较
`type(b).delete is not BackendProtocol.delete`；`execute_accepts_timeout` 用
`inspect.signature(cls.execute)` 内省 `"timeout"` |
| `read` 内容 | 返回**不带行号**的原文；行号由中间件 `format_content_with_line_numbers` 添加 |
| 空文件 | `FileData(content="System reminder: File exists but has empty contents", encoding="utf-8")` |
| 超时 | `ExecuteResponse` 无 timeout 字段；惯例以 `exit_code=124` + output 文本表达 |

**`execute` 签名是硬约束**：`protocol.py:803 execute_accepts_timeout()` 通过
签名内省判定；若写成 `timeout: float | None = None` 或位置参数，模型传
timeout 会被工具层拒绝（"不支持 per-command timeout"）。

### 6.3 ArcBox SDK Adapter

`arcbox.py` 内部薄 adapter，隔离 SDK 版本变化，不泄漏 protobuf 类型：

``` text
BaseSandbox (read/write/edit/grep/glob/ls/delete)
          │  (默认路径：翻译成 guest 内 POSIX 命令)
          ▼
ArcBoxBackend.execute / upload_files / download_files
          ▼
_ArcBoxSdkAdapter
  ├── run(command, timeout) -> (stdout, stderr, exit_code)
  ├── read_bytes(path) -> bytes
  ├── write_bytes(path, data) -> None
  └── translate errors → ArcBoxError 子类
          ▼
ArcBox Python SDK / gRPC (UDS)
```

第一阶段可直接写在 `ArcBoxBackend` 内，但 SDK 类型不得越过 adapter。

### 6.4 组合：`CompositeBackend` 分流框架态

`create_deep_agent` 把同一个 backend 交给 `FilesystemMiddleware`、
`MemoryMiddleware`、`SkillsMiddleware` 与 subagent
（`graph.py:870-884, 966-978, 1048-1089`）。若直接注入裸 `ArcBoxBackend`，
memory 与 skills 文件会写进 VM 并随 sandbox 销毁丢失。

因此注入形态为：

``` python
host_backend = WorkspaceAwareBackend(...)                 # 宿主机框架态
agent_backend = CompositeBackend(
    default=arcbox,                                       # 必须是 default：
    routes={                                              # supports_execution 只看
        "/memories": host_backend,                        # CompositeBackend.default
        "/.soothe": host_backend,
        "/large_tool_results": host_backend,              # 2026-10-17 补：
        "/conversation_history": host_backend,            # upstream 中间件在
        # 其余前缀（/workspace/**）走 default              # execution backend 下的
    },                                                    # 绝对默认前缀（已实测）
)
```

> **2026-10-17 Spike C 落定**：`create_deep_agent` 主链的
> `FilesystemMiddleware` 由 upstream `graph.py:1038` 构造，prefix 默认解析为
> **绝对** `/large_tool_results` / `/conversation_history`（实测确认，非
> nano `SootheFilesystemMiddleware` 的相对 `.soothe/...` 默认——那只影响
> planner/file_ops 目录，sandbox 下两者均被禁用）。因此 route 表必须覆盖
> 这两个前缀，否则框架态落 guest、随 VM 销毁丢失。宿主机后端的虚拟根
> 语义（`should_use_virtual_path_resolution`）会把四个前缀都映射到
> `<host-workspace>/...`，与非 sandbox 模式完全同位。

-   `supports_execution(CompositeBackend)` 判定
    `isinstance(backend.default, SandboxBackendProtocol)`（`filesystem.py:1316-1337`）
    → 为 `True`。该判定在 toolkit 路线下有两个消费方：
    `CompositeBackend` 的 `execute` 转发（`composite.py:673-734`）与
    `shell` toolkit 的 executor 注入判定（§7.1(二)）；中间件 `execute`
    工具本身保持隐藏。
-   `composite.py:673-734` 仅在 `default` 是 `SandboxBackendProtocol` 时转发
    `execute`，否则 `NotImplementedError`。
-   路由匹配语义（`composite.py:131-161`，已核对）：按**绝对路径**匹配，
    `path == prefix.rstrip("/")` 命中根，或 `path.startswith(prefix + "/")`；
    未命中则回 `default`。后缀会剥掉前缀后传给子后端。
-   该形态即上游官方模式：`CompositeBackend` 的 docstring 示例就是
    `routes={"/memories/": StoreBackend(namespace=ns), ...}`，注释明言
    *"state for temp files, persistent store for memories"*（`composite.py:3-5,
    245-252`）。`BackendProtocol` 的定位是"pluggable memory backends
    (single, unified)"（`protocol.py:461-465`）——memory 与工作区共用
    同一文件接口，按前缀分流是它的原生用法。
-   第二个收益：框架态留在宿主机，也顺带满足 §9.1（宿主机状态不进 VM）。
-   第三个收益：`_all_paths_scoped_to_routes` 逃生口 —— 若所有 permission
    路径都落在这些 route 前缀内，§2.3(D) 的 `NotImplementedError` 不再触发。

**待 spike 确认**：路由前缀是字符串前缀匹配，需实测确认 nano 的 memory /
skills / `large_tool_results_prefix` 实际落盘路径（当前线索：
`SootheFilesystemMiddleware` 默认 `large_tool_results_prefix =
".soothe/large_tool_results"`、`conversation_history_prefix =
".soothe/conversation_history"`，均为相对路径）。

## 7. 工具路由与文件系统一致性

这是本 RFC 的**核心正确性要求**。

### 7.1 原则：重路由 `shell`、收缩 `file_ops`、扩充 allowlist（必须成套做）

> **术语区分（极易混淆，实现前必读）**
>
> -   **`shell`** 是 **soothe-nano 的工具组**（`toolkits/shell.py`
>     → `run_command` / `run_python` / `run_background` /
>     `tail_background_log` / `kill_process`），在**宿主机**跑
>     `subprocess`，由 `tools.shell.enabled` 控制。
> -   **`execute`** 是 **deepagents `FilesystemMiddleware` 创建的单个工具**
>     （`middleware/filesystem.py:3522-3706`），唯一入口是
>     `backend.execute()`，不属于任何 nano 工具组。
>
> 二者是**两套完全独立的 shell**，没有任何代码复用。sandbox 模式下必须
> 二选一，否则模型会看到两个"跑命令"的工具，一个在宿主机、一个在 VM。
>
> **命名消歧（已完成，先于本 RFC 的 ArcBox 实现落地）**：`shell` 组原名
> `execution`，因易与 deepagents 的 `execute` 工具混淆而改名。选 "shell" 的
> 依据：`run_command` 的 `ToolMeta` 已有 `aliases=("shell","bash")`
> （`metadata.py:196`），上游同类概念叫 `LocalShellBackend`，内部实现叫
> `_run_shell_command_sync`。已落地范围：插件名 `@plugin(name="shell")`、
> `ShellPlugin`/`ShellToolkit`/`ShellToolsConfig`、配置键
> `tools.shell`（硬改名，经查宿主仓库代码与运行配置无消费者，故未留别名）、
> `ToolMeta.category` 五处 + 两个安全层消费点 + `category_map` 原子同改、
> `_tool_groups` / `ASK_MUTATING_TOOL_GROUPS`、模块
> `toolkits/execution.py` → `toolkits/shell.py`、11 个测试文件改名。
> **工具名（`run_command` 等）未改**——模型可见、提示词已调优、
> `honor_timeout_arg_for` 按名匹配，且它们不是混淆源。
> "host_shell" 之类的放置耦合名否决：executor 注入后 shell 既可在宿主机
> 也可在 guest。

> **决策记录：`shell` 保持 toolkit 路线（不迁入 middleware）。**
> 曾评估把 `shell` 组做成 `SootheShellMiddleware`（仿
> `FilesystemMiddleware`）。经核对 `graph.py` 的继承规则否决：
> subagent 默认继承 parent 的 **tools**（`graph.py:995`）但**不**继承
> parent 的 middleware（普通声明式 subagent 连 opt-in 旗标都没有，仅
> `is_forked` 继承，`graph.py:961-965`；只有默认 GP subagent 有
> `propagate_to_general_purpose` 旗标，`graph.py:1066-1069`）。迁入
> middleware 会让所有 subagent 静默丢失 shell，需在三处显式接线；
> 而 toolkit 的 tools 自动传播，**零接线**。工具经 `InjectedToolArg`
> 已能拿到每调用的 runtime（`shell.py:644-648`），backend 访问只差
> 构建顺序（§7.2 第 1 条），不构成迁移动机。
> 附带收益：后台进程状态本就是文件化（`bg-{pid}.log` / `fg-{pid}.session`）
> + PID 直杀，无内存注册表，toolkit 与 middleware 在这点上无差异。

"注入 Backend → 所有 shell/文件工具自动改道"这一直觉不成立（§2.3 A）；
更糟的是，即便文件工具进了 VM，`execute` 也根本不在 allowlist 里
（§2.3 B）。
正确做法：识别到 `SandboxBackendProtocol` 后端时，nano 进入
**sandbox execution 模式**，做三件事——**重路由** `shell` 组、
**收缩** `file_ops` 组、**扩充** FS allowlist（补 `file_ops` 的缺口）。

**（一）`resolve_tools()` 工具组处理**

| 工具组 / 工具 | 现状 | sandbox 模式下 |
|---|---|---|
| `shell`（`run_command`、`run_python`、`run_background`、`tail_background_log`、`kill_process`） | 宿主机 `subprocess`，`enabled` 默认 True | **保留注册，placement=`guest`**：实现重路由到 `backend.execute()`（§7.5.3），工具名/schema 不变 |
| `file_ops`（`delete`、`file_info`、`edit_lines`、`insert_lines`、`delete_lines`、`apply_diff`） | 自建 `NormalizedPathBackend` | **默认禁用**（中间件已提供同名工具） |
| `data`（`inspect_data` 等） | 直接 `read_text` 读宿主机路径 | `shuttle`（§7.5.6）；第一阶段可先禁用 |
| `image`（`analyze_image`） | 读宿主机路径 | `shuttle`（§7.5.6）；第一阶段可先禁用 |
| `datetime` | 无文件系统依赖 | `host`，保留 |
| `wizsearch` / `http_requests` / `deepxiv` | 网络 | `host`，保留 |
| MCP / plugin / 用户自定义工具 | 视实现 | 走 §7.5 放置模型；未声明者 `deny` |

**（二）`shell` 组重路由映射（placement=`guest`）**

工具名与模型可见 schema **完全不变**，只换执行后端。
实现上**不做 if/else 双分支**，而是抽一个内部 `CommandExecutor` 微协议
（形状即 `SandboxBackendProtocol` 的执行面：`execute(command, *, timeout)`
+ `execute_with_offload`），`build_shell_toolkit(..., executor=...)`
注入：

-   host 模式：`HostShellExecutor` = 现有 `_run_shell_command_sync`
    （`Popen` + reader 线程 + deadline + killpg + `fg-{pid}.session` 注册）
    原样包装，**语义零变化**。不用上游 `LocalShellBackend`：其 `cwd`
    构造期固定（`local_shell.py:313`），无法满足每调用动态 workspace；
    且无 fg session 注册、输出格式模型可见地不同（`[stderr]` 前缀 /
    `<no output>` / `Exit code: N`）。
-   sandbox 模式：注入的 backend（Composite/ArcBox）本就满足该形状，
    **零适配**。
-   `run_command` 只剩一条路径：守卫 → clamp → 解析 cwd → executor →
    格式化。一个 fake executor 即可覆盖两种模式的测试，双分支与双治理栈
    都不会出现。

| 原工具 | guest 实现 |
|---|---|
| `run_command` | `backend.execute_with_offload(command, timeout=...)`（保留退出码与大输出 offload；超时/输出上限/安全守卫逻辑原样保留，仅替换 `subprocess.Popen` 分支）。**实现偏差（2026-10-17）**：offload 仅在 backend 显式 opt-in（`enable_capture_offload` 为真）时启用（`shell.py:645-652`），否则走普通 `execute`——`ArcBoxBackend` 默认不开启 capture offload（§9.3 的前提是 opt-in，非默认） |
| `run_python` | `backend.execute("python3 - <<'EOF' … EOF")`（heredoc 避免引号转义问题） |
| `run_background` | `execute("nohup … > <log> 2>&1 & echo $!")`（`<log>` 由 guest 侧拼好路径；沿用宿主机实现"先写 pending 再按 PID 重命名"的套路，`execution.py:900-905`），返回 guest PID + log 路径。**实现偏差（2026-10-17）**：guest 单行内联完成（`mkdir -p` + `setsid`（可用时）+ `nohup … & pid=$!; mv …; echo $pid`，`shell.py:1020-1030`），并经 `< /dev/null` 释放 session stdio |
| `tail_background_log` | ~~`backend.read(<guest log 路径>)` 取尾部 N 行~~ **实现偏差（2026-10-17）**：改为 guest 侧 `tail -n <count> <log>`（`shell.py:1202-1211`）——`BaseSandbox` 派生的 `backend.read()` 是全文件读（多次 execute 派生原语），既无行数上界也多付 round-trip；guest 自带 `tail` 单次往返且有界（count clamp 1..5000） |
| `kill_process` | `execute("kill -- -<pid>")`（guest 进程组）+ 沿用 PID 守卫逻辑的 guest 等价物 |

**实现偏差（2026-10-17，retention）**：宿主机路径的
`_cleanup_stale_background_logs(log_dir, background_log_retention_days)`
（`shell.py:188-192, 1095`）只在 host `run_background` 分支调用；guest 分支
不清理 `bg-*.log`——guest 后台日志在 VM 存活期内无保留期裁剪。第一阶段
接受（VM 生命周期由调用方管理，随 sandbox 销毁整体消失）；若后续出现
长生命周期 VM + 高频后台任务，需在 guest 侧补等价裁剪。

注意 `execute` 工具本身**保持隐藏**（allowlist 现状不含它）：shell 由重路由
后的 `run_command` 独占，维持"同一时刻只有一套 shell"的硬约束；若同时
暴露 `execute` 会形成双 shell，且两套输出格式
（`[Command succeeded/failed with exit code N]` vs nano 自有格式）与两套
超时治理（middleware `max_execute_timeout` vs `clamp_execute_timeout`）
会同时暴露给模型。

已知残余冗余（接受，不消除）：`FilesystemMiddleware.__init__` 无条件
`_create_execute_tool()`（`filesystem.py:1648-1662`），随后被 allowlist
每请求过滤——`execute` 在 nano 是 created-then-hidden 的死工具。代价仅为
一个死对象 + 每请求一次过滤，可忽略；nano 侧用测试断言钉死
"`execute` 不可见"（§12.2）。如上游将来提供"不创建 execute 工具"的
构造参数可顺带省掉，但不为此发上游 PR。

**（三）FS allowlist 扩充**（补 `file_ops` 禁用后的缺口）

sandbox 模式下 `filesystem_tools` 改为：

``` python
FILESYSTEM_TOOLS_SANDBOX: list[FsToolName] = [
    "ls", "read_file", "write_file", "edit_file", "delete",
    "glob", "grep",
    "file_info", "edit_lines", "insert_lines",
    "delete_lines", "apply_diff",                 # ← 补回 file_ops 禁用后的缺口
]
```

ask / plan / bypass 模式在此基础上按现有只读口径裁剪（去掉 `write_file` /
`edit_file` / `delete` 等写项）。
`read_file` 必须保留——`FilesystemMiddleware` 对不含它的列表直接
`raise ValueError`（`filesystem.py:1560-1562`）。

guest 后台日志路径注意：`run_background` 在 guest 写
`/workspace/.soothe/background/bg-<pid>.log`，与 §6.4 中宿主机路由前缀
`/.soothe` **不是**同一路径（前者以 `/workspace` 开头，不会命中宿主机
route）；`tail_background_log` 必须读 guest 侧路径。列入 Spike C 验证项。

### 7.2 需要的 `builder.py` 改动

1.  **提前解析 `resolved_backend`**：把 L187 的
    `resolved_backend = backend or self._initialize_backend(...)`
    移到 L127 `resolve_tools()` 之前。这一条同时服务两处：FS allowlist
    上下文与 `shell` toolkit 的 backend 注入（§7.1(二)）。
2.  **始终初始化 `FrameworkFilesystem`**（修 §2.3 C）：宿主机后端照常
    `initialize()`；注入 sandbox 时在其上包 `CompositeBackend`，并把
    composite 登记为框架当前实例。
3.  **工具组过滤**：`resolve_tools(...)` 增加 `sandbox_mode: bool`，
    禁用 `file_ops` 组；`shell` 组**保留**但传入 backend。
4.  **FS allowlist 扩充**（修 §2.3 B 后半）：新增 `FILESYSTEM_TOOLS_SANDBOX`
    及 ask/plan/bypass 只读变体，按 §7.1(三) 注入 `filesystem_tools=`。
5.  **`shell` toolkit 重路由**（§7.1(二)）：`build_shell_toolkit`
    接受可选 `executor`；sandbox 模式传注入的 backend（零适配），
    host 模式传 `HostShellExecutor`（现有 subprocess 路径原样包装，
    向后兼容）。
6.  **permissions 冲突**（§2.3 D）：nano 在 ask / plan / bypass 与
    per_step 下都会传非空 permissions。优先靠 §6.4 的
    `CompositeBackend` + `_all_paths_scoped_to_routes` 逃生口解决；
    若 permission 路径无法全部落入 route，则 sandbox 模式下对该 middleware
    不传 `_permissions`。实现阶段必须实测四种模式 × sandbox 的组合。
7.  **plan subagent**：`subagents/plan/engine.py:140-142` 自建
    `FilesystemBackend(root_dir=...)`，需改为使用注入的 backend。
8.  **`max_execute_timeout` 对齐**：中间件有独立的上限参数，Backend 的
    `default_timeout` 不得超过它，否则工具层会拒绝该 timeout
    （`filesystem.py:3566,3652`）。

### 7.3 一致性验收

-   同一时刻 Agent 可见的工具中，有且仅有一套 shell、一套文件读写。
-   不存在同名工具重复注册。
-   集成测试逐个断言：每个 shell / 文件工具都命中 fake ArcBox client。

### 7.4 Workspace 路径

-   VM 内工作区根固定为 `/workspace`（可配）。
-   **不要**把 `ArcBoxBackend` 再包一层 `NormalizedPathBackend` /
    `virtual_mode`：那是宿主机路径沙箱语义，guest 路径不适用。
-   nano 的 `security.allow_paths_outside_workspace` 只对宿主机后端生效；
    sandbox 模式的"越界"边界是 VM 本身。
-   需确认：ArcBox template 初始工作目录、Backend 路径参数是绝对还是相对、
    shell 默认 `working_dir`、`.git` / 隐藏文件 / 符号链接 / 目录遍历行为。
-   `run_command` 等工具的 `workspace_root` 参数在 sandbox 分支映射为 guest
    内 `workspace_root`；命令在 guest 内以该目录为 `cwd`。

### 7.5 全量工具路由：放置模型（Placement Model）

§7.1 只覆盖了 FS 原语与 shell 组。本节回答：**nano 的其余工具组
（`data` / `image` / document / 后台进程）以及用户自定义工具、plugin /
MCP 工具，如何也落到 VM 上。**

#### 7.5.1 先把"通过 ArcBox 执行"拆成两种语义

| 语义 | 含义 | 是否需要把代码放进 VM |
|---|---|---|
| **(A) 效果落在 VM** | 工具读写的是 VM 工作区、命令跑在 VM 里 | 否 |
| **(B) 代码在 VM 内运行** | 工具的 Python 实现本身在 guest 进程里执行 | **是** |

本 RFC 第一阶段只做 **(A)**。(B) 意味着把工具运行时装进 ArcBox 镜像，
与 §3.2「不把 Soothe 放进 VM」冲突，另立 RFC（见 §7.5.7）。
两者混谈会让设计滑向"把 soothe-nano 装进 VM"，必须在评审时明确区分。

#### 7.5.2 复用现有机制，不新造轮子

nano 已有四处可直接承载"per-tool 放置决策"的基础设施：

| 现有资产 | 位置 | 用途 |
|---|---|---|
| `ToolMeta`（`category` / `outcome_type` / `path_arg_keys` / `aliases`）+ `TOOL_REGISTRY`，已注册约 45 个工具 | `src/soothe_nano/tools/metadata.py:18-58,65,748,762` | per-tool 能力表；`path_arg_keys` 已声明"哪些参数是路径"，正是 shuttle 需要的注解 |
| `SoothePolicyMiddleware.awrap_tool_call`（最外层通用 tool-call 拦截，tool_name + args 都在此） | `src/soothe_nano/middleware/policy.py:51` | **运行期收口点** |
| `SootheFilesystemMiddleware._get_backend()`（按调用动态解析 backend 的先例） | `src/soothe_nano/middleware/filesystem.py:261` | 动态换 backend 的范式 |
| 构建期工具合流点 `all_tools`（config 组 + 用户 tools + MCP + 渐进式），唯一整体消费者是 `set_tool_catalog` | `src/soothe_nano/agent/builder.py:133-167,202-210` | **构建期收口点** |
| `_host_middleware_prefix/_suffix` 空钩子 | `builder.py:386-392` | 零侵入宿主注入点 |
| 路径双向映射 `should_use_virtual_path_resolution` / `resolve_backend_os_path` | `workspace/workspace_paths.py:93-125` | host↔逻辑命名空间 shim 的现成范式 |
| `ptc_allowlist`（per-tool-name allowlist 配置先例） | `config/models.py:1519` | 照抄一个 `sandbox.placement_overrides` |

#### 7.5.3 放置枚举与默认推导

给 `ToolMeta` 增加字段 `placement: str | None = None`（`None` = 按默认表推导），
取值：

| placement | 含义 | 适配方式 |
|---|---|---|
| `protocol` | Backend 原生语义 | 直接调 `backend.*`，无适配器（§6.1 的 7 个 FS 原语；`execute` 保持隐藏，shell 走 `guest`） |
| `guest` | 语义迁移为 guest 命令 | 用 `backend.execute()` 重实现（实现住在原 toolkit 内），工具名与 schema 对模型不变 |
| `shuttle` | 字节搬运 | `download_files` → 宿主临时文件 → 跑原实现 → `upload_files` 回传 |
| `host` | 与工作区无耦合 | 原样运行 |
| `deny` | 失败关闭 | 构建期即报错，不注册给模型 |

**默认推导表**（按 `ToolMeta.category` / `outcome_type`，sandbox 模式激活时生效）：

| category / outcome_type | 默认 placement | 例子 |
|---|---|---|
| `file_ops` 且属 FS 原语名 | `protocol` | `ls`/`read_file`/`write_file`/`edit_file`/`delete`/`glob`/`grep`/`edit_lines`/`apply_diff` |
| `shell` / `outcome_type == "code_exec"` | `guest` | `run_command`、`run_python`、`run_background`、`tail_background_log`、`kill_process` |
| `outcome_type == "file_read"` 且非原语 | `shuttle` | `data.*`、`analyze_image`、document 读取 |
| `outcome_type == "file_write"` 且非原语 | `shuttle` | 生成类工具 |
| `web` / 网络类 | `host` | `wizsearch.*`、`http_requests.*` |
| `generic`（无副作用） | `host` | `current_datetime`、`write_todos` |
| **注册表查不到**（用户自定义工具） | **`deny`** | 见 §7.5.5 |

#### 7.5.4 三个收口点

**（1）构建期 `finalize_tools(all_tools, backend)`** —— 插在
`builder.py:170` 之后、`create_deep_agent`（L304）之前。职责：

-   对每个工具求 `placement = resolve_placement(tool, backend, config)`；
-   `protocol` / `guest` / `shuttle` 的分别包装（或标记待运行期处理）；
-   `deny` 的工具**不注册**，并按 `sandbox.on_deny` 决定
    `raise`（默认）还是 warn + 剔除；
-   产出 `ToolPlacementReport`（工具名 → placement），供日志与测试断言。

这是唯一能覆盖"用户 tools + MCP + plugin"全集的位置——
`resolve_tools()` 只处理配置里的工具组，**不能**当收口点。

**（2）运行期 `SoothePolicyMiddleware`（policy.py:51）** —— 已有最外层
`awrap_tool_call`，tool_name 与 args 都在这里。在此按 placement 分派；
`_extract_required_permission`（`policy_profiles.py:283-311`）已经是
"tool_name → 权限" 的唯一映射点，加 placement 分支即可接策略层。

**（3）路径 shim** —— 复用 `workspace_paths.py:93-125` 的双向映射范式，
新增 `remote_mode` 分支：`vm_path ↔ 宿主临时路径` 的互转。

#### 7.5.5 用户自定义工具与 MCP（fail-closed）

用户经 `create_nano_agent(tools=[...])` 传入的工具，当前在
`builder.py:135` 是裸 `extend`，**没有任何元数据或校验**；
`get_tool_meta(name)` 查不到时策略层兜底为
`Permission("fs","read","*")`（`policy_profiles.py:302`），即"默认放行"——
这在 sandbox 模式下是不可接受的静默破坏。

规则：

1.  sandbox 模式下，注册表查不到且未显式声明的工具 → **`deny`**（失败关闭），
    构建期给出可操作错误：

    ``` text
    Tool 'foo' has no placement declaration and a sandbox backend is active.
    Declare one of: @tool(..., placement="host"|"shuttle"|"guest"|"deny")
    or add to config: sandbox.placement_overrides = { foo = "host" }
    ```

2.  声明方式沿用现有 `@tool` 装饰器（`plugin/decorators.py:184-221`，已有
    `_tool_group` 等标签），新增 `placement` 参数；或走配置覆盖。
3.  **MCP 工具**：MCP server 本身已是远端进程，不在本模型内。但
    filesystem 类 MCP server 的根必须指向 VM 或显式 `deny`；
    默认按"有工作区副作用"处理。
4.  **subagent / skills**：自动一致——`create_deep_agent` 把同一 backend
    交给 subagent 与 `SkillsMiddleware`（`graph.py:870-884,966-978`），
    无需额外处理。

#### 7.5.6 `shuttle` 适配器细节（最易出错的部分）

```
模型调用 tool(path="/workspace/data.csv", ...)
   │
   ├─ 1. path_arg_keys 命中 → 判定该参数是 VM 路径   (ToolMeta.path_arg_keys)
   ├─ 2. backend.download_files(["/workspace/data.csv"]) → 宿主临时文件
   ├─ 3. 改写参数："/workspace/data.csv" → "/tmp/…/data.csv"
   ├─ 4. 调用原工具实现（代码零改动）
   ├─ 5. 若 outcome_type == "file_write" → upload_files 回传
   ├─ 6. 【关键】结果反向映射：把返回文本中的临时路径替换回 VM 路径
   └─ 7. 清理临时目录
```

第 6 步**最容易被漏**：工具（尤其 `data.*`、document 类）常把绝对路径
回进模型上下文；若不反向映射，模型下一轮拿到 `/tmp/xxx` 会全错，
且这种错误很隐蔽。

约束：

-   默认只读：非 `file_write` 工具不回传，避免无谓写放大。
-   体积上限：可配置 `sandbox.max_shuttle_bytes`（默认建议 32 MiB），
    超限直接报错而不是静默搬运 90 MB 数据集。
-   一致性：临时副本是快照；对同一文件的连续 shuttle 读写不保证线性一致，
    写路径必须显式回传并在日志标注。
-   目录/通配符参数：`path_arg_keys` 指向目录时按前缀批量 download，
    需限制条目数。

#### 7.5.7 阶段二可选项：Guest Tool Runtime（语义 B）

若 shuttle 因数据量大或必须"贴着数据跑"而不可行，可在 ArcBox 镜像内装
一个极小 RPC runtime（`soothe-tool-runtime` wheel + 由 `execute` 拉起的
服务），nano 侧工具退化为"schema 描述符 + RPC 调用"，placement 记为
`guest_native`。此时工具代码真的在 VM 内运行。

代价：镜像构建、版本对齐、guest 内依赖、凭证边界都需重新设计，
**另立 RFC**。第一阶段不采用。

#### 7.5.8 配置与验收

``` toml
[sandbox]
placement_overrides = { "analyze_image" = "shuttle", "my_tool" = "host" }
on_deny = "raise"            # raise | drop
max_shuttle_bytes = 33554432
```

验收：

-   [ ] `finalize_tools` 输出的 `ToolPlacementReport` 覆盖
        **全部**工具（config 组 + 用户 tools + MCP + plugin），无遗漏项。
-   [ ] 注册表未命中的工具在 sandbox 模式下被 `deny`（有断言）。
-   [ ] 每个 `protocol`/`guest` 工具在集成测试中命中 fake ArcBox client。
-   [ ] 每个 `shuttle` 工具的返回结果中不含宿主临时路径（反向映射断言）。
-   [ ] `host` 类工具确无工作区副作用（人工审计 + 配置白名单）。

## 8. 生命周期与配置

### 8.1 生命周期归属

第一阶段由上层调用者管理（通常是 Flowjet Session 层）：

``` text
Session created
  └── ArcBox SDK: Create sandbox → wait READY
        └── create_nano_agent(..., backend=ArcBoxBackend(sandbox_id=...))
              └── run agent loop
Session closed / expired
  └── stop/remove sandbox (caller policy)
```

`ArcBoxBackend` 只绑定已存在的 `sandbox_id`，构造时不隐式创建 VM。

### 8.2 配置接口

``` python
backend = ArcBoxBackend(
    sandbox_id=sandbox_id,
    client=arcbox_client,        # 省略则由 adapter 按 UDS 默认位置连接
    workspace_root="/workspace",
)
agent = create_nano_agent(config, backend=backend)
```

保留 fake/mock client 注入点。后续若需配置驱动，可加
`backend.type = "arcbox"`；本 RFC 不要求第一阶段实现自动创建。

### 8.3 依赖管理

-   `soothe-deepagents>=0.8.6,<1.0.0`（`pyproject.toml:26`）。`BaseSandbox`
    在 0.8.6 已可用，但**未在 `soothe_deepagents.backends` 顶层导出**
    （实测顶层只有 `LangSmithSandbox` / `LocalShellBackend` 等），需从
    `soothe_deepagents.backends.sandbox` 导入，并加存在性检查 + 版本门槛
    友好报错（范式见 `middleware/filesystem.py:55-78`）。
-   **仓库当前没有 lockfile**（无 `uv.lock` / `poetry.lock` /
    `requirements.txt`）。因此"锁定 arcbox 版本"只能靠
    `pyproject.toml` 的上界约束 + CI 兼容性测试，不能依赖 lockfile。
-   **决策更新（2026-10-17）**：`arcbox>=0.1.0,<0.2.0` 以**主依赖**形式
    进入 `pyproject.toml`（非 optional extra）——上文 optional extra
    提案作废。惰性导入设计保留（`src/soothe_nano/sandbox/__init__.py`
    不触发 SDK import；`ArcBoxBackend` 实例化时不传 `client` 才连接），
    `_ensure_sandbox` 的 ImportError 指引相应指向"core dependency /
    重装或注入自定义 client"。
-   `arcbox` 导入失败时，`src/soothe_nano/sandbox/__init__.py` 不应抛错，
    仅在实例化 `ArcBoxBackend` 时给出安装指引。

## 9. 凭证与安全约束

### 9.1 LLM API Key 不进入 Sandbox

禁止放入：ArcBox `CreateSandbox` 的 `env`、`cmd`、guest workspace 文件、
Dockerfile / template、VM 镜像或快照、工具参数或返回值。

**条款修正（2026-10-17）**：原文"`ArcBoxBackend` 不接受 `api_key` 参数"
不准确。`ArcBoxBackend` 确实接受 `api_url` / `api_key` / `socket_path`
（及 `ARCBOX_API_URL` / `ARCBOX_API_KEY` 环境变量回退），但它们是
**ArcBox daemon 凭证**——宿主机到 daemon 控制面的认证，host-only，
用于 `connect(sandbox_id)`；不是模型供应商凭证，也不进入 guest。
不变式不变：**模型 API Key 永不进入 backend 构造面、永不序列化进 VM**；
单测 `test_constructor_surface_holds_no_model_credentials` 以签名参数集
断言钉死（`api_key` 参数名仅指 daemon 凭证）。
§6.4 的 `CompositeBackend` 还额外保证宿主机框架态（含可能含敏感内容的
memory / conversation history offload）不落进 VM。

### 9.2 不静默回退

ArcBox 不可用时，工具返回明确错误并终止该次调用；**不得**回退到宿主机
shell 或本地 workspace。

### 9.3 输出与错误

-   不在 Backend 内自造字符截断（不要加 `max_output_bytes` 之类旋钮）：
    由 `enable_capture_offload = True` 走
    `execute_with_offload`，大输出落 guest 文件、只回 head/tail 预览，
    **`exit_code` 得以保留**——自造截断会丢退出码。
    捕获硬上限是模块级 `_EXECUTE_CAPTURE_MAX_BYTES = 10 MiB`
    （`sandbox.py:690`），非构造参数；`enable_capture_offload=False` 时命令
    不包装、全量返回，由中间件通用 eviction 兜底。
-   `enable_capture_offload = True` 的前提是 guest 有 POSIX shell +
    coreutils（见 §6.1 的 python3 要求一并验收），否则应置回 `False`。
-   错误消息中不打印环境变量、完整 SDK 请求对象或可能含凭证的配置。
-   命令执行结果是 Agent 的不可信输入，沿用现有工具结果处理策略。
-   不把 ArcBox daemon socket 暴露给 VM。

### 9.4 信任边界

-   ArcBox daemon 的本地 UDS V1 依赖 socket 文件权限，**没有额外 API 认证**。
    第一阶段只适合受控单用户 / 可信宿主机部署。
-   `BaseSandbox` 的文件能力全部由 `execute` 派生 → 任何拿到 Backend
    实例的代码都能在 VM 内执行任意命令。因此 Backend 实例不应暴露给
    不可信插件；plugin/MCP 工具默认按 §7.1 禁用。

### 9.5 第一阶段暂缓的强化措施

宿主机 Sandbox Manager、细粒度 session authorization、网络出口策略、
资源配额集中管理、审计日志与多租户策略。

## 10. 执行语义与错误处理

### 10.1 执行结果映射

| 语义 | 映射 |
|---|---|
| 退出码 | `ExecuteResponse.exit_code`；无法确定时 `None`（**不要当成失败**） |
| stdout / stderr | 合并进 `ExecuteResponse.output`（stderr 追加在 stdout 之后，空则不加前缀换行） |
| 超时 | `ExecuteResponse` 无 timeout 字段：按惯例返回 `exit_code=124` + output 文本说明 |
| 截断 | `ExecuteResponse.truncated = True` |
| sandbox 未就绪 / SDK 通信错误 | 返回 `ExecuteResponse(output="Error: ...", exit_code=None)`，不抛异常 |
| 不支持的能力 | `NotImplementedError`（中间件会捕获并转 error ToolMessage） |

### 10.2 超时

-   `execute` 接受关键字 `timeout: int | None`；未传时用 `default_timeout`。
-   若 ArcBox API 提供服务端执行期限，优先传递。
-   若 SDK 只有客户端等待超时，必须区分"等待超时"与"guest 命令已被终止"：
    前者不得声称命令已停止。
-   超时后按 ArcBox 能力查询执行状态或终止 execution，不得另起命令重试。

### 10.3 重试与幂等

第一阶段不自动重试非幂等 shell 命令。若 execution API 支持 execution ID /
output offsets / resume，用其恢复读取同一次 execution 的输出。

### 10.4 并发

-   不全局串行化，除非 Agent Harness 要求。
-   不在 `ArcBoxBackend` 内共享非线程安全的可变请求对象。
-   注意 `BaseSandbox` 的文件操作是"每条命令一次 execution"，
    并发写同一文件存在 race；沿用 harness 现有 edit lock 语义，测试需覆盖。

## 11. 代码改造清单

> **落地状态（2026-10-17，phase 1）**：第 1–4、7、9 项已落地
> （`sandbox/{__init__,arcbox}.py`、builder composite 包装与 permissions 降级、
> shell executor seam 五工具 guest 映射、`FILESYSTEM_TOOLS_SANDBOX` +
> `SANDBOX_EXCLUDED_TOOL_GROUPS`、`pyproject` `arcbox` extra、单测三套
> `tests/unit/sandbox` / `tests/unit/toolkits/test_shell_executor.py` /
> `tests/unit/agent/test_builder_sandbox.py`）。
> **暂缓项**：第 5 项全工具放置模型（placement/shuttle，host-bound 自定义
> 工具在 sandbox 模式暂由排除组兜底）、第 6 项 plan subagent 后端贯穿
> （planner 仍用宿主 `FilesystemBackend`，guest 路径对其不可见）、
> 第 10 项使用文档；均待真实 ArcBox 环境联调后推进。
> 偏差记录：`run_command` 超时在 guest 侧按 `exit_code=124` 约定回传
> （§10.1），由 `BackendShellExecutor` 映射回统一的超时文案；
> `kill_process` guest 分支跳过宿主 protected-kill 钩子（只保护宿主进程）。
> **2026-10-17 二轮修复（A-F）**：A=composite routes 补
> `/large_tool_results` + `/conversation_history`（Spike C 落定，见 §6.4）；
> B=§7.5.5 fail-closed 闸门前置落地（`config.sandbox` 的
> `placement_overrides` 白名单 + `on_deny: raise|drop`，默认 raise；
> 完整 placement 模型仍缓）；C=guest 后台进程 `setsid` + `kill -- -PGID`
> 进程组回收（无 setsid 时回退单 pid）；D=桥接超时不再标 124/不再声称
> 已杀（`may still be running`，与 SDK 服务端真超时区分）；E=planner
> subagent 在 sandbox 模式禁用+告警（宿主 `FilesystemBackend` 看不见
> guest 工作区，待后端贯穿后恢复）；F=四种交互模式 × sandbox 组合
> 全部有 builder 测试覆盖。
> **2026-10-17 更新**：`data` / `image` 工具组已从 nano 整体删除
> （§7.1 表中两行与 §7.5 默认推导表中对应的 shuttle 例子随之作废），
> sandbox 排除组收缩为仅 `file_ops`；shuttle 的剩余受益者只剩
> document/自定义工具场景，placement 模型（第 5 项）的优先级相应下调。
> **2026-10-18 真机 E2E 轮**：§12.4 全部十步 + §12.5 验收清单落地为
> `tests/integration/test_arcbox_e2e.py`（15 测试全绿，真机 daemon 0.9.0，
> Apple Silicon）。§13-2/3/4/11 风险随之钉死（`BaseSandbox` 0.8.6 路径
> 真机可用；四前缀路由行为级验证；offload heredoc 包装与 ArcBox shell
> 兼容，`offloaded=True` 正常）。**镜像前置检查发现真问题（§13-9 坐实）**：
> daemon 默认模板**没有 python3**；flowjet-arcbox 草稿模板的 python3 是
> 坏 wrapper（`exec /app/.venv/bin/python ""` 吞参 + venv 符号链接循环指回
> wrapper，guest 内无任何可用解释器，构建 bug 属 flowjet 模板范围）。
> 处置：构建 production 模板 `soothe-nano-e2e`
> （`python:3.12-slim-bookworm` + util-linux[setsid]/procps[kill -- -PGID]/
> coreutils/findutils/grep/sed/ca-certificates，512 MiB，digest
> `sha256:655e0721…`），E2E 以 `ARCBOX_E2E_TEMPLATE` 选择模板、daemon
> 不可达时干净 skip（无 daemon CI 仍绿）。
> 平台观察（flowjet/ArcBox 范围，非本仓）：沙箱创建偶发
> "stopped before becoming ready"（约 1/7，重试即可）。
> **2026-10-18 planner 贯穿（第 6 项完成，§7.2-7 落地）**：解除 sandbox 模式
> planner 禁用。`resolve_subagents(..., sandbox_backend=)` 把 composite
> backend 经 context 传入 `create_plan_subagent`；planner recon 工具
> （`get_planner_readonly_tools(backend=...)`）直接绑注入 backend，
> workspace 取 guest 根（`backend.workspace_root`，非宿主 work_dir）。
> host 模式零变化（`sandbox_backend=None` 走原 `FilesystemBackend` 路径）。
> **2026-10-18 placement 完整模型（第 5 项完成，§7.5 落地）**：
> 新增 `sandbox/placement.py`（五值枚举、`resolve_placement` 推导：
> config override > `@tool(placement=)` / `ToolMeta.placement` 显式声明 >
> category/outcome_type 默认表 > 注册表 miss → `deny` fail-closed；
> `wrap_shuttle_tool` shuttle 适配器：path_arg_keys 下载 → 宿主临时文件
> → 原实现 → file_write 回传 → 结果临时路径反查 → 清理，
> `sandbox.max_shuttle_bytes` 默认 32 MiB 超限报错）。
> builder 收口 `_finalize_tool_placements` 替换旧 name 白名单闸门，
> 产出 `ToolPlacementReport`（`builder.placement_report`）。
> config：`placement_overrides` 由 `set[str]`（host 白名单）升级为
> `dict[str, str]`（name → placement）；`@tool` 装饰器新增 `placement=`。
> §7.5.8 验收：report 覆盖全部工具 ✓（单测）、registry miss deny 有断言 ✓、
> shuttle 反查断言 ✓（无宿主临时路径泄漏）、host 类无副作用 = 既有
> infra 白名单 + 内置组审计 ✓；§7.5.7 Guest Tool Runtime 仍另立 RFC 不做。

### 11.1 `soothe-nano`

1.  新增 `src/soothe_nano/sandbox/{__init__.py,arcbox.py}`：
    `ArcBoxBackend(BaseSandbox)` 实现四个抽象成员 + `_ArcBoxSdkAdapter`。
2.  `AgentBuilder.build()`：
    - `resolved_backend` 解析提前到 `resolve_tools()` 之前；
    - 始终初始化宿主机 `FrameworkFilesystem`；
    - 注入 sandbox 时包 `CompositeBackend`（§6.4）；
    - sandbox 模式禁用 `file_ops` 组、按 §7.1(三) 扩充 allowlist；
    - 处理四种模式的 permissions 冲突（§2.3 D）。
3.  **`toolkits/shell.py` 重路由**（§7.1(二)，executor 注入；
    `execution` → `shell` 组改名已先期单独完成，见 §7.1 命名消歧）：
    - 抽内部 `CommandExecutor` 微协议（= `SandboxBackendProtocol` 执行面）；
    - `HostShellExecutor` 包装现有 `_run_shell_command_sync`（语义零变化）；
    - `build_shell_toolkit(..., executor=...)` 注入，sandbox 模式传
      注入的 backend、host 模式传 `HostShellExecutor`——**单代码路径，
      无双分支**；
    - `run_python` / `run_background` / `tail_background_log` / `kill_process`
      的 guest 映射同样走 executor；
    - 安全守卫、timeout clamp、输出格式化逻辑单份共用。
4.  `agent/interaction_mode.py`：新增 `FILESYSTEM_TOOLS_SANDBOX`
    及 ask / plan / bypass 只读变体。
5.  **全工具放置模型**（§7.5）：
    - `tools/metadata.py` 的 `ToolMeta` 增加 `placement` 字段；
    - 新增 `sandbox/placement.py`（`resolve_placement` / 默认推导表）；
    - 新增 `sandbox/finalize.py`（`finalize_tools` 构建期收口）；
    - 新增 `sandbox/shuttle.py`（字节搬运 + 结果反向映射）；
    - `middleware/policy.py:51` 增加运行期分派分支；
    - `plugin/decorators.py` 的 `@tool` 支持 `placement=` 参数；
    - `config/models.py` 增加 `[sandbox]` 配置块。
6.  `subagents/plan/engine.py:140` 改用注入后端。
7.  `pyproject.toml` 增加 `arcbox` optional extra。
8.  `create_nano_agent` / `create_dual_mode_nano_agent` 签名不变，补文档。
9.  新增测试（§12）。
10. 补充 `docs/arcbox-backend.md` 使用文档与 README 链接。

### 11.2 `flowjet`（集成方，非本 RFC 主要实现范围）

1.  Session 层调 ArcBox SDK 创建 Sandbox 并等 READY。
2.  构造 `ArcBoxBackend(sandbox_id=...)`，经 `create_nano_agent(..., backend=...)`
    注入。
3.  Session 结束时停止或删除 Sandbox。
4.  不向 Backend / Sandbox 传递模型 API Key。

## 12. 测试策略与验收标准

### 12.1 单元测试（无 ArcBox daemon）

用 fake SDK client 验证：

-   `execute` 参数正确映射；`exit_code` / stdout / stderr / timeout 正确转换。
-   `upload_files` / `download_files` 逐文件错误码与顺序一致。
-   继承 `BaseSandbox` 后 `ls`/`read`/`write`/`edit`/`glob`/`grep`/`delete`
    可用（直接用基类契约测试，不重复实现）。
-   `execute` 签名通过 `execute_accepts_timeout()`。
-   **shell toolkit executor 注入**：`run_command` 经注入的 executor
    执行（host executor 行为与今日 `subprocess` 路径逐字节一致，golden
    输出对比；sandbox executor 命中 fake backend）；`run_python` heredoc
    拼装无引号注入；`run_background` / `tail_background_log` /
    `kill_process` 的 guest 映射正确；同一 fake executor 覆盖两种模式。
-   `id` 是 property 且返回 `sandbox_id`。
-   所有请求都带 sandbox_id。
-   `upload_files` / `download_files` 对相对路径返回
    `invalid_path`（对齐上游惯例）。
-   SDK 异常 → `ArcBoxError` → `ExecuteResponse(error…)`，不抛穿。
-   异常路径不调用本地 `subprocess`。
-   Backend 不持有 / 不序列化 LLM API Key。
-   `resolve_placement()` 对已注册 ~45 个工具的推导结果与 §7.5.3 默认表一致。
-   shuttle：参数改写、写回传、**结果反向映射**（返回值不含宿主临时路径）、
    临时目录清理、超 `max_shuttle_bytes` 报错。

### 12.2 Builder 集成测试

-   注入 sandbox backend 后 `FrameworkFilesystem.get()` 不抛（§2.3 C 回归）。
-   工具列表中**不含** `file_ops` 系列同名重复注册。
-   `run_command` / `run_python` / `run_background` / `tail_background_log` /
    `kill_process` **仍在**工具列表且实现指向注入的 backend（§7.1(二)
    回归——这是最容易被漏掉的一条）。
-   工具列表中**不含** `execute`（保持隐藏，防双 shell）。
-   allowlist 含 `file_info` / `edit_lines` / `insert_lines` /
    `delete_lines` / `apply_diff`（补 `file_ops` 禁用后的缺口）。
-   `ToolPlacementReport` 覆盖**全部**工具（config 组 + 用户 tools + MCP +
    plugin），无未判定项；未声明的用户工具被 `deny`（§7.5.8）。
-   `read_file` 必在 allowlist（否则中间件 `ValueError`）。
-   ask / plan / bypass / `gp_mode == "per_step"` 四种模式 × sandbox
    均能构造成功（§2.3 D 回归）。
-   未注入 backend 时工具集与今日完全一致（向后兼容）。
-   `CompositeBackend` 路由：`/memories/x` → 宿主机后端，
    `/workspace/x` → ArcBox 后端。

### 12.3 Agent 集成测试（mock client）

-   Agent 的 `run_command` 调用命中 fake ArcBox client（不碰本地
    `subprocess`）。
-   `run_background` 在 guest 落 nohup 日志，`tail_background_log` 读 guest
    侧路径（§7.1(二) 路径注意），`kill_process` 走 guest 进程组。
-   文件工具写入的内容可由后续 guest shell 读到；反之亦然。
-   只读模式仍禁止写操作。
-   GP subagent 与 plan subagent 使用注入的 backend。
-   memory / skills 写入落在宿主机路由，不进 VM。

### 12.4 ArcBox 端到端测试（显式 opt-in，Apple Silicon M3+ / macOS 15+）

1.  创建 Sandbox 并等 READY。
2.  **镜像前置检查**：guest 内 `python3 --version` 与 POSIX coreutils 可用
    （否则 `read` / `edit` / `grep` 全废，见 §6.1）。
3.  执行 `pwd`、`uname -a`、简单 shell 命令。
4.  `write` 文件 → guest shell `cat` 读到；shell 创建文件 → `read` 读到。
5.  验证退出码、stdout、stderr、超时（`exit_code=124`）。
6.  验证 `glob` / `grep` / `edit_lines` / `apply_diff` 在 guest 生效。
7.  验证大输出走 capture-offload：`exit_code` 仍保留、输出被截断标记。
8.  重复调用不误创建多个 Sandbox。
9.  stop/remove 后操作返回明确错误。
10. 检查 guest 环境、启动参数、工作区与日志中无 LLM API Key。

### 12.5 验收标准

-   [ ] `create_nano_agent(config, backend=ArcBoxBackend(...))` 可构建 Agent。
-   [ ] 模型调用与 Agent Loop 仍在宿主机。
-   [ ] Agent 可见的 shell 工具（`run_command` 等）命令确实在 ArcBox guest
    中运行，工具名与 schema 与非 sandbox 模式一致。
-   [ ] 文件工具与 shell 使用同一份 guest workspace。
-   [ ] 不存在第二套宿主机 shell / 文件工具。
-   [ ] guest 镜像含 python3（否则 `read`/`edit`/`grep` 不可用）。
-   [ ] memory / skills / `.soothe` 仍在宿主机。
-   [ ] 与工作区无关的工具保持原有行为。
-   [ ] ArcBox 失败时不回退到宿主机执行。
-   [ ] LLM API Key 不传入 Sandbox 或 guest。
-   [ ] 默认不传 Backend 时行为不变。
-   [ ] 单元测试可在没有 ArcBox daemon 的 CI 中运行。
-   [ ] E2E 测试在受支持机器上通过。

## 13. 风险与待确认事项

| # | 风险 | 处置 |
|---|---|---|
| 1 | ArcBox Python SDK API 仍在变化 | 用 adapter 隔离；上界 pin；不做未验证的方法名假设 |
| 2 | `BaseSandbox` 未在顶层导出，属半私有路径 | 导入时做存在性检查 + 友好报错；与上游确认是否可稳定依赖 |
| 3 | `CompositeBackend` 路由前缀与 nano 框架态实际路径不匹配 | §6.4 spike：实测 memory / skills / offload 落盘路径 |
| 4 | ask / plan / bypass / per-step 下 permissions + execute 互斥 | 优先靠 Composite 路由覆盖；否则该模式不传 `_permissions`；四种模式实测 |
| 5 | `data` / `image` 工具禁用后能力下降（第一阶段可先禁用） | 走 §7.5.6 shuttle 改道；先以禁用保证一致性 |
| 6 | 无 lockfile，依赖版本只能靠上界 + CI | CI 增加 `soothe-deepagents` 最新兼容版本回归 |
| 7 | `BaseSandbox` 文件操作是"每操作一次 execution" → 慢、有并发 race | 若 SDK 有原生文件 API 则 override `read`/`write`；并发测试覆盖 |
| 8 | 平台限制（M3+ / macOS 15+ / VZ） | 其他平台启动时明确报错，不回退宿主机 shell |
| 9 | **guest 镜像缺 python3** → `read`/`edit`/`grep` 静默失效 | 写进 ArcBox template 验收；E2E 第 2 步前置检查 |
| 10 | allowlist 改动影响非 sandbox 路径 | `FILESYSTEM_TOOLS_SANDBOX` 仅在 sandbox 模式启用；加向后兼容断言 |
| 11 | `enable_capture_offload` 的 heredoc 包装与 ArcBox shell 不兼容 | E2E 验证；不兼容则回落 `False` |

## 14. 实施步骤

1.  **Spike A（协议）**：复核 `BaseSandbox` 四个抽象成员与
    `CompositeBackend` 路由行为（本文已核对 0.8.6，实施时复核当前版本）。
2.  **Spike B（SDK）**：最小脚本用 `arcbox` SDK 连接 Sandbox、执行命令、
    读写字节，确定 adapter 三个能力的可行性与错误类型。
3.  **Spike C（路径）**：实测 nano memory / skills / offload 的实际落盘
    前缀，确定 `CompositeBackend` 路由表；验证 guest 后台日志路径
    `/workspace/.soothe/background/` 不命中宿主机 route（§7.1(二)）。
4.  **Spike D（镜像）**：确认 ArcBox template 内含 **python3** 与
    POSIX coreutils（含 `nohup`/`kill`）—— 缺 python3 会让
    `read`/`edit`/`grep` 全部失效（§6.1）。
5.  **`ArcBoxBackend` 基础实现**：四个抽象成员 + adapter；不碰 builder。
6.  **Mock 单测**：`BaseSandbox` 契约 + 映射正确性（无 daemon）。
7.  **Builder 接线**：提前解析 backend、`FrameworkFilesystem` 修复、
    `CompositeBackend`、`file_ops` 收缩、**allowlist 扩充**、
    **shell toolkit 重路由**、plan subagent、四种模式的 permissions 冲突。
8.  **Builder 集成测试**：工具集断言（`run_command` 指向 backend、
    `execute` 不可见、无 file_ops 重复）+ 向后兼容断言。
9.  **全工具放置模型**（§7.5）：`ToolMeta.placement`、默认推导、
    `finalize_tools` 收口、shuttle 适配器、policy middleware 分派、
    `@tool(placement=...)`。
10. **Agent 集成测试**：真实 harness + fake client 全链路
    （含 run_background/tail/kill 的 guest 语义）。
11. **E2E 测试**：受支持 Mac 上跑真实 microVM（含镜像前置检查）。
12. **Flowjet 接入**：Session 层创建 Sandbox 并注入 Backend。
13. **后续 RFC**：Sandbox Manager、权限模型、网络策略、审计；
    Guest Tool Runtime（§7.5.7，语义 B）。

## 15. 最终决策

采用 **soothe-nano 内的可注入 `ArcBoxBackend`（继承 `BaseSandbox`）** 作为
第一阶段方案：

-   不改 Agent Loop，不把 Agent 放进 VM，不在 nano 内新增 Sandbox Manager；
-   复用 `soothe-deepagents` 的 `BaseSandbox` 与 `BackendProtocol`，
    只实现 `id` / `execute` / `upload_files` / `download_files` 四个成员；
-   用 `CompositeBackend` 让 guest 只承载 `/workspace`，框架态留宿主机；
-   **`shell` 保持 toolkit 路线**：保留注册、实现重路由到
    `backend.execute()`，工具名与 schema 不变；`file_ops` 组禁用、由中间件
    同名工具补位；中间件 `execute` 保持隐藏——保证有且仅有一套 shell 与
    一套文件工具；
-   Flowjet Session 层管理 Sandbox 生命周期；
-   LLM API Key 永远留在宿主机；
-   ArcBox 不可用时失败关闭，不回退到本机执行。

## 16. Phase-2：`file_ops` 与中间件 FS 统一（2026-10-18 落地）

**结果**：`file_ops` 工具组整体退役——中间件 FS 面成为文件工具唯一来源，
「同一 allowlist + 同一份中间件 + 仅 backend 不同」达成。

**探查后修正的事实**（与原方案假设有出入）：主图 FS 从来不是
`SootheFilesystemMiddleware` 进栈——builder 走
`create_deep_agent(filesystem_tools=...)`，上游在图内自建裸
`FilesystemMiddleware`（`graph.py:1038`）；`SootheFilesystemMiddleware`
只是工具工厂。双实例只存在于 host 模式（file_ops 组工具与中间件同名工具
同屏，`ToolNode.tools_by_name` 后写覆盖、file_ops 实例胜出，两者同源
同行为）。subagent 中间件本就复用同一 `filesystem_tools` allowlist
（`graph.py:870-880`）——坑 3 由统一自动消解。

**四个坑的实际处置**：

1.  **by-name replace**：不适用——没有自定义中间件进栈，无需 name 覆盖。
2.  **progressive deferred 工具**：`DEFERRED_FROM_CORE` 的
    `file_info` / `apply_diff` / `delete` 不再依赖组实例；目录填充回落
    `_ensure_catalog(request.tools)`（request.tools 本就含中间件工具），
    单一来源成立。
3.  **subagent 不对称**：subagent 的 FS 中间件本就带同一 allowlist，
    统一后 subagent 的手术工具与主 agent 同源（含 wrap 行为）。
4.  **行为回归面**：行为等价性由既有测试套保证（1980 单测全绿 +
    15 真机 E2E 全绿）；`tools.file_ops.enabled=False` 语义收窄为
    「从 allowlist 剔除手术族（`delete` 除外，属基础变面，与统一前
    生效行为一致）」，`builder.py` 在 allowlist 选择处统一施加。

**改动清单**：`FILESYSTEM_TOOLS_AGENT` 并入手术族；`SANDBOX_EXCLUDED_TOOL_GROUPS`
清空、`ASK_MUTATING_TOOL_GROUPS` 只剩 `shell`；resolver 移除组注册与
surgical 单独路由（单名路由统一走 `build_filesystem_tools`）；插件注册表
移除 `FileOpsPlugin`；`toolkits/file_ops.py` 删除，
`build_filesystem_tools` 迁至 `toolkits/filesystem_tools.py`，
`SURGICAL_FILE_OP_TOOL_NAMES` 收编进 `interaction_mode.py`。

（另：`file_ops` 统一后 §7.5 placement 模型的必要性进一步下降——
剩余受益者只剩 document/自定义工具场景。）
