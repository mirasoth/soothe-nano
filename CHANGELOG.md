# Changelog

All notable changes to soothe-nano are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

