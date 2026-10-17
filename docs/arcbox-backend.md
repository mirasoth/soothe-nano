# ArcBox Sandbox Backend 使用指南

> 面向集成方（session 层 / 宿主应用）的使用文档。设计细节、事实核对与
> 决策记录见 [soothe-nano-arcbox-backend-design.md](soothe-nano-arcbox-backend-design.md)（下称 RFC）。

## 1. 这是什么

`ArcBoxBackend` 把 nano 的执行面（shell 五工具 + 全部文件工具）搬进
[ArcBox](https://github.com/mirasoth) microVM 沙箱：agent 看到的文件系统和
命令都在 guest 里跑，宿主机只保留框架态（memory、skills 状态、会话产物）。

- 沙箱**生命周期归调用方**：backend 只连接已存在的 sandbox（按 id），
  从不创建或销毁 VM（RFC §8.1）。
- 依赖：`arcbox>=0.1.0` 是 **soothe-nano 的主依赖**（非 optional extra）；
  guest 镜像需自带 `python3` 与 POSIX coreutils（文件原语由 guest
  `execute` 派生，RFC §6.1）。

## 2. 快速开始

```python
from soothe_nano import create_nano_agent
from soothe_nano.config import SootheConfig
from soothe_nano.sandbox import ArcBoxBackend

# 1. 调用方用 arcbox SDK 创建 sandbox 并等 READY（略）
sandbox = ArcBoxBackend(
    sandbox_id="sbx-...",                # 已就绪的 ArcBox sandbox id
    workspace_root="/workspace",          # guest 默认 cwd
    default_timeout=120,                  # execute 兜底超时（秒）
)

# 2. 注入；backend 在构建期被自动包装，无需手工组 CompositeBackend
agent = create_nano_agent(SootheConfig(), backend=sandbox)
```

`ArcBoxBackend(sandbox_id=...)` 未显式传 `client` 时使用真实 arcbox SDK
适配器；daemon 连接参数（`api_url` / `api_key` / `socket_path`）有
`ARCBOX_API_URL` / `ARCBOX_API_KEY` 环境变量回退。**测试时注入自定义
client**（实现 `run` / `read_bytes` / `write_bytes` 三方法的协议
`ArcBoxClient`）即可，无需 daemon。

## 3. 构建期自动发生的事（RFC §7）

检测到 `SandboxBackendProtocol` 后端时，`AgentBuilder` 进入 sandbox 执行模式：

| 项 | 行为 |
|---|---|
| backend 包装 | 裸 sandbox 被包成 `CompositeBackend`：`/memories`、`/.soothe`、`/large_tool_results`、`/conversation_history` 四前缀 → 宿主机后端，其余路径（含 guest 侧 `/workspace/.soothe/...`）→ sandbox。框架态不随 VM 销毁丢失（RFC §6.4）。调用方传入的 composite 信任原样使用。 |
| `shell` 组 | `run_command` / `run_python` / `run_background` / `tail_background_log` / `kill_process` 实现重路由到 `backend.execute()`，工具名与 schema 不变；安全守卫、timeout clamp、输出格式化单份共用。 |
| `file_ops` 组 | 整组禁用——`FilesystemMiddleware` 的同名中间件工具接管（经 sandbox backend 落 guest）。 |
| FS allowlist | 扩充为 `FILESYSTEM_TOOLS_SANDBOX`（agent 面 + `file_info` / `edit_lines` / `insert_lines` / `delete_lines` / `apply_diff`）。upstream 的内置 `execute` 工具保持隐藏——guest shell 只有 `run_command` 一个入口，防双 shell。 |
| permissions | 全部丢弃（sandbox backend 不支持宿主写拒绝语义），ask/plan/bypass 下打 warning；只读强制回落到工具 allowlist。 |
| planner subagent | 禁用并告警——其自建宿主 `FilesystemBackend` 看不见 guest 工作区（后端贯穿后恢复，RFC §7.2-7）。 |
| GP subagent | 由 `agent.runtime.general_purpose_subagent` 控制：`off` / `full` / `readonly`（write-deny 降级为只读工具面）/ `per_step`（注册 `general-purpose-readonly` 变体供宿主中间件重定向；sandbox 下两条变体都不带宿主 permissions）。 |
| 未声明工具闸门 | 无声明放置的自定义 / MCP / 插件工具默认**拒绝构建**（fail-closed），见 §4。 |

## 4. 工具放置闸门（fail-closed）

sandbox 模式下，builtin 组之外的每个工具（用户 `tools=[...]`、MCP、插件）
都必须有声明的放置，否则默认抛 `ValueError` 中止构建。宿主侧的自定义工具
二选一：

```yaml
sandbox:
  on_deny: raise            # 默认；"drop" 则改为剔除 + warning
  placement_overrides:      # 声明「已审查、允许留在宿主机」的工具名
    - my_reviewed_host_tool
```

纯元数据目录工具（`search_tools` / `search_skills` / `invoke_skill` /
`search_mcp_tools` / `mcp_resources_list`）内置豁免。

## 5. 凭证与安全边界（RFC §9）

- `api_key` 只是 **ArcBox daemon 凭证**（宿主 → daemon 的控制面认证），
  不是模型 API key。**模型凭证永不进入 backend、永不序列化进 VM**——
  单测钉死构造面（`test_constructor_surface_holds_no_model_credentials`）。
- backend 错误一律**错误即数据**（`ExecuteResponse(error=...)` /
  `ArcBoxError` 映射），异常路径不触碰宿主 `subprocess`。
- 不静默回退：guest 不可用就是错误，不会降级到宿主机执行。

## 6. 执行语义（RFC §10）

- 超时两套语义，严格区分：
  - **SDK 服务端真超时**：guest 进程组被杀，按 nano 约定回传
    `exit_code=124` + 提示文案；
  - **桥接超时**（sync 侧等待 deadline，默认命令超时 + 30s 余量）：
    只取消等待方，**不声称已杀**，错误文案注明 "the guest command may
    still be running"。
- guest 后台进程经 `setsid` 成独立进程组，`kill_process` 用
  `kill -- -PGID` 整组回收（无 setsid 时回退单 pid）。
- `default_timeout` 兜底 120s；`FilesystemMiddleware` 的
  `max_execute_timeout` 上限（3600s）恒大于它。

## 7. 测试与验证现状

- 无 daemon 单测三套：`tests/unit/sandbox/`（backend 契约 + 不变量）、
  `tests/unit/toolkits/test_shell_executor.py`（executor 注入 + 异常路径
  不碰宿主 subprocess）、`tests/unit/agent/test_builder_sandbox.py`
  （composite 路由、四模式 × sandbox、放置闸门、execute 隐藏、GP 变体）。
- 真机 E2E（RFC §12.4/12.5，Apple Silicon M3+ / macOS 15+）未跑，
  属后续里程碑。

## 8. 已知限制（phase 1）

- `file_ops` 与中间件 FS 工具的双实例未统一（方向已定，须独立 phase-2
  PR；涉及 by-name replace 对 Soothe 子类失效、progressive 分层静默吞
  deferred 工具、subagent 中间件不继承三个坑）。
- 全工具放置模型（placement / shuttle，RFC §7.5）只有 fail-closed 闸门
  先行；plan subagent 后端未贯穿。
- nano 2.0.0 发布列车内：本能力随 `[Unreleased]` 交付。
