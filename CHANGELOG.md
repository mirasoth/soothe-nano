# Changelog

All notable changes to soothe-nano are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.19] - 2026-08-14

### Changed
- **Removed the Muse-Glimmer-specific adapter** (`soothe_nano.utils.llm.muse_glimmer`,
  816 lines) and its test suite (514 lines). The model-agnostic implementation in
  `OpenAICompatModelWrapper` — tool_choice sanitization, `json_schema`
  structured-output routing, thinking-token stripping, and the streaming
  auto-fallback — already covers every OpenAI-compatible provider, so the
  dedicated protocol adapter is no longer needed. New local models sharing the
  wire protocol keep working without a code change.
- **`bind_tools` re-wraps the bound model** in a new `OpenAICompatModelWrapper`
  so thinking-token stripping and the streaming auto-fallback still apply on
  every tool-bound invocation; the previous release shipped this fix but it
  was shadowed in some local installs and is now confirmed green.

### Fixed
- Lockfile markers for platform-conditional dependencies (`zipp` on Python
  <3.12, `cryptography`/`jeepney` on non-Windows) so `uv sync` resolves cleanly
  across platforms.

## [1.1.18] - 2026-08-13

### Changed

- **Protocol detection is now content-based, not name-based.** The
  `muse_glimmer` adapter runs on every generation via
  `OpenAICompatModelWrapper` and no-ops when the wire markers
  (`to=self<|message|>`, `<|eom|>`, `<atem:`) are absent. New models sharing
  the protocol work without a code change or name match.
- **Streaming auto-fallback.** `_stream`/`_astream` now catch LangChain's
  `No generations found in stream` (a server ignoring `stream: true`, e.g.
  vLLM-Metal) and transparently retry via `_generate`/`_agenerate`. Broken
  streaming endpoints self-heal without `streaming: false`.
- **Provider-level `max_tokens`.** `ModelProviderConfig` accepts `max_tokens`;
  `get_provider_kwargs` injects it into `init_chat_model` kwargs so servers
  that truncate when the field is omitted (vLLM-Metal mid-tool-call) set it
  once at the provider level. Caller params still take precedence.
- **`bind_tools` re-wraps the bound model** so the adapter and auto-fallback
  apply on every tool-bound invocation.

### Removed
- `_is_muse_glimmer_model` name-based detection and the `muse_glimmer` flag on
  `OpenAICompatModelWrapper` / `LLMFactory` — superseded by content
  detection.

## [1.1.17] - 2026-08-13

### Added
- **Muse-Glimmer response adapter** (`soothe_nano.utils.llm.muse_glimmer`):
  handles the self-talk wire protocol (`to=self<|message|>…<|eom|>` followed
  by `<|start|>assistant to=user<|message|>…`) emitted as raw `content` by
  vLLM-Metal (`localhost:9543`) and oMLX. Strips self-talk, extracts the
  `to=user` reply, parses six tool-call XML dialects into structured
  `tool_calls` (+ `tool_call_chunks` for streaming), and detects the
  vLLM-Metal chat-template repetition loop.
- Document parsing for Word, PowerPoint, OpenDocument, `.rtf`, and `.epub`
  via `firecrawl-anydoc` (Rust converter, GIL-releasing).
- `ExtractTextTool` advertises and routes the new Office/OpenDocument
  formats.

### Changed
- `LLMFactory` injects a default `max_tokens=2048` for Muse-Glimmer models
  so vLLM doesn't truncate mid-tool-call XML.
- `OpenAICompatModelWrapper` accepts `streaming` and `muse_glimmer` flags;
  when `muse_glimmer` is set, `_generate`/`_agenerate` transform every
  `AIMessage`, and `_stream`/`_astream` buffer the full turn and emit one
  transformed chunk so live reasoning tokens never leak.
- `bind_tools` re-wraps the bound model so the adapter applies on every
  tool-bound invocation; `_extract_tool_param_order` feeds bound tool
  schemas for positional-arg-to-keyword mapping.
- `_parse_document` routes `_ANYDOC_EXTENSIONS` to `_parse_with_anydoc`,
  falling back to PDF/DOCX/TXT.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.16...v1.1.17

## [1.1.16] - 2026-08-13

### Changed
- `LLMFactory` now reads a per-provider `streaming` flag (default `True`) from
  `ModelProviderConfig` and passes `streaming`/`stream_usage` to
  `init_chat_model` accordingly. The model cache key no longer hard-codes
  `streaming:` so providers with the same spec but different streaming settings
  no longer collide.
- `ProviderRegistry.get_provider_streaming` resolves whether LangChain should
  stream a provider's responses; returns `True` for unknown providers.

### Removed
- `soothe_nano.utils.llm.muse_glimmer` adapter and its test suite
  (`tests/unit/utils/llm/test_muse_glimmer_adapter.py`). The adapter worked
  around an oMLX/vLLM-Metal prototype endpoint that ignores `stream: true` and
  returns a single non-SSE JSON body. Instead of translating the model's
  internal self-talk protocol per-model, disable streaming at the provider
  level (`streaming: false`) so LangChain's non-streaming `_agenerate` path is
  used.
- `muse_glimmer` flag and auto-detection (`_is_muse_glimmer_model`) from
  `OpenAICompatModelWrapper` and `LLMFactory`; the `muse_glimmer` exports were
  dropped from `soothe_nano.utils.llm.__init__`.

### Fixed
- `ModelProviderConfig.streaming` field (default `True`) lets a provider opt
  out of streaming for OpenAI-compatible servers whose streaming endpoint is
  broken or unsupported (e.g. vLLM-Metal prototype), avoiding
  `No generations found in stream` errors.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.15...v1.1.16

## [1.1.15] - 2026-08-12

### Added
- Muse-Glimmer response adapter (`soothe_nano.utils.llm.muse_glimmer`): the
  oMLX endpoint model emits a self-talk protocol (`to=self<|message|>…`)
  as raw content and embeds tool calls as XML (``<atem:function_calls>``/
  ``<atem:invoke>``, ``<function name="…"><arg>``, self-named
  ``<read_file file_path="…"/>``) never as structured `tool_calls`. The
  adapter strips self-talk, extracts the `to=user` reply into `content`,
  and parses all six tool-call dialects into structured `tool_calls`
  (+ `tool_call_chunks` for streaming). Streaming turns are buffered and
  emitted as one transformed chunk because the live tokens are internal
  reasoning that must be hidden anyway. Wired into
  `OpenAICompatModelWrapper` via a `muse_glimmer` flag (auto-triggered for
  model names starting with `muse-glimmer`); `bind_tools` re-wraps the
  bound model so the adapter applies on every tool-bound invocation.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.14...v1.1.15

## [1.1.14] - 2026-08-12

### Fixed
- `computer_use` vision loop: attach the latest screenshot as a multimodal
  `image_url` block so the model can see the desktop instead of stalling on
  repeated screenshot-only steps; auto-capture an observation before the first
  step and after each UI action (`action_delay_s`); nudge after consecutive
  observe-only actions; treat screenshot/wait-only runs as no-progress; probe
  and correct Retina `coordinate_scale` from the first full-screen capture.
- `computer_use` input backend: missing `pyautogui` now raises
  `DesktopInputUnavailableError` with install guidance, is logged as
  `input_unavailable` at startup, and is returned as a step-level error rather
  than aborting the whole run (macOS screenshots can still work via
  `screencapture`).
- Stop emitting the noisy `soothe.internal.policy.checked` event on every
  policy check; denials still emit `PolicyDeniedEvent`.

### Changed
- Default `computer_use` `max_steps` raised from 10 to 99.
- Example `07_nano_computer_use_weixin_favorites.py`: bring WeChat forward via
  Spotlight and rely on auto-detected coordinate scale.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.13...v1.1.14

## [1.1.13] - 2026-08-12

### Added
- `computer_use` subagent: `create_computer_use_tools` and
  `resolve_computer_use_backend` factory functions for direct main-agent
  desktop-tool binding (Style 1 — routed delegation), exported from the
  `soothe_nano.subagents.computer_use` package.
- Foreground session tracking for `run_command`: writes
  `{workspace}/.soothe/foreground/fg-{pid}.session` markers while a
  synchronous shell command is in flight so host cancel can reap the
  process group (mirrors the existing `run_background` log tracking).
  New helpers `_register_foreground_session` /
  `_unregister_foreground_session` / `_foreground_session_path` /
  `_resolve_foreground_session_dir` in `toolkits/execution.py`.
- Examples `06_nano_computer_use_example.py` (desktop GUI automation via
  the computer_use subagent) and `07_nano_computer_use_weixin_favorites.py`
  (WeChat Favorites article-link harvester).

### Changed
- `examples/_shared/config.py` injects the repo `src/` dir onto `sys.path`
  so examples run under a foreign venv with a stale flat-snapshot install.
- System prompt: the `computer_use` subagent is advertised in the
  subagent guide and noted as reachable via the `task` tool rather than
  bound directly on the main agent.

### Fixed
- `RunCommandShellTool`: foreground `run_command` invocations now register
  an in-flight session marker so cancellation drains the child process
  group even for synchronous commands; marker is removed on exit.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.12...v1.1.13

## [1.1.12] - 2026-08-11

### Fixed
- `computer_use` subagent: add missing `CallbackManagerForToolRun` import to
  `tools.py` (fixes F821 undefined name at 4 sites) and apply ruff format to
  subagent files and tests (fixes format-check on 6 files). CI verified:
  ruff check passed, ruff format --check clean (444 files), pytest unit
  1596 passed / 42 skipped / 0 failed.
- LLM stack: strip inline thinking tokens (`<think>`, `<thinking>`,
  `<reasoning>`) from DeepSeek-R1-style local model output. Adds
  `thinking_filter.py` with `strip_thinking` (stateless, complete blocks) and
  `ThinkingStreamFilter` (stateful, buffers partial tag fragments split across
  streaming chunks). Stripped content is logged at DEBUG before removal.
- Wire the thinking filter through the LLM stack:
  - `SootheConfig.hide_thinking_tokens` (default `True`; env override
    `SOOTHE_HIDE_THINKING_TOKENS`).
  - `LLMFactory._apply_wrapper_chain` passes the flag to both
    `OpenAICompatModelWrapper` and `SootheTokenUsageChatModel`.
  - `OpenAICompatModelWrapper` strips blocks in `_generate/_agenerate` and
    filters streaming deltas in `_stream/_astream` with per-stream
    `ThinkingStreamFilter` instances.
  - `SootheTokenUsageChatModel` carries the flag for consistent downstream use.
  - `llm_response_text` strips thinking from assembled responses.
  - Export `strip_thinking`/`ThinkingStreamFilter` from the llm package.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.11...v1.1.12

## [1.1.11] - 2026-08-10

### Fixed
- Fallback (no-index) skill scan and `resolve_skill_directory` now label
  `.agents/skills` as `"agents"` and `.soothe/skills` as `"project"`,
  matching the index path. Previously the fallback path used only `"user"`
  for all non-builtin skills, causing inconsistent source labels between
  the fast (indexed) and legacy (full-scan) code paths.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.10...v1.1.11

## [1.1.10] - 2026-08-10

### Changed
- Version bump for maintenance release.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.9...v1.1.10

## [1.1.9] - 2026-08-10

### Changed
- Version bump for maintenance release.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.8...v1.1.9

## [1.1.8] - 2026-08-09

### Changed
- Version bump for maintenance release.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.7...v1.1.8

## [1.1.7] - 2026-08-08

### Changed
- Default `agent.middleware.llm_rate_limit.concurrent_limit` from `8` to `2`
  and `global_concurrent_limit` from `0` to `4` (safer under typical provider
  concurrency quotas; raise for higher-tier APIs).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.6...v1.1.7

## [1.1.6] - 2026-08-08

### Fixed
- `llm_rate_limit_config_from` reads `agent.middleware.llm_rate_limit` instead
  of the removed `agent.loop` path, so direct LLM calls (planner, classifiers,
  autopilot reasoners) honor configured timeouts, retries, and concurrency.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.5...v1.1.6

## [1.1.5] - 2026-08-08

### Added
- `agent.middleware.llm_rate_limit.global_concurrent_limit` (default `0` =
  no global cap), wired to `soothe-deepagents` process-wide LLM concurrency
  slots; per-budget `concurrent_limit` still applies

### Changed
- Require `soothe-deepagents>=0.8.5` for loop-safe LLM rate-limit registry

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.4...v1.1.5

## [1.1.4] - 2026-08-06

### Fixed
- Pin `langchain-mcp-adapters<0.3.1` and `mcp<2.0.0` so standalone CI lock
  resolution stays compatible (mcp 2.0 broke `RequestContext` imports).
- MCP auth transport unit tests import `langchain_mcp_adapters.client` before
  `patch()`.

### Changed
- Web search/crawl (`wizsearch_search` / `wizsearch_crawl`) now call `tarzi>=0.2.3`
  directly. Dropped the `wizsearch` package dependency. Tool names and
  `tools.wizsearch` config keys are unchanged for compatibility. Engines are an
  ordered failover list; crawl uses tarzi WebFetcher (plain HTTP → browser).
- Default `tools.wizsearch.default_engines` is now
  `tavily → google_serper → duckduckgo → bing → brave` (API engines plus
  tarzi's built-in web defaults).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.2...v1.1.4

## [1.1.3] - 2026-08-06

Yanked / not published (CI lock pulled mcp 2.0 incompatibly). See 1.1.4.

## [1.1.2] - 2026-08-04

### Added
- `looprail-creator` builtin skill: authors and validates Soothe LoopRail YAML
  workflow patterns for Autopilot. Covers event/when/then protocol, CE builtins
  only, draft→promote workflow, and protocol-invariant checks. Includes
  `references/looprail-protocol.md` and `references/templates.md`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.1...v1.1.2

## [1.1.1] - 2026-07-31

### Added
- Dual ASK / AGENT interaction modes (opt-in). Default remains AGENT and is
  behavior-compatible for existing callers.
  - `create_nano_agent(..., interaction_mode="ask"|"agent")` and
    `agent.runtime.interaction_mode` config (default `agent`).
  - Hard Ask: read-only `filesystem_tools`, write-deny permissions, `ask`
    policy profile, no `execution`/`file_ops` tool groups, planner-only
    subagent allowlist, Ask system-prompt suffix.
  - Opt-in `DualModeCoreAgent` / `create_dual_mode_nano_agent` with per-thread
    mode pin.

### Removed
- `CodingCoreAgent` compatibility alias; use `SootheNanoAgent`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.0...v1.1.1

## [1.1.0] - 2026-07-31

### Fixed
- `delete` tool no longer crashes with `TypeError: async_delete() missing 1
  required positional argument: 'runtime'`. `SootheFilesystemMiddleware` wrapped
  the tool's `func`/`coroutine` in `*args, **kwargs` closures to supply the
  default `backup_dir`, which erased the `ToolRuntime` annotation that `ToolNode`
  reads to decide what to inject. The default is now supplied only through
  `wrap_tool_call` / `awrap_tool_call`, leaving tool signatures intact.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.15...v1.1.0

## [1.0.15] - 2026-07-31

### Fixed
- Structured chat: bind-time `jsonschema.ValidationError` from
  `JsonSchemaModelWrapper` (e.g. reasoning models returning `{}`) now gets one
  repair-hint retry and method fallback instead of failing the call immediately.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.14...v1.0.15

## [1.0.14] - 2026-07-31

### Changed
- File-operation backups now default to workspace `.soothe/backups` (configured
  in nano) instead of scattered `.backups` folders. `SootheFilesystemMiddleware`
  injects this path when delete omits `backup_dir`; soothe-deepagents remains
  brand-neutral with its own `.backups` default.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.13...v1.0.14

## [1.0.13] - 2026-07-31

### Fixed
- Structured chat: when `function_calling` returns `None` (model emits schema
  JSON in content without a tool call), fall through to `json_schema` /
  `json_mode` instead of retrying the same method. Callers can pass
  `methods=` to prefer JSON response formats on the first request (intake
  classifiers).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.12...v1.0.13

## [1.0.12] - 2026-07-30

### Fixed
- Require `wizsearch>=1.1.9` (pulls `tarzi>=0.1.11`) so blocking web search
  releases the Python GIL. Previously tarzi held the GIL across headless-browser
  I/O and froze the daemon event loop / WebSocket heartbeats during
  `deep_research` / wizsearch fan-out.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.11...v1.0.12

## [1.0.11] - 2026-07-29

### Fixed
- browser_use subagent now stops the browser `Agent.eventbus` from an outer
  `finally` on both happy and failure paths. Previously the bubus `_run_loop`
  re-armed on `CancelledError` and the process hung forever after the answer
  was already printed.
- `operation_guard` denies bare `kill <pid>` against the live daemon, self, or
  parent via protected-kill hooks; banned-command patterns cover common shell
  idioms (port 8765, pidfile, `pgrep soothed`) that resolve the daemon PID.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.10...v1.0.11

## [1.0.10] - 2026-07-29

### Fixed
- `RunBackgroundTool` now declares `RunBackgroundInput` / `args_schema` so LangChain
  strips unknown LLM kwargs (e.g. Cursor-style `description`) instead of raising
  `TypeError: _arun() got an unexpected keyword argument 'description'`.
- Diagnose only fails providers used by the active profile.
- Planner recon tools run via `ToolNode` so `ToolRuntime` injection works.

### Added
- Readonly recon tools for the plan-design subagent.
- Planner stage progress events; nano logs surface in `soothe.log`.

### Changed
- Require `soothe-sdk>=1.0.7`.
- Planner produces a solution report (goal-completion proposal) instead of an
  investigation roadmap.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.8...v1.0.10

## [1.0.8] - 2026-07-25

### Added
- Public `soothe_nano.diagnose` API for package-owned doctor checks (`tool_deps`,
  `providers`, `observability`; deep: MCP, vector stores, models, protocols).
- Tool dependency checks use deepagents `get_rg_bin` / `get_fd_bin` helpers.

### Fixed
- Diagnose status aggregation no longer prefers lexicographic `"ok"` over
  `"error"` when combining `CheckStatus` values (`StrEnum` + `max()`).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.7...v1.0.8

## [1.0.7] - 2026-07-25

### Fixed
- Import `is_rg_available` from `soothe_deepagents.backends.grep_search` (filesystem re-exports were missing in deepagents 0.8.3).
- Omit LangGraph `durability` kwargs when no checkpointer is present (ephemeral execute twin).

### Changed
- Require `soothe-deepagents>=0.8.4` for directory-capable glob (`fd` + scandir) and `grep_search` helpers.
- Workspace/local glob uses deepagents discovery helpers directly; drop the local `grep_search` shim.

### Added
- Directory glob coverage (`trailing /`, `include_dirs`) in unit tests.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.6...v1.0.7

## [1.0.4] - 2026-07-24

### Fixed
- `toolkits.execution` no longer depends on the sunset `langchain-experimental` `ShellTool` / `PythonREPL`; `run_command` and `run_python` are now implemented on `BaseTool` with an in-process REPL. `datetime.utcnow` replaced with timezone-aware UTC.
- Bump `soothe-sdk>=1.0.6` (required for the unified SQLite runtime contract).

### Changed
- Unify SQLite durability, vector store, and persistence under a single process-scoped runtime (`sqlite_runtime`) with a shared runtime lifecycle and pool registry, matching the PostgreSQL control-plane shape.
- Rewrite `sqlite_store` and `sqlite_vec` to route through the runtime, dropping redundant per-instance connection plumbing.
- Centralize SQLite path resolution in `paths.sqlite_paths`, threaded through config models/settings and the resolver infra.
- Align `postgres_pool_lifecycle` / `postgres_pool_registry` with the unified runtime shape.

### Added
- `tests/unit/persistence/test_sqlite_runtime.py` covering the new SQLite runtime.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.3...v1.0.4

## [1.0.3] - 2026-07-24

### Changed
- Drop SDK re-export shims in `events` and `plugin` packages; import the canonical registry and plugin contracts directly from `soothe_sdk`.
- Expose the `project_instructions` prompt module as part of the public API surface.
- Minor refactors in MCP config and the academic / deep research subagent implementations.

### Removed
- Dead code swept across grep search, MCP reconnect, middleware tool-name hints, backend ops, polite HTTP, browser CDP, circuit breaker, outcome preview, prompt clock, and text preview modules.
- Host-owned constants pruned from `events.constants`; nano references only its own protocol type strings.
- Pruned unit tests tied to removed dead code: grep search, static headers provider, prompt clock, text preview, and MCP auth.

### Fixed
- Internal reference numbering aligned to the canonical scheme across tests and module docstrings.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.2...v1.0.3

## [1.0.2] - 2026-07-23

### Fixed
- `ToolOptimizationMiddleware` now redirects simple shell content/path searches (`grep`, `egrep`, `fgrep`, `ag`, literal `rg`, `find -name`) to the native `grep` / `glob` tools, while keeping an escape hatch for true-regex `rg` invocations (metacharacters or explicit regex flags).
- `discovery_hints` module exposes search-backend (`ripgrep` / `python_fallback`) detection helpers.
- Active search backend surfaced in the environment context XML and system-prompt guidance.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.1...v1.0.2

## [1.0.1] - 2026-07-22

### Added
- `WorkspaceAwareBackend.virtual_mode` property and `bind_workspace()` method so deepagents `FilesystemMiddleware` can bind nested task workspaces without host config objects.
- `ToolOptimizationMiddleware`: short-circuit empty `write_todos` payloads and guide on repeated same-path `read_file` slices; expose new metrics counters.
- Tests: workspace-aware backend IG-645 coverage and tool optimization middleware regression tests.

### Changed
- Require `soothe-deepagents>=0.8.2` for workspace bind / GP middleware propagate support.
- `WorkspaceContextMiddleware` resolves `virtual_mode` from the live backend / workspace context instead of injecting `soothe_config`; opts into `propagate_to_general_purpose` so middleware carries into subagents.
- `system_templates`: prefer one wider `read_file` over many offset/limit slices; restrict task subagent to multi-hop reasoning, not mechanical repo search.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.0.0...v1.0.1

## [1.0.0] - 2026-07-22

### Added
- `ErrorGeneralEvent` registered in the shared `REGISTRY` — canonical `soothe.error.general.failed` model for stream/wire error payloads.
- `mcp-builder` builtin skill for MCP server development, loaded on demand with `skill-creator` instead of at cold start.

### Changed
- Raise `AgentRuntimeConfig.recursion_limit` default from 200 to 9_999 to reduce spurious recursion caps during deep agent runs.
- Decouple nano from the host package: fix import paths from `soothe` to `soothe_nano` in filesystem README, browser-use preview docstring, and toolkits internal docstring.
- Add host extension points in `PostgresPoolRegistry`: template methods `_databases_to_open()` and `_initialize_pool_schema()` let host subclasses prepend checkpoints DB and add schema bootstrap.
- Add injectable pool class params (`metadata_pool_cls`, `checkpointer_pool_cls`) to `resolve_durability`/`resolve_checkpointer` so the host can inject registry-bound subclasses.
- Add `_REGISTRY_CLS` class attribute to `SharedCheckpointerPool` for host subclass override of the backing registry.
- Update resolver and test imports from `soothe.runner.resolver` to `soothe_nano.resolve` (module path migration).
- Point docs and tests at `soothe.coreagent` / `soothe.sloop` instead of the removed `soothe.foundation` namespace.
- Require `soothe-sdk>=1.0.5` for the updated wire constants.

### Removed
- `pytest.importorskip("soothe")` guards from tests; replaced host Veritas schema import with inline schema; dropped Executor tests that depended on host `soothe.sloop`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v0.9.9...v1.0.0

## [0.9.9] - 2026-07-21

### Added
- Extensible builtin skill roots and MCP server catalog — `skill-creator` and `mcp-builder` load on demand; the builtin skill index discovers skill roots without cold-start cost.

## [0.9.8] - 2026-07-21

### Changed
- Share paths via `soothe_sdk` and make the metadata pool extensible — nano no longer hard-codes workspace path resolution; path contracts come from the SDK.

## [0.9.7] - 2026-07-21

### Removed
- Unused / host-owned direct dependencies: `aiosqlite`, `anyio`, `pexpect`, `bubus`, `jinja2`, `openai`, `anthropic`, `pyjwt`, `langgraph-checkpoint-sqlite`, `arxiv`, `tavily-python`, `chardet`, `watchdog` (host already declares checkpointer/JWT/jinja/watchdog; `openai` remains via `langchain-openai`)

### Fixed
- `security.operation_guard` no longer bans remote git operations (e.g. `git push` / `git fetch`); these are gated by the `allow_out` network policy instead. Banned pattern removed; remote git is now permitted for CI and commit workflows.

### Changed
- `events.catalog` no longer redefines `EventRegistry` / `EventMeta` / `EventPriority` / `register_event` locally; it re-exports the canonical implementations from `soothe_sdk.core.registry` and registers protocol events via the shared `register_event`.
- `events.constants` keeps only the protocol type strings nano's own models reference; host-owned MCP/plugin/skill/replay constants removed.
- `plugin.events` corrects type identifiers to `soothe.internal.plugin.*` to match the internal domain classification.
- `skills.events` removes host-owned `SkillActivatedEvent`.
- `resolve._resolver_infra._resolve_sqlite_checkpointer` docstring clarified: it resolves the SQLite checkpointer database path and defers `AsyncSqliteSaver` creation to async context (same pattern as PostgreSQL); callers constructing the saver require `langgraph-checkpoint-sqlite`.

## [0.9.6] - 2026-07-21

### Removed
- `logging.thread_logger.ThreadLogger` (host-owned at `soothe.logging.thread_logger`)
- `config.reload.ConfigWatcher` / `ConfigReloadEvent` / `start_config_watcher` / `stop_config_watcher` / `get_config_watcher` / `DEFAULT_NANO_CONFIG_PATH` / `DEFAULT_CONFIG_PATH` / `ConfigReloadCallback` (host-owned at `soothe.config.reload`)
- `paths.thread_paths.THREADS_DATA_DIR` / `PersistenceDirectoryManager` (host-owned at `soothe.sloop.checkpoints.directory_manager`)
- `workspace.workspace_policy.normalize_user_id` / `user_id_for_hash` / `compute_scoped_workspace_dir_name` / `validate_client_workspace` / `translate_client_path_to_container` / `translate_container_path_to_client` (host-owned at `soothe.workspace.scoped` / `.resolution`)
- `backends.persistence.display_store.DisplayCardStore` / `configure_display_card_store` / `get_display_card_store` (moved to daemon `soothe_daemon.display.display_store`)
- `persistence.sql.soothe_checkpoints.init.sql` (host-owned at `soothe.persistence.sql.soothe_checkpoints`); `cron_jobs` + `identity_*` DDL removed from `soothe_metadata/init.sql` (host applies at runtime)
- `utils.progress.set_step_context` / `reset_step_context` / `get_step_id` (dead — zero callers)
- `utils.error_format.log_exception_simplified` (dead — only its own docstring referenced it)

### Changed
- `persistence.unified.configure_unified_persistence` no longer configures the display-card store (daemon calls `configure_display_card_store` directly)
- `persistence.postgres_pool_registry.open_all` no longer opens a checkpoints pool (host-owned; standalone nano uses `SharedCheckpointerPool` + `AsyncPostgresSaver.setup()`)

## [0.9.5] - 2026-07-21

### Fixed
- Align `WorkspaceAwareBackend` / `NormalizedPathBackend` `edit` with deepagents positional protocol so `edit_file` applies
- Honor `replace_all` through LocalFilesystem → workspace backends (was always forced off)
- Align `grep` / `agrep` with BackendProtocol so middleware `content` mode returns line text; keep `output_mode` keyword-only
- Implement `download_files` / `upload_files` on workspace backends (no longer raise `NotImplementedError`)

## [0.9.4] - 2026-07-21

### Fixed
- Release gate: deepagents dependency floor assertion accepts `>=0.8.x`

## [0.9.3] - 2026-07-21

### Changed
- Adapt workspace filesystem and toolkits to `soothe-deepagents` 0.8.0 (`DeleteResult`, no `ls_info` / backend factories)
- Require `soothe-deepagents>=0.8.0`
- `WorkspaceAwareBackend` no longer implements `__call__` (avoids false factory deprecation warnings)

## [0.9.2] - 2026-07-20

### Added
- Declare `browser-use` as a first-party nano dependency (owned by the browser subagent)

### Removed
- Unused `asyncpg` pin (Postgres paths use `psycopg`)

## [0.9.1] - 2026-07-20

### Added
- Structured LLM invoke retries once with a schema-repair hint when strict JSON Schema validation fails
- Integration test helpers in `tests/conftest.py` for base config loading and API-key gating

### Changed
- Filesystem types and locks come from `soothe-deepagents` directly (no nano protocol re-export shims)
- `LocalFilesystem` write/edit/delete/batch/grep delegate to `FilesystemBackend`
- Skill catalog, index, and builtins discovery use deepagents public skill parse/list APIs
- Require `soothe-deepagents>=0.7.24`

### Removed
- `soothe_nano.filesystem.protocol` and `soothe_nano.filesystem._lock_registry` shim modules
- Parallel `ag`-based grep subprocess stack (search uses deepagents ripgrep + Python fallback)

## [0.9.0] - 2026-07-20

### Added
- Initial public soothe-nano packaging on PyPI as a batteries-included Coding CoreAgent

