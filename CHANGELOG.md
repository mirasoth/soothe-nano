# Changelog

All notable changes to soothe-nano are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- `paths.thread_paths.THREADS_DATA_DIR` / `PersistenceDirectoryManager` (host-owned at `soothe.foundation.sloop.state.persistence.directory_manager`)
- `workspace.workspace_policy.normalize_user_id` / `user_id_for_hash` / `compute_scoped_workspace_dir_name` / `validate_client_workspace` / `translate_client_path_to_container` / `translate_container_path_to_client` (host-owned at `soothe.foundation.workspace.scoped` / `.resolution`)
- `backends.persistence.display_store.DisplayCardStore` / `configure_display_card_store` / `get_display_card_store` (moved to daemon `soothe_daemon.display.display_store`)
- `persistence.sql.soothe_checkpoints.init.sql` (host-owned at `soothe.foundation.persistence.sql.soothe_checkpoints`); `cron_jobs` + `identity_*` DDL removed from `soothe_metadata/init.sql` (host applies at runtime)
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

