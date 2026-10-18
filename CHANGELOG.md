# Changelog

All notable changes to soothe-nano are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- ArcBox sandbox backend (phase 1 of `docs/arcbox-backend.md`): `ArcBoxBackend` runs command execution and file ops inside an ArcBox Linux microVM while the agent loop and credentials stay on the host. Ships as a core dependency (`arcbox>=0.1.0`); the SDK is lazy-imported and `arcbox.Connection`-less fake clients are injectable for tests. Usage guide: `docs/arcbox-backend.md`.
  - Shell tools keep their names/schemas but route through an injected `CommandExecutor`; host mode is unchanged. New `tests/unit/wire/` coverage for the wire contracts.
  - Sandbox hardening round 2 (RFC gaps A–F): composite routes now also cover `/large_tool_results` and `/conversation_history` (upstream middleware resolves them absolute under an execution backend — without the route, framework state landed in the guest and died with the VM); fail-closed tool-placement gate — custom/MCP/plugin tools without a declared placement now raise by default (`config.sandbox.placement_overrides` whitelist, `sandbox.on_deny: "raise"|"drop"`); guest background jobs spawn via `setsid` and `kill_process` reaps the whole process group (`kill -- -PGID`, falling back to single-PID kill without setsid); bridge-deadline timeouts no longer claim the command was killed (no 124, explicit "may still be running" caveat — only the SDK's server-side timeout maps to the 124 convention); the planner subagent is disabled with a warning in sandbox mode (its host-bound read-only backend cannot see the guest workspace); all four interaction modes × sandbox have builder-level test coverage.
  - Sandbox hardening round 3 (offline batch): `ArcBoxBackend` raises a friendly `ImportError` when `soothe-deepagents` lacks `BaseSandbox` (version floor `<0.8.6`) and a core-dependency hint when the arcbox SDK is missing; `tail_background_log` reads guest logs via guest `tail -n` (single bounded round-trip) instead of `backend.read()`; documented deviations in the RFC (§7.1 tail/retention/offload-opt-in, §8.3 main-dependency decision, §9.1 daemon-credential clarification) and a phase-2 candidate section for the `file_ops`/middleware unification (§16). New invariant tests: middleware timeout cap ≥ backend default, constructor surface holds no model credentials, FS tools and shell share the guest workspace bidirectionally, concurrent writes smoke, backend error paths never touch host subprocesses, and builder-level tests for GP per-step/readonly variants × sandbox (permission-free), behavioral composite routing, and `execute` created-then-hidden filtering.
  - Sandbox E2E round (design §12): 15-test live-daemon suite in `tests/integration/test_arcbox_e2e.py` (opt-in via `--run-integration`; clean skip without a daemon; template selectable via `ARCBOX_E2E_TEMPLATE`). Default template `soothe-nano-e2e` is a production guest image built from `python:3.12-slim-bookworm` + setsid/procps/coreutils — the daemon default template lacks python3 and the flowjet-arcbox draft template's python3 is a broken wrapper with circular symlinks (build bugs recorded in `docs/arcbox-backend.md` §12). Coverage: image prerequisites, execute semantics (124 timeout convention), FS/shell workspace sharing, glob/grep/edit/delete round-trip, capture offload with preserved exit code, no sandbox leaks, stopped-sandbox error-as-data, credential-free guest env, agent-build acceptance.
  - Sandbox placement model (design §7, completes the phase-1 deferred item): new `sandbox/placement.py` assigns every tool a placement under a sandbox backend — `protocol` (FS primitives via the middleware), `guest` (shell group via `execute()`), `shuttle` (byte-transfer adapter: guest path args download to a host temp dir, the original implementation runs, `file_write` outcomes upload back, leaked temp paths are remapped, `sandbox.max_shuttle_bytes` caps transfers at 32 MiB by default), `host`, or `deny` (fail-closed; raises or drops per `sandbox.on_deny`). Resolution order: `sandbox.placement_overrides` (now a `dict[name, placement]`, replacing the flat host allowlist set) > explicit declaration via the new `@tool(placement=...)` parameter / `ToolMeta.placement` field > category/outcome_type default table > registry miss → deny. The builder's name-allowlist gate is replaced by `_finalize_tool_placements`, which produces a `ToolPlacementReport` (available as `builder.placement_report`) covering every tool.

### Removed
- Retired the `file_ops` toolkit group (design §9, phase 2): the middleware filesystem surface is now the single source of file tools in every mode — `FILESYSTEM_TOOLS_AGENT` absorbs the surgical family (`file_info`, `edit_lines`, `insert_lines`, `delete_lines`, `apply_diff`), the group is gone from resolver registration and the plugin registry, and `tools.file_ops.enabled=False` now gates the surgical family directly on the middleware allowlist (`delete` stays — base mutating surface, matching pre-unification behavior). `toolkits/file_ops.py` is deleted; `build_filesystem_tools` moved to `toolkits/filesystem_tools.py` and the surgical name constants to `agent/interaction_mode.py`. Subagents keep the surgical tools via their own FS middleware (same allowlist). Behavior equivalence covered by the existing unit suite and the live E2E suite.
- Deleted the `academic_research` subagent entirely (module tree, resolver factory registration, builtin plugin discovery entry, default config entry, tool metadata, and its tests) — no compat shim; use `deep_research` for all web/academic research.
- Deleted dead modules with zero consumers: `core.types` (unused `VerbosityLevel` export) and `agent.factory` (`soothe_nano.create_nano_agent` now imports from `agent.builder` directly; public name unchanged).
- Inlined single-consumer helper modules: `utils.thread_id` into `backends.durability.base`, and `utils.url_validation.validate_url` into `toolkits._internal.wizsearch`.
- Deleted the `soothe_nano.toolkits.file_ops_catalog` module — its catalog constants and filesystem-tool builders moved into `soothe_nano.toolkits.file_ops` (hard move, no shim).
- Deleted the `data` and `image` toolkits (host-path-bound file-inspection tools duplicating `read_file` + `run_python`), including their config groups, plugin registrations, registry entries, and prompt guide listings.
- Resolver dead code: unused `_resolve_postgres_checkpointer`/`_mask_dsn` (superseded by the shared checkpointer pool), `clear_tool_cache`/`get_cache_stats` (no callers in any repo), the fake parallel subagent branch, the never-supplied `LazySubagentRunnable(materialize=...)` parameter, and the unused dict-like methods on `SUBAGENT_FACTORIES` (`__getitem__`/`keys`/`items`/`__len__`).
- Removed the legacy `tools.file_ops` config field and the corresponding builder gating of the surgical FS allowlist — the middleware FS surface is the single source of file tools; the removed constants (`SURGICAL_FILE_OP_TOOL_NAMES`/`_SET`) had no remaining consumers.
- Removed dead prompt-module exports (zero consumers, verified by import-graph sweep): `build_shared_environment_workspace_prefix` and `RFC104_CONTEXT_XML_VERSION` (`context_xml.py`), the `load_workspace_project_instructions` alias (`project_instructions.py`), and the `soothe_nano.config` re-exports of the underscore prompt template globals.

### Changed
- The planner subagent now works in sandbox mode (design §6): `resolve_subagents` threads the composite sandbox backend through the subagent context, and the planner's readonly recon tools bind to it with the guest workspace root — previously the planner was disabled entirely in sandbox mode because its host-bound `FilesystemBackend` could not see the guest workspace. Host mode is unchanged.
- Removed the `soothe_nano.resolve` package: the full resolution API (protocols, durability/checkpointer, tools, subagents, lazy compilation) now lives in `soothe_nano.utils.resolver` (single module, was 6 files); the shared checkpointer pool moved to `soothe_nano.persistence.shared_checkpointer_pool` next to `shared_metadata_pool`. Hard moves, no shims — hosts import from the new paths.
- Folded the now-`deep_research`-only research helper modules into the `deep_research` package: `_research_json_util` merged into `deep_research.json_util` (was a pure re-export), `_research_timeouts` → `deep_research.timeouts`, `_research_topic_util` → `deep_research.topic_util`, `research_wire` → `deep_research.wire` (hard moves, no shims). Their unit tests moved to `tests/unit/subagents/deep_research/`.
- `soothe_nano.utils.resolver` is the full public host-resolution API: `resolve_checkpointer` and `resolve_durability` are exported so hosts bind their own pools via public imports.
- Consolidated `soothe_nano.middleware` tool-* modules (9 → 5 files), zero behavior change; import `ToolCallArgsMiddleware` / `ToolResultStorageMiddleware` / `ToolResultEvictionMiddleware` from their new modules.
- Renamed the `execution` tool group to `shell` (module, plugin, config key `tools.shell`, `ToolMeta.category`); tool names are unchanged.
- Renamed `soothe_nano.ux` to `soothe_nano.wire` — it holds wire-format contracts, not UX logic. Hard rename, no compat shim.
- Moved `soothe_nano.intention.models` to `soothe_nano.protocols.routing` (flat module; the single-file `intention/` subpackage had no nano runtime consumer — the routing models are host↔nano graph-state contracts, so they now sit next to `protocols.planner`). Hard move, no compat shim.
- Moved the four duck-typed config protocols (`WebSocketConfigProtocol` / `DaemonTransportConfigProtocol` / `DaemonConfigProtocol` / `CliConfigProtocol`) from `soothe_nano.paths` to `soothe_nano.protocols.daemon_config` (re-exported from `soothe_nano.protocols`). They are config contracts, not path constants; `soothe_nano.paths` now holds only path constants and resolvers. Hard move, no compat shim.
- The `soothe_nano.workspace` package's module-level functions are now class-based APIs (hard rename, no compat shim): `WorkspaceResolver` (`workspace_policy.py`) owns the resolution chains — `resolve_stream` / `resolve_tool_execution` / `resolve` (precedence-dispatched, absorbing the previously dead `resolve_workspace` + `WorkspacePrecedence` dispatch from `workspace_api.py`) / `effective_tool_workspace`; `WorkspaceRuntime` (`workspace_runtime.py`) owns the per-task workspace ContextVar (`set` / `get` / `reset` / `virtual_home` / `virtual_mode` / `process_workspace_root`, replacing the `*_workspace_context` / `get_virtual_*` function families); `WorkspacePaths` (`workspace_paths.py`) binds a workspace root + sandbox policy + size cap (`from_config`, `should_use_virtual_path_resolution`, `resolve_os_path`, `join_normalized_path`, `resolve_backup_dir`, replacing the per-call `workspace_root` / `virtual_mode` threading); `WorkspaceBackendRegistry` (`workspace_filesystem.py`) replaces `get_workspace_backend` / `clear_workspace_backend_cache`. `workspace_api.py` is now the types facade (`ResolvedWorkspace` / `WorkspacePrecedence`); the exported names `get_virtual_home` / `get_virtual_mode` / `set_virtual_mode_context` / `clear_virtual_mode_context` / `get_workspace_context` / `resolve_workspace_for_stream` / `resolve_workspace_for_tool_execution` are gone.
- The `soothe_nano.skills` package's module-level functions are now class-based APIs (hard rename, no compat shim): `SkillRoots` (`builtins.py`) owns the process-level skill-root registry (`register` / `roots` / `is_builtin_directory` / `builtin_paths`, absorbing `register_builtin_skill_root`, `iter_skill_roots`, `is_builtin_skill_directory`, `get_built_in_skills_paths`); `SkillCatalog` + `SlashSkillLine` (`catalog.py`) bind config + workspace (`resolve_skill` / `read_markdown` / `build_context_text` / `build_invocation_envelope` / `try_expand_slash_line` / `wire_entries`, plus the `/skill:` wire-line `parse` / `format` statics and the public `parse_skill_directory`); `WorkspaceSkillMirror` (`workspace_sync.py`) binds config + workspace for external-skill mirroring (`mirror_root` / `directories_for_resolution` / `is_under_workspace` / `sync_skill` / `collect_external` / `sync_all` / `sync_specific`); `SkillSearcher` (`search.py`) binds a `ProgressiveSkillRegistry` (`prefetch_core_from_corpus` / `prefetch_from_goal` — merging the pure-forwarding `prefetch_deferred_skills` alias — / `search` / `merge_search_results` / `latest_human_text`) and drops the dead `config` / `catalog_by_name` parameters left over from the Skillify semantic-search handover; `ProgressiveSkillRegistry` absorbs `resolve_core_skill_names` → `resolve_core_names` and `is_core_skill` → `is_core` (the LangGraph reducer `merge_skill_activation` stays module-level); `CorpusMatcher` (`corpus_match.py`) absorbs `earliest_corpus_match` / `match_variants_for_token`; `SkillListingBudget` (`budget.py`) absorbs `format_skills_within_budget`. Dead code removed: `index._make_wire_entry` (duplicated by `SkillIndex.wire_entries`). The langchain tool factories in `discovery_tools.py` intentionally stay as module-level functions.
- The `soothe_nano.prompts` package's functional modules are now class-based APIs (hard rename, no compat shim): `ContextXml` (`context_xml.py`) owns the nested-XML section builders (`build_environment` / `build_workspace` / `build_thread` / `build_protocols` / `build_complexity_sections`, replacing `build_soothe_*_section` and `build_context_sections_for_complexity`); `PromptIdentity` (`identity.py`) owns the identity block surface (`normalize_name` / `identity_block` / `prepend_identity`, replacing `normalize_assistant_name` / `build_assistant_identity_block` / `prepend_assistant_identity`) and reads `ASSISTANT_IDENTITY_FRAGMENT` lazily at call time so host persona patches reach the hot path; `ProjectInstructions` (`project_instructions.py`) owns the AGENTS.md/CLAUDE.md loader (`load` / `build_block_cached` / `read_file_head_lines`, replacing `load_agent_instructions`; the `load_workspace_project_instructions` alias is gone); `SystemTemplates` (`system_templates.py`) owns the system prompt templates and volatile tail (`format_complex_core` / `build_response_language_hint` / `timestamp_iso` / `timestamp_xml_footer` / `default_body` / `uses_builtin`, replacing `format_complex_agent_system_prompt_core` etc.) with the template constants (`DEFAULT_SYSTEM_PROMPT` / `MEDIUM_SYSTEM_PROMPT` / `SIMPLE_SYSTEM_PROMPT` / `TOOL_ORCHESTRATION_GUIDE` / `EXECUTE_WORKSPACE_RULES_FRAGMENT` / `RESPONSE_LANGUAGE_HINT_FALLBACK` / `SKILL_CONTEXT_ACTIVE_GUIDE`) as class attributes replacing the underscore module globals. `soothe_nano.prompts` is now a class facade; `soothe_nano.config` no longer re-exports the old prompt constants (zero consumers).
- The `soothe_nano.persistence` package's functional modules are now class-based APIs (hard rename, no compat shim): `PostgresPoolLifecycle` (`postgres_pool_lifecycle.py`) owns the psycopg pool helpers (`timing_from_config` / `apply_row_factory` / `ensure_open` / `release_idle` / `close`, replacing `postgres_pool_timing_from_config` / `ensure_async_pool_open` / `release_idle_pool_connections` / `close_async_pool`); `PostgresProvisioning` (`postgres_provisioning.py`) owns database auto-provisioning with the process cache and lock as class attributes (`ensure_databases` / `ensure_databases_async` / `admin_dsn` / `target_dsn` / `uses_postgresql` / `required_database_keys` / `validate_database_name` / `reset_cache_for_tests`, replacing `ensure_postgres_databases(_async)` / `postgres_admin_dsn` / `postgres_target_dsn` / `uses_postgresql_persistence` / `required_postgres_database_keys` / `reset_provision_cache_for_tests`; the private `_initialize_postgres_schemas` hook is now `PostgresProvisioning._initialize_schemas` — patch targets follow); `ConnectionRetry` (`retry_utils.py`) owns the retry helpers (`is_duplicate_schema_error` / `is_recoverable_connection_error` / `run_with_retry`, replacing `run_with_connection_retry`); `DatabaseInit` (`db_init/runner.py`) owns the init/migration runner (`initialize` / `initialize_sync` / `run_init(_sync)` / `run_migrations(_sync)` / `load_init_script` / `init_script_path` / `discover_scripts` / `split_statements` / `sql_root`, replacing `initialize_database(_sync)` / `run_database_init(_sync)` / `run_database_migrations(_sync)` / `discover_versioned_scripts` / `split_sql_statements` / `database_sql_root`); the `MigrationScript` / `DatabaseSchemaResult` dataclasses and the `DbKey` literal stay module-level types, and `db_init/__init__.py` is now the class + types facade. The already-class-based modules (`SqliteRuntimeRegistry` / `PostgresPoolRegistry` / `SharedCheckpointerPool` / `SharedMetadataPool`) keep their structure and only re-point their lifecycle/retry imports at the new classes.

### Fixed
- System-prompt guides now reference real bound tool names: `wizsearch_search`/`wizsearch_crawl` instead of the legacy deepagents aliases `search_web`/`crawl_web` (aliases exist only in the permission-layer registry — the model was steered to names never bound); the data guide directs tabular/document work to `read_file` + `run_python` + `file_info` instead of the deleted tools; `run_python` persistence claims hedge the sandbox one-shot mode. Tool-trigger registry keys renamed to match.
- Coalescing middlewares no longer impose a fixed 50 ms latency floor on lone calls: `ReadCoalescingMiddleware`, `ToolOptimizationMiddleware` (grep/glob batch window), and `EditCoalescingMiddleware` fast-flush after one event-loop tick when no sibling call has joined the window; batched calls still wait the full detection window. `read_coalescing`/`tool_optimization` futures now use `asyncio.get_running_loop()` instead of the deprecated `get_event_loop()`.
- `RoleRoutingMiddleware` no longer rescans the full message history for its debug log on every hop (the hop index is only computed when debug logging is enabled).
- Eviction dead branch removed in `ToolResultEvictionMiddleware` (`NON_EVICTABLE_TOOLS` re-check is subsumed by the `EVICTABLE_TOOLS` membership test) and the never-called `_time_since_last_assistant` placeholder deleted.
- Coalescing middlewares (`ReadCoalescingMiddleware` / `ToolOptimizationMiddleware` / `EditCoalescingMiddleware`) key their pending queues, staging buffers, and detection windows by request scope (`thread_id:checkpoint_ns`, shared helper `middleware._scope.request_scope_id`) — concurrent graph threads on one compiled graph no longer co-mingle reads/searches/edits or head-of-line block each other. `WorkspaceContextMiddleware` stores its reset token in a task-local `ContextVar` instead of instance state, so interleaved turns no longer clobber each other's workspace context.
- `SystemPromptMiddleware` per-hop dedup: recent tool calls extracted once (was 3×) and trigger sections derived once for the memory/protocol/tool-context blocks; the workspace resolution chain is skipped when `modify_request` already resolved the workspace into state. `ToolResultEvictionMiddleware` measures token estimates and collects evictable candidates in a single pass (was two full scans); `ToolResultStorageMiddleware` persists oversized outputs via `asyncio.to_thread` (`amaybe_persist_tool_result`) so large writes never block the event loop.
- Batched edit dispatch is no longer an unprotected fast path: `EditCoalescingConfig.batch_dispatch_timeout_seconds` (default 60s, matching the tool-timeout middleware default) caps each file's batched write — lone pass-through edits are excluded (their handler chain already runs through the inner tool-timeout middleware with per-tool overrides). Any timed-out or failed batch resolves every pending future with an error ToolMessage instead of hanging the caller, and one file's dispatch failure no longer hangs the remaining files in the same window. `SoothePolicyMiddleware` memoizes workspace `Path.resolve()` per raw configurable string (bounded at 128 entries).
- Shared detection-window infrastructure: `middleware._window` (`ScopeWindowBank` + `resolve_pending_results`) is now the single implementation of the enqueue/fast-flush/take cycle and the singleton-vs-gather execution + future resolution used by `ReadCoalescingMiddleware` and `ToolOptimizationMiddleware` (edit coalescing keeps its staging-aware flow). `ProgressiveListingMiddleware` reuses the stack-builder's `SkillIndex`/`ProgressiveSkillRegistry` (skills scanned once per staleness window, not once per middleware) and builds its config-derived tool-listing registry once instead of per hop.

## [1.4.2] - 2026-10-13

### Removed
- Dead code cleanup (verified by an AST import-graph sweep): `soothe_nano.utils.llm` back-compat shim, unreferenced DashScope embedding modules, MemU per-category config modules, `filesystem.langchain_adapter` / `filesystem.factory` (superseded by the soothe-deepagents backend layer), and various unused helpers.
- Dropped the `aiohttp`, `firecrawl-anydoc`, `dashscope`, and `httpx` runtime dependencies (unused).

### Changed
- `make examples` now also runs `example-06` (computer-use subagent) and `example-07` (computer-use WeChat Favorites harvest).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.4.1...v1.4.2

## [1.4.1] - 2026-10-13

### Fixed
- `soothe_nano.ux.stream_tool_wire` lazily imported `soothe_nano.ux.task_namespace`, which was not shipped — `ux/task_namespace.py` now ships in this package.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.4.0...v1.4.1

## [1.4.0] - 2026-10-13

### Added
- Absorb the shared-contract layer formerly shipped as the separate `soothe-sdk` package: the plugin decorator API (`soothe_nano.plugin`), event contracts (`soothe_nano.core`), protocols, paths, tool metadata (`soothe_nano.tools`), Langfuse helpers (`soothe_nano.observability.langfuse`), intent routing (`soothe_nano.intention`), wire constants (`soothe_nano.ux.stream_tool_wire`), and core utils.

### Changed
- Drop the `soothe-sdk` dependency — soothe-nano is now self-contained (only first-party runtime dep: `soothe-deepagents`).
- **Plugin authors**: migrate `soothe_sdk.*` imports to their `soothe_nano.*` equivalents; `soothe-sdk` is deprecated as a separate package.
- Host consumers (soothe / soothe-daemon): plan the migration to `soothe_nano.core.events` / `soothe_nano.core.registry` in the same deploy window.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.3.3...v1.4.0

## [1.3.3] - 2026-10-12

### Fixed
- `SootheConfig.secret_resolver` was missing, leaving the MCP registry empty and the agent with zero tools; the property now returns the shared `_resolve_env` helper.
- `fetch_tools_and_descriptors` is now async and awaits `client.get_tools(...)` (`langchain-mcp-adapters` 0.3.x); previously the coroutine was never awaited and zero tools loaded.

### Changed
- Widened `langchain-mcp-adapters` pin from `<0.3.1` to `<0.4.0` (0.3.0 caused the async `get_tools` regression above) and bumped the langchain ecosystem to latest stable: `langchain` 1.4.4, `langchain-core` 1.6.9, `langchain-openai` 1.7.0, `langchain-community` 0.4.2, `langgraph` 1.2.14, `mcp` 1.30.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.3.2...v1.3.3

## [1.3.2] - 2026-10-11

### Fixed
- Fix `run_python` REPL corrupting `sys.stderr` when user code redirects it (e.g. to capture pytest output) and the tool times out: the in-process REPL now saves/restores both `sys.stdout` and `sys.stderr` in its `finally` block, preventing a closed-file `ValueError` from cascading into step failures via `SkillActivationMiddleware` logging.
- Make `SkillIndex._parse_skill_dir` resilient to exceptions from `parse_skill_metadata` (including logging-infrastructure failures): malformed skills now produce a debug log and are skipped instead of crashing the calling step.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.3.1...v1.3.2

## [1.3.1] - 2026-09-23

### Added
- Add `PersistentRetryRunner` middleware wrapper that retries 429/529/transient-connection errors with exponential backoff (capped at 5 min/attempt, 6 hr total), yielding heartbeat events during backoff sleeps so the daemon sees periodic activity.
- Add `QuerySource` enum and query-source discrimination: background sources (compact, summary) bail immediately on 529 capacity errors instead of amplifying gateway load.
- Add model fallback on repeated capacity errors: after a configurable threshold of consecutive 529/overloaded errors, switch to a fallback model resolved via `fallback_model_role` (router role like `"fast"`) or `fallback_model` (raw spec string).
- Add stale-connection recovery: detect `ECONNRESET`/`EPIPE`/`ConnectionResetError`/`BrokenPipeError`, disable HTTP keep-alive, and retry with a fresh connection.
- Add `ModelFallbackEvent` and `LLMPersistentRetryEvent` protocol events emitted via `stream_writer` during persistent retry cycles.

### Changed
- Lower classifier `min_confidence` default from 0.75 to 0.6 to reduce false escalations on ambiguous tool-approval verdicts.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.3.0...v1.3.1

## [1.3.0] - 2026-09-21

### Changed
- Flatten `embedding_profile` from a list to a single `EmbeddingProfile` scalar on `SootheConfig`: YAML configs that passed a one-element list must now pass the profile object directly. The `_apply_embedding_profile` validator reads the scalar instead of indexing `[0]`.
- Remove `ClassifierConfig.shadow` field and its docstring entry — verdicts always apply now; calibration-only recording is gone.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.31...v1.3.0

## [1.2.31] - 2026-09-21

### Changed
- Merge classifier backends into `providers`: a backend is any entry with `provider_type: typesafe`. The standalone `classifier_providers` list is removed, so `classifier.provider` now names a `providers` entry.
- Set classifier defaults to `min_confidence: 0.75` and a 5-second provider timeout.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.30...v1.2.31

## [1.2.30] - 2026-09-21

### Added
- Add `classifier` config block (`enabled`, `provider`, `min_confidence`, `min_margin`, `suppress_min_confidence`, `strict`) plus a `classifier_providers` list, so a swappable calibrated-probability backend is configured once for nano and hosts.
- Add `classifier.suppress_min_confidence` (default 0.9): suppression verdicts need higher confidence than the fail-safe direction.
- Add `SootheConfig.classifier_provider_kwargs()` resolving the configured provider into transport kwargs.

### Fixed
- Gate classifier verdicts on `Choice` answers (binary `Noul` answers carry no confidence).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.29...v1.2.30

## [1.2.29] - 2026-09-19

### Added
- **Tool call efficiency suite.** Parallel-call batching instruction in the system prompt; cross-step tool-result eviction (`ToolResultEvictionMiddleware`); multi-file read coalescing and search consolidation in `ToolOptimizationMiddleware`; large tool outputs (>10K chars) persisted to disk with a compact reference (`ToolResultStorageMiddleware`).

### Changed
- **Core tool set reduced 26 → 20** (`file_info`, `apply_diff`, `delete`, `tail_background_log`, `kill_process`, `current_datetime` moved to deferred loading).
- Updated the tool orchestration prompt guide with batching and large-result re-fetch guidance.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.28...v1.2.29

## [1.2.28] - 2026-09-15

### Fixed
- **Thinking-only streams now trigger failover in `MultiModelChatModel`.** When thinking tokens are stripped and nothing remains, the empty stream fails over like any other failure (sync and async paths) and counts toward the circuit breaker.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.27...v1.2.28

### Added
- `DEFAULT_IDENTICAL_TOOL_CALL_THRESHOLD=3` exposed so hosts can import the Act-stream circuit-breaker threshold (stops degenerate same-tool repeat loops).

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.26...v1.2.27

## [1.2.26] - 2026-09-12

### Fixed
- **`git rm` no longer blocked as a destructive `rm`** (negative lookbehind for `git `); standalone `rm -rf` variants remain blocked.
- **Tool security gate honors loop-scoped human approvals** — a command approved via the `tool_approval` pipeline is no longer re-denied by `run_command`'s own security gate.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.25...v1.2.26

## [1.2.25] - 2026-09-08

### Fixed
- **Empty 200-OK responses now trigger failover in `MultiModelChatModel`** (no text, no tool calls) across all four generation paths, and count toward the circuit breaker.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.24...v1.2.25

## [1.2.24] - 2026-09-07

### Added
- `dangerous_command_rule_id` in `security_api` and `rule_family()` in `operation_guard` — approving one rule now suppresses re-interrupt for the whole rule family (e.g. `rm` variants, `dd` writes).

### Changed
- Inter-endpoint failover cooldown in `MultiModelChatModel` (`failover_cooldown_s`, default 3) to pace failover attempts.
- Raised LLM rate-limit defaults: `rpm_limit` 60→120, `concurrent_limit` 2→4, `global_concurrent_limit` 4→10.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.23...v1.2.24

## [1.2.23] - 2026-09-03

### Fixed
- **Per-model circuit breaker in `MultiModelChatModel`.** After N consecutive failures (default 5) a model's circuit opens for 60s; falls back to the full pool if all are open; success resets.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.22...v1.2.23

## [1.2.22] - 2026-09-01

### Changed
- **Simplified docstrings in `tool_error_guard`.** Trimmed verbose module, class, and function docstrings to one-line summaries per the AGENTS.md docstring standard. Removed redundant inline comments. No behavior change.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.21...v1.2.22

## [1.2.21] - 2026-09-01

### Fixed
- **E402 lint failure in `__init__.py`.** The `bootstrap_dotenv()` call before module imports triggered E402 on all subsequent imports, failing CI. Added `__init__.py` to ruff `per-file-ignores` for E402 and removed redundant inline `# noqa: E402` comments.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.20...v1.2.21

## [1.2.20] - 2026-09-01

### Fixed
- **`.env` loaded at import time.** `bootstrap_dotenv()` runs in `__init__.py` before YAML config parsing resolves `${VAR}` placeholders, fixing auth failures in multi-model configs when env keys weren't exported in the shell.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.19...v1.2.20

## [1.2.19] - 2026-09-01

### Fixed
- Silenced litellm's bare-print debug noise via `litellm.suppress_debug_info = True` before any LangChain import; `LiteLLM` added to the suppressed third-party loggers.
- Resolved E402 lint violations in `provider.py` with intentional-ordering `# noqa` annotations.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.18...v1.2.19

## [1.2.18] - 2026-09-01

### Fixed
- `_model_cache_lock` is now an `RLock` — re-entrant acquisition within `LLMFactory` methods, fixing a deadlock under concurrent model creation.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.17...v1.2.18

## [1.2.17] - 2026-09-01

### Added
- **Bypass permissions mode (`interaction_mode="bypass"`)** — per-session mode that skips all security enforcement layers (policy middleware, dangerous paths/commands, approval prompts). Not a config default.

### Changed
- Multi-model router profiles with per-call failover.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.16...v1.2.17

## [1.2.16] - 2026-08-30

### Fixed
- **`kill_process` now coerces string PIDs** via a Pydantic `args_schema`, instead of raising `TypeError` on JSON-string PIDs and aborting the whole step.
- **New `ToolErrorGuardMiddleware` isolates single-tool failures** — exceptions become error `ToolMessage`s so the agent self-recovers instead of the whole step dying.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.15...v1.2.16

## [1.2.15] - 2026-08-29

### Fixed
- `_state_retrieval_config` now strips `__pregel_scratchpad` alongside the other parent checkpoint coordinates, fixing `KeyError: 'checkpoint_ns'` on resume.

## [1.2.14] - 2026-08-28

### Added
- **`ainvoke_structured_traced` now accepts a `methods` parameter** to override the default structured-output method order (function_calling → None → json_schema → json_mode). Forwarded to `invoke_structured_chat`; when `None`, the default order is used.
- **`decompose_task` timeout default (180s)** added to `ToolTimeoutConfig` defaults, giving the internal grounding-critic LLM call enough time for schema-repair retries.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.13...v1.2.14

## [1.2.13] - 2026-08-27

### Fixed
- `WorkspaceToolOperationSecurity` now blocks dangerous paths (`.git/`, `.bashrc`, …) even without a `SecurityConfig`.
- Expanded banned command patterns: bare `rm -rf` / `rm -r` / `sudo` / `chmod 777`, `shred`, `git push --force`.
- `PathValidator` now flags UNC paths and more dangerous components (project, shell, and git config files).

### Changed
- `build_operation_security_request` is now a standalone exported function in `soothe_nano.security.security_api`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.12...v1.2.13

## [1.2.12] - 2026-08-26

### Fixed
- **`lc_to_litellm_messages` drops `tool_calls` with a missing/empty `function.name`.** A corrupt historical tool call previously caused a non-retriable 400 `invalid_request_error` from providers, failing the whole LLM call; malformed entries are now dropped.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.11...v1.2.12

## [1.2.10] - 2026-08-24

### Changed
- **`general_purpose_subagent` is now a mode enum**: `Literal["off", "full", "readonly", "per_step"]` (default `"full"`) replaces the two booleans. `per_step` (new) registers a full variant for agent-mode steps plus a read-only variant for plan/ask steps; the deprecated `general_purpose_subagent_readonly` field is removed.

### Fixed
- Per-step GP variant wiring: the read-only variant is appended to the graph subagents so a host middleware can route plan/ask `task` calls to it without advertising it to the model.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.9...v1.2.10

## [1.2.9] - 2026-08-24

### Added
- **General-purpose readonly subagent**: new `general_purpose_subagent_readonly` flag restricting the GP subagent to read-only filesystem tools with write-deny permissions. Requires `soothe-deepagents>=0.8.6`.

## [1.2.8] - 2026-08-21

### Added
- **New `plan` interaction mode** — read-only like `ask`, but tuned for producing implementation plans. `InteractionMode` is now `Literal["agent", "ask", "plan"]`; `AgentBuilder` applies plan tool allowlists, permissions, an empty subagent allowlist, and a plan system-prompt suffix.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.7...v1.2.8

## [1.2.7] - 2026-08-21

### Fixed
- **`_StructuredOutputRunnable` tolerates a leaked `CallbackManager` in `config['callbacks']`** (not iterable), which previously routed every query through the intake fail-safe.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.6...v1.2.7

## [1.2.6] - 2026-08-21

### Added
- **New builtin skills: drawio, office, pdf, anydoc.** Renamed `builtin_skills/` → `builtin/`; the new skills ship authoring references, OOXML validators, and supporting scripts.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.5...v1.2.6

## [1.2.5] - 2026-08-20

### Fixed
- **Structured-output calls now emit Langfuse generations.** The runnable bypassed LangChain callbacks; it now uses public `invoke`/`ainvoke` with `config=` so token usage is recorded via callbacks.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.4...v1.2.5

## [1.2.4] - 2026-08-20

### Added
- **Unified Langfuse-traced LLM invocation helpers** (`soothe_nano.llm.traced`).
  Adds `ainvoke_traced`, `ainvoke_structured_traced`, and
  `build_traced_invoke_config` as the single entry point for direct LLM
  `ainvoke` calls. Every call gets Langfuse callbacks (when observability is
  enabled), is wrapped in `await_with_llm_call_policy` for rate-limit/timeout/
  retry, and structured-output calls are traced the same way as plain
  `ainvoke`. The helpers are safe to call without a config (unit tests,
  headless runs) — the call still works, just without tracing.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.3...v1.2.4

## [1.2.3] - 2026-08-17

### Fixed
- **`lc_to_litellm_messages` now accepts plain dict messages**, normalizing role aliases and content; fixes `AttributeError` on the structured-output draft path.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.2...v1.2.3

## [1.2.2] - 2026-08-16

### Fixed
- **`_StructuredOutputRunnable` no longer leaks the LangChain `config` into litellm kwargs** (previously failed JSON serialization → `StructuredOutputError` → degraded intake classification); the config is popped before forwarding.
- **Token-usage callback now fires inline for structured-output calls**, so loop token accumulation keeps working for planner/intent calls.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.1...v1.2.2

## [1.2.1] - 2026-08-16

### Fixed
- Disable litellm's remote model-cost-map fetch (`LITELLM_LOCAL_MODEL_COST_MAP=True`) to avoid offline timeouts on import.
- Use `ConfigDict` instead of deprecated `class Config` in `ChatLitellmModel`.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.2.0...v1.2.1

## [1.2.0] - 2026-08-16

### Changed
- **LLM utilities consolidated into a top-level `soothe_nano.llm` package** (`factory`, `registry`, `provider`, `base`, `message`, `tools`, `structured`, `thinking`, `observability`, `invoke_policy`, `response_text`, `schema_wire`, `types`); old `utils/llm` shims removed (thin re-exports kept during migration).
- Provider abstraction is first-class; structured output now drives `json_schema` method routing with validation-retry recovery from empty payloads.
- Subagents, middleware, and toolkits import from the new `soothe_nano.llm` package.

### Added
- `examples/llm/` with eight runnable examples plus a shared `_helpers` module and README.

### Fixed
- Test fixes aligning with the middleware's no-op contract and the validation-retry path.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.19...v1.2.0

## [1.1.19] - 2026-08-14

### Changed
- Removed the Muse-Glimmer-specific adapter — the model-agnostic implementation in `OpenAICompatModelWrapper` already covers every OpenAI-compatible provider.
- `bind_tools` re-wraps the bound model so thinking-token stripping and streaming auto-fallback apply on every tool-bound invocation.

### Fixed
- Lockfile markers for platform-conditional dependencies so `uv sync` resolves cleanly across platforms.

## [1.1.18] - 2026-08-13

### Changed
- **Protocol detection is now content-based, not name-based** — the adapter no-ops when the wire markers are absent, so new models sharing the protocol need no code change.
- **Streaming auto-fallback** for servers ignoring `stream: true` (e.g. vLLM-Metal).
- Provider-level `max_tokens` on `ModelProviderConfig`.
- `bind_tools` re-wraps the bound model so the adapter and auto-fallback apply on every tool-bound invocation.

### Removed
- Name-based `muse_glimmer` detection and flag — superseded by content detection.

## [1.1.17] - 2026-08-13

### Added
- Muse-Glimmer response adapter: strips the self-talk wire protocol, extracts the `to=user` reply, parses six XML tool-call dialects into structured `tool_calls`, and detects the repetition loop.
- Document parsing for Word, PowerPoint, OpenDocument, `.rtf`, `.epub` via `firecrawl-anydoc`; `ExtractTextTool` routes the new formats.

### Changed
- `LLMFactory` injects a default `max_tokens=2048` for Muse-Glimmer models; `OpenAICompatModelWrapper` gains `streaming`/`muse_glimmer` flags with buffered streaming turns; `_parse_document` routes anydoc extensions with PDF/DOCX/TXT fallback.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.16...v1.1.17

## [1.1.16] - 2026-08-13

### Changed
- `LLMFactory` reads a per-provider `streaming` flag (default `True`); the model cache key no longer hard-codes `streaming:`.

### Removed
- The `muse_glimmer` adapter and auto-detection — replaced by disabling streaming at the provider level for servers with broken streaming endpoints.

### Fixed
- `ModelProviderConfig.streaming` field (default `True`) lets a provider opt out of streaming.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.15...v1.1.16

## [1.1.15] - 2026-08-12

### Added
- Muse-Glimmer response adapter (`soothe_nano.utils.llm.muse_glimmer`): strips self-talk, extracts the `to=user` reply, parses XML tool calls into structured `tool_calls`, and buffers streaming turns into one transformed chunk. Wired via a `muse_glimmer` flag auto-triggered for `muse-glimmer` models.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.14...v1.1.15

## [1.1.14] - 2026-08-12

### Fixed
- `computer_use` vision loop: attach the latest screenshot as a multimodal block, auto-capture observations, treat observe-only runs as no-progress, and probe Retina coordinate scale.
- Missing `pyautogui` now raises a step-level error with install guidance instead of aborting the whole run.
- Stop emitting the noisy `soothe.internal.policy.checked` event per check; denials still emit `PolicyDeniedEvent`.

### Changed
- Default `computer_use` `max_steps` raised 10 → 99.
- Example `07` brings WeChat forward via Spotlight and relies on auto-detected coordinate scale.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.13...v1.1.14

## [1.1.13] - 2026-08-12

### Added
- `computer_use` subagent factory functions (`create_computer_use_tools`, `resolve_computer_use_backend`) for direct main-agent desktop-tool binding.
- Foreground session tracking for `run_command` so host cancel can reap the process group.
- Examples `06` (desktop GUI automation) and `07` (WeChat Favorites harvester).

### Changed
- Examples inject the repo `src/` onto `sys.path`; the system prompt advertises the `computer_use` subagent as reachable via `task`.

### Fixed
- Foreground `run_command` registers an in-flight session marker so cancellation drains the child process group.

[Compare with previous version]: https://github.com/mirasoth/soothe-nano/compare/v1.1.12...v1.1.13

## [1.1.12] - 2026-08-11

### Fixed
- `computer_use` subagent: missing import fix + ruff format.
- **Strip inline thinking tokens** (`<think>`, `<thinking>`, `<reasoning>`) from DeepSeek-R1-style output: stateless `strip_thinking` and stateful `ThinkingStreamFilter`, wired through `SootheConfig.hide_thinking_tokens`, the LLM wrapper chain, and `llm_response_text`.

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
- `toolkits.execution` no longer depends on the sunset `langchain-experimental` `ShellTool` / `PythonREPL`; `run_command` and `run_python` are now implemented on `BaseTool` with an in-process REPL.

### Changed
- Unify SQLite durability, vector store, and persistence under a single process-scoped runtime (`sqlite_runtime`); centralize SQLite path resolution in `paths.sqlite_paths`.
- Bump `soothe-sdk>=1.0.6`.

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
- Raise `AgentRuntimeConfig.recursion_limit` default from 200 to 9_999.
- Decouple nano from the host package (import paths, docs, tests now point at `soothe_nano` / `soothe.coreagent`).
- Add host extension points: `PostgresPoolRegistry` template methods, injectable pool classes in `resolve_durability`/`resolve_checkpointer`, and `_REGISTRY_CLS` on `SharedCheckpointerPool`.
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

