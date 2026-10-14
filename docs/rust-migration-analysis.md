# Rust Migration Analysis — soothe-nano

> **Comprehensive per-file analysis of all 333 Python source files in `src/soothe_nano/`,
> categorized by migration feasibility: Rust-migratable / LangChain-dependent / Python-only.
> Includes per-module recommendations, priority ranking, and effort estimates.

**Generated:** 2026-10-14  
**Repository:** soothe-nano v1.4.2  
**Total source files analyzed:** 333 (non-`__init__.py` Python files in `src/soothe_nano/`)  
**Total lines of code:** 82,461  

---

## Executive Summary

| Category | Files | Lines | % of Files | % of LOC |
|---|---:|---:|---:|---:|
| Rust-migratable | 109 | 20,089 | 32.7% | 24.4% |
| LangChain-dependent | 96 | 35,601 | 28.8% | 43.2% |
| Python-only | 128 | 24,450 | 38.4% | 29.7% |
| **Total** | **333** | **82,461** | **100.0%** | **100.0%** |

### Key Findings

1. **109 files (20,089 LOC)** are candidates for Rust migration — pure logic, stdlib-only, or already partially migrated via the `_rust_compat` PyO3 layer.
2. **96 files (35,601 LOC)** are blocked on the LangChain/LangGraph ecosystem. Migration requires either a Rust-native agent runtime or a long-term FFI bridge strategy.
3. **128 files (24,450 LOC)** should remain Python — they depend on Python-ecosystem libraries (psycopg, langfuse, browser-use, pyautogui, pandas, PyMuPDF) or define Pydantic models, exception hierarchies, or Protocol interfaces.
4. **Existing Rust infrastructure:** 14 Cargo crates already exist under `crates/`, and the `_rust_compat.py` PyO3 bridge (1,619 lines) provides 50+ migrated functions with Python fallbacks.
5. **Skills builtin scripts** (55 files, ~14K LOC) are domain-specific tooling scripts that should remain Python — they are user-extensible and rely on Python ecosystem libraries.

### Existing Rust Crates

| Crate | Purpose |
|---|---|
| `soothe-nano-sys` | PyO3 bindings (the `_rust` extension module) |
| `soothe-nano-core` | Event classification, verbosity, priority |
| `soothe-nano-config` | Config constants, env vars, models |
| `soothe-nano-security` | Path/command validation, rate limiting, circuit breaker |
| `soothe-nano-filesystem` | File ops, glob, grep, discovery hints |
| `soothe-nano-persist` | Durability, persist store, SQLite runtime |
| `soothe-nano-protocols` | Protocol definitions (concurrency, durability, identity, etc.) |
| `soothe-nano-utils` | Chrome detection, circuit breaker, formatting, JSON, logging, output, path, prompt clock, task namespace, text preview, thread ID, URL validation |
| `soothe-nano-tokens` | Token counting (tiktoken-rs) |
| `soothe-nano-skills` | Skill budget, corpus matching, discovery |
| `soothe-nano-events` | Wire protocol events |
| `soothe-nano-prompts` | Context XML, environment, identity, project instructions, system templates |
| `soothe-nano-diagnose` | Diagnostic checks (MCP, models, observability, providers, tool deps, vector stores) |
| `soothe-nano-workspace` | Workspace policy, resolution, SQLite paths |

---

## Priority & Effort Legend

### Priority

| Priority | Meaning |
|---|---|
| **P0** | Already partially migrated — complete the Rust port |
| **P1** | High-value, low-risk — pure logic, no external deps, existing crate |
| **P2** | Medium priority — some deps, requires FFI bridge or partial port |
| **P3** | Low priority — blocked on ecosystem migration or domain-specific |

### Effort Estimate

| Effort | Lines (approx) | Description |
|---|---|---|
| **S** | <100 | Small — straightforward port, 1-2 hours |
| **M** | 100-400 | Medium — moderate complexity, 2-4 hours |
| **L** | 400-800 | Large — significant logic, 1-2 days |
| **XL** | >800 | Extra large — complex, multi-day effort |

---

## Per-Module Analysis

### Module Summary

| Module | Files | Lines | Rust-migratable | LangChain-dependent | Python-only |
|---|---:|---:|---:|---:|---:|
| `(root)` | 3 | 1,720 | 2 | 1 | 0 |
| `agent` | 7 | 1,644 | 1 | 5 | 1 |
| `backends` | 26 | 7,471 | 18 | 2 | 6 |
| `config` | 5 | 3,350 | 3 | 2 | 0 |
| `core` | 6 | 808 | 4 | 0 | 2 |
| `diagnose` | 9 | 1,203 | 7 | 2 | 0 |
| `events` | 1 | 178 | 1 | 0 | 0 |
| `filesystem` | 5 | 3,236 | 1 | 3 | 1 |
| `intention` | 1 | 46 | 0 | 0 | 1 |
| `llm` | 15 | 4,423 | 2 | 10 | 3 |
| `logging` | 2 | 285 | 1 | 1 | 0 |
| `mcp` | 9 | 1,727 | 2 | 5 | 2 |
| `middleware` | 25 | 6,868 | 1 | 24 | 0 |
| `observability` | 9 | 1,113 | 0 | 2 | 7 |
| `persistence` | 7 | 1,733 | 1 | 0 | 6 |
| `plugin` | 15 | 2,333 | 7 | 3 | 5 |
| `prompts` | 4 | 713 | 3 | 0 | 1 |
| `protocols` | 10 | 1,742 | 6 | 2 | 2 |
| `resolve` | 5 | 1,368 | 1 | 2 | 2 |
| `security` | 6 | 2,335 | 6 | 0 | 0 |
| `skills` | 75 | 16,143 | 2 | 5 | 68 |
| `subagents` | 42 | 8,286 | 16 | 11 | 15 |
| `toolkits` | 20 | 6,283 | 4 | 12 | 4 |
| `tools` | 1 | 835 | 0 | 1 | 0 |
| `utils` | 18 | 2,362 | 15 | 1 | 2 |
| `ux` | 2 | 643 | 2 | 0 | 0 |
| `workspace` | 5 | 1,292 | 3 | 2 | 0 |
| **Total** | **333** | **82,461** | **109** | **96** | **128** |

---

### Module: `(root)` — 3 files, 1,720 lines

**Module recommendation:** The `_rust_compat.py` file is the PyO3 bridge layer — it stays Python but its logic is already in Rust. `_dotenv.py` and `_upstream_warnings.py` are thin Python wrappers.

**Breakdown:** 2 Rust-migratable, 1 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `_rust_compat.py` | 1619 | Rust | P2 | L | tiktoken | Pure logic suitable for Rust migration. |
| `_dotenv.py` | 69 | Rust | P2 | S | — | Pure logic suitable for Rust migration. |
| `_upstream_warnings.py` | 32 | LC | P3 | S | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |

---

### Module: `agent` — 7 files, 1,644 lines

**Module recommendation:** Agent orchestration is deeply coupled to LangGraph/deepagents. The builder/core_agent/dual_mode/lazy files are LangChain-dependent and blocked on ecosystem migration. Only `subagent_catalog.py` and `factory.py` are Rust-migratable (pure catalog/factory logic).

**Breakdown:** 1 Rust-migratable, 5 LangChain-dependent, 1 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `agent/builder.py` | 541 | LC | P3 | L | asyncio, langchain/deepagents, langgraph-checkpoint | Core agent orchestration. Deeply coupled to LangGraph/deepagents. Requires Rust-native agent runtime or FFI bridge. Defer until LangGraph replacement exists. |
| `agent/core_agent.py` | 379 | LC | P3 | L | langchain/deepagents, langgraph-checkpoint | Core agent orchestration. Deeply coupled to LangGraph/deepagents. Requires Rust-native agent runtime or FFI bridge. Defer until LangGraph replacement exists. |
| `agent/dual_mode.py` | 303 | LC | P3 | L | langchain/deepagents, langgraph-checkpoint | Core agent orchestration. Deeply coupled to LangGraph/deepagents. Requires Rust-native agent runtime or FFI bridge. Defer until LangGraph replacement exists. |
| `agent/interaction_mode.py` | 202 | LC | P3 | M | langchain/deepagents | Core agent orchestration. Deeply coupled to LangGraph/deepagents. Requires Rust-native agent runtime or FFI bridge. Defer until LangGraph replacement exists. |
| `agent/lazy.py` | 195 | LC | P3 | M | langchain/deepagents, langgraph-checkpoint | Core agent orchestration. Deeply coupled to LangGraph/deepagents. Requires Rust-native agent runtime or FFI bridge. Defer until LangGraph replacement exists. |
| `agent/subagent_catalog.py` | 19 | Rust | P2 | S | — | Agent catalog/factory logic. Port simple logic; keep builder/core_agent in Python. |
| `agent/factory.py` | 5 | Py | P2 | S | — | Keep in Python — Python ecosystem dependency or idiomatic Python pattern. |

---

### Module: `backends` — 26 files, 7,471 lines

**Module recommendation:** The `memu` memory subsystem is pure-logic (JSON I/O, clustering, recall) and highly suitable for Rust migration. Vector store and persistence backends depend on Python database drivers (psycopg, sqlite-vec, weaviate) and should stay Python.

**Breakdown:** 18 Rust-migratable, 2 LangChain-dependent, 6 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `backends/memory/memu/memory_store.py` | 654 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/memory/memory_agent.py` | 620 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/memory/actions/link_related_memories.py` | 543 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/memory/actions/update_memory_with_suggestions.py` | 535 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/vector_store/pgvector.py` | 412 | Py | P1 | M | psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `backends/memory/memu/memory/recall_agent.py` | 401 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/vector_store/sqlite_vec.py` | 393 | Py | P1 | M | sqlite-vec | SQLite vector extension. Keep in Python — sqlite-vec Python binding is the integration point. |
| `backends/persistence/postgres_store.py` | 391 | Py | P1 | M | asyncio, psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `backends/memory/memu/memory/actions/base_action.py` | 347 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/memory/actions/add_activity_memory.py` | 325 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/memory/file_manager.py` | 324 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/vector_store/weaviate.py` | 323 | Py | P1 | M | weaviate | Weaviate client. Keep in Python — no Rust client with feature parity. |
| `backends/memory/memu/memory/actions/cluster_memories.py` | 292 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/memory/actions/run_theory_of_mind.py` | 277 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/config/markdown_config.py` | 249 | Py | P1 | M | pyyaml | Keep in Python — Python ecosystem dependency or idiomatic Python pattern. |
| `backends/durability/base.py` | 243 | Rust | P1 | M | — | Backend store logic. Port SQL/connection management to soothe-nano-persist crate. |
| `backends/memory/memu/memory/actions/generate_suggestions.py` | 217 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu_adapter.py` | 174 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `backends/persistence/sqlite_store.py` | 172 | Rust | P1 | M | — | Backend store logic. Port SQL/connection management to soothe-nano-persist crate. |
| `backends/memory/memu/langchain_adapter.py` | 149 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `backends/memory/memu/memory/embeddings.py` | 125 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/memory/memu/models.py` | 105 | Py | P1 | M | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `backends/memory/memu/llm_client.py` | 103 | Rust | P1 | M | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/durability/sqlite.py` | 39 | Rust | P1 | S | — | Backend store logic. Port SQL/connection management to soothe-nano-persist crate. |
| `backends/memory/memu/llm_adapter.py` | 33 | Rust | P1 | S | — | Memory subsystem pure logic (JSON I/O, clustering, recall). Port to Rust crate with serde. LLM calls stay Python. |
| `backends/durability/postgresql.py` | 25 | Rust | P1 | S | — | Backend store logic. Port SQL/connection management to soothe-nano-persist crate. |

---

### Module: `config` — 5 files, 3,350 lines

**Module recommendation:** `constants.py` and `env.py` are already partially migrated. `models.py` (2,025 lines) and `settings.py` (1,144 lines) are Pydantic + langchain settings — keep in Python.

**Breakdown:** 3 Rust-migratable, 2 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `config/models.py` | 2025 | LC | P3 | XL | browser-use, deepxiv-sdk, langchain/deepagents, langfuse, langgraph-checkpoint, psycopg, pydantic, sqlite-vec, tarzi, tavily, weaviate | Config models. Coupled to pydantic-settings + langchain. Port constants; keep settings models in Python. |
| `config/settings.py` | 1144 | LC | P3 | XL | browser-use, deepxiv-sdk, langchain/deepagents, langgraph-checkpoint, pydantic, pyyaml, sqlite-vec, tarzi, weaviate | Config models. Coupled to pydantic-settings + langchain. Port constants; keep settings models in Python. |
| `config/constants.py` | 83 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `config/env.py` | 82 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `config/middleware_access.py` | 16 | Rust | P1 | S | — | Config constants/env. Port to soothe-nano-config crate. Already partially migrated. |

---

### Module: `core` — 6 files, 808 lines

**Module recommendation:** All files already use `_rust_compat`. Complete the Rust port for remaining Python fallback logic. Pydantic models in `events.py` and `registry.py` stay Python.

**Breakdown:** 4 Rust-migratable, 0 LangChain-dependent, 2 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `core/registry.py` | 321 | Rust | P0 | M | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `core/events.py` | 200 | Rust | P0 | M | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `core/subagent_wire.py` | 160 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `core/verbosity.py` | 58 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `core/exceptions.py` | 55 | Py | P1 | S | — | Exception/type definitions. Keep in Python — Python exception hierarchy is idiomatic. |
| `core/types.py` | 14 | Py | P1 | S | — | Exception/type definitions. Keep in Python — Python exception hierarchy is idiomatic. |

---

### Module: `diagnose` — 9 files, 1,203 lines

**Module recommendation:** All files already use `_rust_compat` and have corresponding Rust crate functions. Complete remaining fallback logic. `providers.py` has langchain dependency.

**Breakdown:** 7 Rust-migratable, 2 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `diagnose/providers.py` | 272 | LC | P3 | M | asyncio, langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `diagnose/observability.py` | 196 | Rust | P0 | M | langfuse | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `diagnose/tool_deps.py` | 148 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `diagnose/vector_stores.py` | 141 | Rust | P0 | M | sqlite-vec, weaviate | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `diagnose/mcp.py` | 123 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `diagnose/models.py` | 99 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `diagnose/protocols.py` | 79 | Rust | P0 | S | sqlite-vec, weaviate | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `diagnose/api.py` | 74 | Rust | P2 | S | — | Diagnostic logic. Port to soothe-nano-diagnose crate. Already partially migrated. |
| `diagnose/models_check.py` | 71 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |

---

### Module: `events` — 1 files, 178 lines

**Module recommendation:** `catalog.py` already uses `_rust_compat`. Complete the Rust port in `soothe-nano-events` crate.

**Breakdown:** 1 Rust-migratable, 0 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `events/catalog.py` | 178 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |

---

### Module: `filesystem` — 5 files, 3,236 lines

**Module recommendation:** `local.py` and `workspace.py` depend on deepagents/wcmatch/pathspec. `discovery_hints.py` is already migrated. `unified.py` and `exceptions.py` are pure logic suitable for Rust.

**Breakdown:** 1 Rust-migratable, 3 LangChain-dependent, 1 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `filesystem/local.py` | 1410 | LC | P3 | XL | aiofiles, asyncio, langchain/deepagents, wcmatch | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `filesystem/unified.py` | 852 | LC | P3 | XL | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `filesystem/workspace.py` | 746 | LC | P3 | L | asyncio, langchain/deepagents, pathspec, wcmatch | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `filesystem/exceptions.py` | 145 | Py | P1 | M | — | Exception/type definitions. Keep in Python — Python exception hierarchy is idiomatic. |
| `filesystem/discovery_hints.py` | 83 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |

---

### Module: `intention` — 1 files, 46 lines

**Module recommendation:** Single Pydantic model file. Keep in Python.

**Breakdown:** 0 Rust-migratable, 0 LangChain-dependent, 1 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `intention/models.py` | 46 | Py | P2 | S | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |

---

### Module: `llm` — 15 files, 4,423 lines

**Module recommendation:** The entire LLM provider stack is coupled to langchain-core/litellm. `response_text.py` and `thinking.py` are pure logic and Rust-migratable. All others are LangChain-dependent.

**Breakdown:** 2 Rust-migratable, 10 LangChain-dependent, 3 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `llm/provider.py` | 1075 | LC | P3 | XL | asyncio, langchain/deepagents, litellm, pydantic | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/invoke_policy.py` | 791 | LC | P3 | L | asyncio, langchain/deepagents | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/structured.py` | 392 | LC | P3 | L | jsonschema, langchain/deepagents, pydantic | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/message.py` | 309 | LC | P3 | L | langchain/deepagents, litellm, pydantic | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/traced.py` | 271 | LC | P3 | M | langchain/deepagents, langfuse | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/tools.py` | 267 | LC | P3 | M | langchain/deepagents, litellm | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/registry.py` | 255 | Py | P2 | M | litellm | LiteLLM model registry. Keep in Python — litellm has no Rust equivalent. |
| `llm/observability.py` | 242 | LC | P3 | M | langchain/deepagents | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/base.py` | 207 | LC | P3 | M | langchain/deepagents, litellm | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/thinking.py` | 199 | Rust | P2 | M | — | Pure logic suitable for Rust migration. |
| `llm/factory.py` | 170 | LC | P3 | M | langchain/deepagents, litellm | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |
| `llm/response_text.py` | 110 | Rust | P2 | M | — | Pure logic suitable for Rust migration. |
| `llm/schema_wire.py` | 61 | Py | P2 | S | litellm | LiteLLM model registry. Keep in Python — litellm has no Rust equivalent. |
| `llm/types.py` | 52 | Py | P2 | S | litellm | LiteLLM model registry. Keep in Python — litellm has no Rust equivalent. |
| `llm/exceptions.py` | 22 | LC | P3 | S | langchain/deepagents | LLM provider abstraction. Coupled to langchain-core/litellm. Requires Rust-native LLM client or FFI bridge to litellm. Long-term migration target. |

---

### Module: `logging` — 2 files, 285 lines

**Module recommendation:** `setup.py` depends on langfuse. `context.py` is pure logic and Rust-migratable.

**Breakdown:** 1 Rust-migratable, 1 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `logging/setup.py` | 257 | LC | P3 | M | browser-use, langchain/deepagents, langfuse | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `logging/context.py` | 28 | Rust | P2 | S | — | Logging context logic. Port simple context to Rust. |

---

### Module: `mcp` — 9 files, 1,727 lines

**Module recommendation:** MCP integration is coupled to langchain-mcp-adapters. `mcp_events.py` and `mcp_utils.py` are pure logic. Others are LangChain-dependent.

**Breakdown:** 2 Rust-migratable, 5 LangChain-dependent, 2 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `mcp/mcp_registry.py` | 304 | LC | P3 | L | asyncio, langchain/deepagents | MCP integration. Coupled to langchain-mcp-adapters. Port config validation; keep MCP client in Python. |
| `mcp/mcp_events.py` | 289 | Rust | P2 | M | — | MCP event/utility logic. Port pure logic to Rust; keep MCP protocol handling in Python (mcp library). |
| `mcp/mcp_config.py` | 201 | LC | P3 | M | langchain/deepagents | MCP integration. Coupled to langchain-mcp-adapters. Port config validation; keep MCP client in Python. |
| `mcp/mcp_registry_support.py` | 197 | LC | P3 | M | asyncio, langchain/deepagents | MCP integration. Coupled to langchain-mcp-adapters. Port config validation; keep MCP client in Python. |
| `mcp/mcp_progressive.py` | 168 | LC | P3 | M | langchain/deepagents, pydantic | MCP integration. Coupled to langchain-mcp-adapters. Port config validation; keep MCP client in Python. |
| `mcp/cleanup.py` | 165 | Py | P2 | M | asyncio | Async logic. Keep in Python for now — Rust async (tokio) migration requires runtime bridge. |
| `mcp/mcp_utils.py` | 157 | Rust | P2 | M | — | MCP event/utility logic. Port pure logic to Rust; keep MCP protocol handling in Python (mcp library). |
| `mcp/reconnect.py` | 143 | Py | P2 | M | asyncio | Async logic. Keep in Python for now — Rust async (tokio) migration requires runtime bridge. |
| `mcp/mcp_resource_tools.py` | 103 | LC | P3 | M | langchain/deepagents, pydantic | MCP integration. Coupled to langchain-mcp-adapters. Port config validation; keep MCP client in Python. |

---

### Module: `middleware` — 25 files, 6,868 lines

**Module recommendation:** Middleware pipeline is coupled to LangGraph. Pure-logic middleware (coalescing, context, progressive) is Rust-migratable. LangChain-coupled middleware stays Python.

**Breakdown:** 1 Rust-migratable, 24 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `middleware/edit_coalescing.py` | 900 | LC | P3 | XL | aiofiles, asyncio, langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/system_prompt.py` | 714 | LC | P3 | L | browser-use, langchain/deepagents, langfuse | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_optimization_middleware.py` | 584 | LC | P3 | L | asyncio, langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/model_call_profiler.py` | 582 | LC | P3 | L | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/skill_activation.py` | 483 | LC | P3 | L | asyncio, langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/_builder.py` | 425 | LC | P3 | L | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/filesystem.py` | 306 | LC | P3 | L | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/progressive_listing.py` | 294 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/progressive_tools.py` | 256 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/mcp_activation.py` | 251 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_result_storage.py` | 233 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_result_eviction.py` | 229 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/code_interpreter.py` | 195 | LC | P3 | M | langchain-quickjs, langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/_tool_context.py` | 193 | Rust | P2 | M | — | Middleware logic. Port pure computation; keep LangChain middleware integration in Python. |
| `middleware/tool_result_storage_middleware.py` | 182 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/policy.py` | 162 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/role_routing.py` | 153 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/read_coalescing.py` | 144 | LC | P3 | M | asyncio, langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_enforcement.py` | 138 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/workspace_context.py` | 133 | LC | P3 | M | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_call_args_registry.py` | 75 | LC | P3 | S | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/per_turn_model.py` | 73 | LC | P3 | S | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_error_guard.py` | 70 | LC | P3 | S | asyncio, langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_call_args_middleware.py` | 61 | LC | P3 | S | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |
| `middleware/tool_name_hints.py` | 32 | LC | P3 | S | langchain/deepagents | Middleware pipeline. Coupled to LangGraph middleware API. Port computation; keep middleware registration in Python. |

---

### Module: `observability` — 9 files, 1,113 lines

**Module recommendation:** Langfuse integration. All files depend on langfuse SDK. Keep in Python.

**Breakdown:** 0 Rust-migratable, 2 LangChain-dependent, 7 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `observability/langfuse/callback_handler.py` | 325 | LC | P3 | L | asyncio, langchain/deepagents, langfuse | Langfuse integration. Coupled to langfuse SDK. Port formatting; keep callback handler in Python. |
| `observability/langfuse/_handlers.py` | 161 | LC | P3 | M | langchain/deepagents, langfuse | Langfuse integration. Coupled to langfuse SDK. Port formatting; keep callback handler in Python. |
| `observability/langfuse/_merge.py` | 143 | Py | P2 | M | langfuse | Langfuse SDK integration. Keep in Python — no Rust client with feature parity. |
| `observability/langfuse/tracer.py` | 129 | Py | P2 | M | langfuse | Langfuse SDK integration. Keep in Python — no Rust client with feature parity. |
| `observability/langfuse/_client.py` | 108 | Py | P2 | M | langfuse | Langfuse SDK integration. Keep in Python — no Rust client with feature parity. |
| `observability/langfuse/_trace_io.py` | 107 | Py | P2 | M | langfuse | Langfuse SDK integration. Keep in Python — no Rust client with feature parity. |
| `observability/langfuse/system_hint.py` | 92 | Py | P2 | S | langfuse | Langfuse SDK integration. Keep in Python — no Rust client with feature parity. |
| `observability/langfuse/_types.py` | 32 | Py | P2 | S | langfuse | Langfuse SDK integration. Keep in Python — no Rust client with feature parity. |
| `observability/langfuse/_names.py` | 16 | Py | P2 | S | langfuse | Langfuse SDK integration. Keep in Python — no Rust client with feature parity. |

---

### Module: `persistence` — 7 files, 1,733 lines

**Module recommendation:** `sqlite_runtime.py` is already migrated. PostgreSQL pool/provisioning files depend on psycopg and stay Python.

**Breakdown:** 1 Rust-migratable, 0 LangChain-dependent, 6 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `persistence/db_init/runner.py` | 471 | Py | P1 | M | psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `persistence/sqlite_runtime.py` | 361 | Rust | P0 | M | asyncio | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `persistence/postgres_pool_registry.py` | 243 | Py | P1 | M | asyncio, psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `persistence/postgres_provisioning.py` | 220 | Py | P1 | M | asyncio, langgraph-checkpoint, psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `persistence/retry_utils.py` | 189 | Py | P1 | M | asyncio, psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `persistence/postgres_pool_lifecycle.py` | 134 | Py | P1 | M | psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `persistence/shared_metadata_pool.py` | 115 | Py | P1 | M | psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |

---

### Module: `plugin` — 15 files, 2,333 lines

**Module recommendation:** Plugin registry/lifecycle logic is pure and Rust-migratable. `decorators.py`, `depends.py`, `loader.py` are LangChain-dependent (tool registration).

**Breakdown:** 7 Rust-migratable, 3 LangChain-dependent, 5 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `plugin/lifecycle.py` | 405 | Py | P2 | M | asyncio | Async logic. Keep in Python for now — Rust async (tokio) migration requires runtime bridge. |
| `plugin/decorators.py` | 395 | LC | P3 | L | asyncio, langchain/deepagents | Plugin decorators. Coupled to langchain tool registration. Port registry; keep decorator in Python. |
| `plugin/loader.py` | 314 | LC | P3 | L | langchain/deepagents | Plugin decorators. Coupled to langchain tool registration. Port registry; keep decorator in Python. |
| `plugin/registry.py` | 260 | Rust | P2 | M | — | Plugin registry/lifecycle logic. Port registry mechanics to Rust; keep Python decorator/discovery. |
| `plugin/discovery.py` | 212 | Py | P2 | M | browser-use | Browser automation library. Keep in Python — browser-use has no Rust equivalent. |
| `plugin/context.py` | 158 | Rust | P2 | M | — | Plugin registry/lifecycle logic. Port registry mechanics to Rust; keep Python decorator/discovery. |
| `plugin/events.py` | 103 | Rust | P2 | M | — | Plugin registry/lifecycle logic. Port registry mechanics to Rust; keep Python decorator/discovery. |
| `plugin/exceptions.py` | 97 | Py | P2 | S | — | Exception/type definitions. Keep in Python — Python exception hierarchy is idiomatic. |
| `plugin/emit.py` | 92 | Rust | P2 | S | — | Plugin registry/lifecycle logic. Port registry mechanics to Rust; keep Python decorator/discovery. |
| `plugin/global_registry.py` | 87 | Rust | P2 | S | — | Plugin registry/lifecycle logic. Port registry mechanics to Rust; keep Python decorator/discovery. |
| `plugin/manifest.py` | 62 | Py | P2 | S | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `plugin/depends.py` | 55 | LC | P3 | S | langchain/deepagents | Plugin decorators. Coupled to langchain tool registration. Port registry; keep decorator in Python. |
| `plugin/lazy.py` | 48 | Rust | P2 | S | — | Plugin registry/lifecycle logic. Port registry mechanics to Rust; keep Python decorator/discovery. |
| `plugin/cache.py` | 26 | Rust | P2 | S | — | Plugin registry/lifecycle logic. Port registry mechanics to Rust; keep Python decorator/discovery. |
| `plugin/health.py` | 19 | Py | P2 | S | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |

---

### Module: `prompts` — 4 files, 713 lines

**Module recommendation:** `context_xml.py` and `project_instructions.py` are already migrated. `identity.py` is pure logic. `system_templates.py` depends on browser-use.

**Breakdown:** 3 Rust-migratable, 0 LangChain-dependent, 1 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `prompts/system_templates.py` | 275 | Py | P1 | M | browser-use | Browser automation library. Keep in Python — browser-use has no Rust equivalent. |
| `prompts/project_instructions.py` | 214 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `prompts/context_xml.py` | 174 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `prompts/identity.py` | 50 | Rust | P1 | S | — | Prompt assembly logic. Port to soothe-nano-prompts crate. Already partially migrated. |

---

### Module: `protocols` — 10 files, 1,742 lines

**Module recommendation:** Protocol definitions with Pydantic models. Logic portions already use `_rust_compat`. Pydantic Protocol interfaces stay Python.

**Breakdown:** 6 Rust-migratable, 2 LangChain-dependent, 2 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `protocols/identity.py` | 439 | Rust | P0 | M | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `protocols/planner.py` | 254 | Rust | P0 | M | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `protocols/durability.py` | 211 | Rust | P0 | M | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `protocols/policy.py` | 205 | Rust | P0 | M | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `protocols/core_agent.py` | 181 | LC | P3 | M | langchain/deepagents, langgraph-checkpoint | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `protocols/vector_store.py` | 140 | Py | P1 | M | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `protocols/memory.py` | 109 | Rust | P0 | M | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `protocols/operation_security.py` | 78 | Rust | P0 | S | pydantic | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `protocols/concurrency.py` | 66 | LC | P3 | S | langchain/deepagents, pydantic | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `protocols/persistence.py` | 59 | Py | P1 | S | — | Keep in Python — Python ecosystem dependency or idiomatic Python pattern. |

---

### Module: `resolve` — 5 files, 1,368 lines

**Module recommendation:** Resolver tools are coupled to LangGraph checkpointer. `_lazy_subagent.py` and `_tool_cache.py` have pure logic. `shared_checkpointer_pool.py` stays Python.

**Breakdown:** 1 Rust-migratable, 2 LangChain-dependent, 2 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `resolve/_resolver_tools.py` | 674 | LC | P3 | L | asyncio, browser-use, deepxiv-sdk, langchain/deepagents, tarzi | Resolver tools. Coupled to LangGraph checkpointer. Port caching; keep checkpointer pool in Python. |
| `resolve/_resolver_infra.py` | 246 | Py | P2 | M | langgraph-checkpoint, psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `resolve/shared_checkpointer_pool.py` | 240 | Py | P2 | M | asyncio, langgraph-checkpoint, psycopg | PostgreSQL driver integration. Keep in Python — psycopg3 has no Rust equivalent with feature parity. |
| `resolve/_lazy_subagent.py` | 147 | Rust | P2 | M | — | Resolver logic. Port caching/lazy loading; keep checkpointer integration in Python. |
| `resolve/_tool_cache.py` | 61 | LC | P3 | S | langchain/deepagents | Resolver tools. Coupled to LangGraph checkpointer. Port caching; keep checkpointer pool in Python. |

---

### Module: `security` — 6 files, 2,335 lines

**Module recommendation:** All files already use `_rust_compat` with corresponding `soothe-nano-security` crate. Complete remaining Python fallback logic.

**Breakdown:** 6 Rust-migratable, 0 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `security/path_security.py` | 515 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `security/security_enforcer.py` | 470 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `security/policy_models.py` | 444 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `security/operation_guard.py` | 414 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `security/policy_profiles.py` | 411 | Rust | P1 | M | — | Security-critical path/command validation. Port to soothe-nano-security crate. Reject-only fast paths already exist. |
| `security/security_api.py` | 81 | Rust | P1 | S | — | Security-critical path/command validation. Port to soothe-nano-security crate. Reject-only fast paths already exist. |

---

### Module: `skills` — 75 files, 16,143 lines

**Module recommendation:** Core skill infrastructure (budget, corpus_match, discovery, catalog, registry, search, index) is Rust-migratable. Builtin skill scripts (drawio, office, pdf, mcp-builder, skill-creator) are domain-specific Python tooling and should stay Python.

**Breakdown:** 2 Rust-migratable, 5 LangChain-dependent, 68 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `skills/builtin/office/scripts/office/validators/base.py` | 824 | Py | P2 | L | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/catalog.py` | 547 | LC | P3 | L | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `skills/builtin/drawio/scripts/autolayout.py` | 457 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/office/validators/docx.py` | 444 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/office/validators/pptx.py` | 428 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/comment.py` | 411 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/mcp-builder/scripts/evaluation.py` | 407 | Py | P2 | M | asyncio | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/skill-creator/scripts/init_skill.py` | 383 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/add_slide.py` | 377 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/buildup.py` | 367 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/validate.py` | 356 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/registry.py` | 320 | Py | P2 | M | pathspec | Keep in Python — Python ecosystem dependency or idiomatic Python pattern. |
| `skills/builtin/office/scripts/thumbnail.py` | 306 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/merge_runs.py` | 303 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/clean.py` | 302 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/recalc.py` | 301 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/tfimports.py` | 287 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/office/validators/redlining.py` | 287 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/timelapse.py` | 286 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/k8simports.py` | 270 | Py | P2 | M | pyyaml | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/compress.py` | 269 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/index.py` | 252 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `skills/builtin/drawio/scripts/runbook.py` | 246 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/heatmap.py` | 242 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/workspace_sync.py` | 240 | Py | P2 | M | — | Keep in Python — Python ecosystem dependency or idiomatic Python pattern. |
| `skills/builtin/drawio/scripts/drawiohtml.py` | 238 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/seqlayout.py` | 235 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/aiicons.py` | 234 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/ciimports.py` | 229 | Py | P2 | M | pyyaml | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/prdiff.py` | 221 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/rustimports.py` | 210 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/raster2drawio.py` | 207 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/skill-creator/scripts/quick_validate.py` | 204 | Py | P2 | M | pyyaml | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/c4.py` | 199 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/office/soffice.py` | 190 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/openapiimports.py` | 188 | Py | P2 | M | pyyaml | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/office/helpers/pptx_chart.py` | 188 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/tubemap.py` | 181 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/sqlerd.py` | 179 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/restyle.py` | 178 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/drawiodiff.py` | 176 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/shapesearch.py` | 173 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/office/validate.py` | 172 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/explain.py` | 169 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/dockerimports.py` | 165 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/jsimports.py` | 163 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/pyclasses.py` | 162 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/drawio2mermaid.py` | 160 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/pyimports.py` | 160 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/search.py` | 158 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `skills/builtin/mcp-builder/scripts/connections.py` | 151 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/budget.py` | 150 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `skills/builtin/drawio/scripts/tfstate.py` | 150 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/goimports.py` | 148 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/composeimports.py` | 136 | Py | P2 | M | pyyaml | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/skill-creator/scripts/package_skill.py` | 135 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtins.py` | 135 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `skills/builtin/office/scripts/accept_changes.py` | 131 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/pdf/scripts/extract_form_field_info.py` | 130 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/drawio2pptx.py` | 129 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/pdf/scripts/extract_form_structure.py` | 116 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/relabel.py` | 110 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/office/scripts/office/helpers/pptx_theme.py` | 110 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/pdf/scripts/fill_pdf_form_with_annotations.py` | 108 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/pdf/scripts/fill_fillable_fields.py` | 103 | Py | P2 | M | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/svgflow.py` | 86 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/discovery_tools.py` | 86 | LC | P3 | S | langchain/deepagents, pydantic | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `skills/builtin/pdf/scripts/check_bounding_boxes.py` | 74 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/corpus_match.py` | 64 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `skills/builtin/office/scripts/office/helpers/pptx_slide.py` | 59 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/encode_drawio_url.py` | 58 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/pdf/scripts/create_validation_image.py` | 39 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/drawio/scripts/repair_png.py` | 38 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/pdf/scripts/convert_pdf_to_images.py` | 33 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |
| `skills/builtin/pdf/scripts/check_fillable_fields.py` | 13 | Py | P2 | S | — | Domain-specific skill script. Keep in Python — relies on Python ecosystem libraries (openpyxl, PyMuPDF, etc.) and is user-extensible. |

---

### Module: `subagents` — 42 files, 8,286 lines

**Module recommendation:** Subagent engines are coupled to LangGraph/deepagents. Display/formatting/persistence/termination logic is Rust-migratable. Engine/implementation files are LangChain-dependent.

**Breakdown:** 16 Rust-migratable, 11 LangChain-dependent, 15 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `subagents/computer_use/implementation.py` | 1748 | LC | P3 | XL | asyncio, browser-use, langchain/deepagents, pyautogui, pydantic | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/browser_use/implementation.py` | 832 | LC | P3 | XL | asyncio, browser-use, langchain/deepagents, pydantic | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/plan/engine.py` | 668 | LC | P3 | L | langchain/deepagents, pydantic | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/academic_research/engine.py` | 628 | LC | P3 | L | asyncio, langchain/deepagents | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/deep_research/engine.py` | 626 | LC | P3 | L | asyncio, langchain/deepagents | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/computer_use/tools.py` | 433 | LC | P3 | L | langchain/deepagents, pyautogui, pydantic | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/deep_research/sources/web_search.py` | 279 | LC | P3 | M | langchain/deepagents, tavily | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/academic_research/termination.py` | 181 | Rust | P2 | M | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/deep_research/termination.py` | 181 | Rust | P2 | M | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/academic_research/sources/academic_search.py` | 178 | Py | P2 | M | deepxiv-sdk, tarzi | Keep in Python — Python ecosystem dependency or idiomatic Python pattern. |
| `subagents/deep_research/report_classifier.py` | 170 | LC | P3 | M | langchain/deepagents, pydantic | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/academic_research/report_classifier.py` | 168 | LC | P3 | M | langchain/deepagents, pydantic | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/browser_use/action_format.py` | 122 | Py | P2 | M | browser-use | Browser automation library. Keep in Python — browser-use has no Rust equivalent. |
| `subagents/academic_research/events.py` | 118 | Py | P2 | M | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/deep_research/events.py` | 112 | Py | P2 | M | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/academic_research/effort.py` | 108 | Py | P2 | M | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/deep_research/effort.py` | 108 | Py | P2 | M | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/computer_use/action_format.py` | 104 | Rust | P2 | M | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/academic_research/persistence.py` | 99 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/deep_research/persistence.py` | 99 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/academic_research/protocol.py` | 97 | Py | P2 | S | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/academic_research/display_summary.py` | 93 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/academic_research/references.py` | 92 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/deep_research/display_summary.py` | 92 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/deep_research/protocol.py` | 92 | Py | P2 | S | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/deep_research/references.py` | 92 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/_research_topic_util.py` | 91 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/computer_use/config_model.py` | 84 | Py | P2 | S | pyautogui, pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/browser_use/events.py` | 80 | Py | P2 | S | browser-use, pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/computer_use/events.py` | 80 | Py | P2 | S | pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/academic_research/implementation.py` | 68 | LC | P3 | S | langchain/deepagents | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/deep_research/implementation.py` | 68 | LC | P3 | S | langchain/deepagents | Subagent engines. Coupled to LangGraph/deepagents. Port display/formatting; keep engine orchestration in Python. |
| `subagents/research_wire.py` | 56 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/_research_json_util.py` | 55 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/browser_use/config_model.py` | 50 | Py | P2 | S | browser-use, pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `subagents/_research_timeouts.py` | 32 | Py | P2 | S | tavily | Keep in Python — Python ecosystem dependency or idiomatic Python pattern. |
| `subagents/browser_use/display_summary.py` | 18 | Py | P2 | S | browser-use | Browser automation library. Keep in Python — browser-use has no Rust equivalent. |
| `subagents/computer_use/display_summary.py` | 18 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/academic_research/json_util.py` | 17 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/deep_research/json_util.py` | 17 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/browser_use/_preview.py` | 16 | Rust | P2 | S | — | Subagent display/formatting logic. Port to Rust; keep engine/implementation in Python (LangGraph). |
| `subagents/computer_use/_preview.py` | 16 | Py | P2 | S | browser-use | Browser automation library. Keep in Python — browser-use has no Rust equivalent. |

---

### Module: `toolkits` — 20 files, 6,283 lines

**Module recommendation:** Toolkit logic is mixed. Pure computation (shell_compat, progressive, backend_ops) is Rust-migratable. LangChain @tool wrappers and SDK-dependent tools (deepxiv, wizsearch, url_crawl) stay Python.

**Breakdown:** 4 Rust-migratable, 12 LangChain-dependent, 4 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `toolkits/execution.py` | 1218 | LC | P3 | XL | langchain/deepagents, pydantic | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/deepxiv.py` | 920 | LC | P3 | XL | deepxiv-sdk, langchain/deepagents, pydantic, tarzi | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/_internal/wizsearch.py` | 786 | Py | P2 | M | asyncio, tavily | Async logic. Keep in Python for now — Rust async (tokio) migration requires runtime bridge. |
| `toolkits/data.py` | 496 | LC | P3 | L | langchain/deepagents, pydantic | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/url_crawl/polite_http.py` | 447 | Py | P2 | XL | asyncio, deepxiv-sdk, tarzi, tavily | Async logic. Keep in Python for now — Rust async (tokio) migration requires runtime bridge. |
| `toolkits/_internal/document.py` | 433 | LC | P3 | L | PyMuPDF, langchain/deepagents, requests | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/wizsearch.py` | 403 | LC | P3 | L | langchain/deepagents, pydantic, tavily | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/image.py` | 262 | LC | P3 | M | asyncio, langchain/deepagents, pydantic | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/_internal/backend_ops.py` | 208 | Rust | P2 | M | — | Toolkit logic. Port pure computation to Rust; keep LangChain tool wrappers in Python. |
| `toolkits/progressive/registry.py` | 189 | Rust | P2 | M | — | Toolkit logic. Port pure computation to Rust; keep LangChain tool wrappers in Python. |
| `toolkits/progressive/budget.py` | 174 | Rust | P2 | M | — | Toolkit logic. Port pure computation to Rust; keep LangChain tool wrappers in Python. |
| `toolkits/_internal/tabular.py` | 164 | Py | P2 | M | pandas | Pandas data processing. Keep in Python — pandas has no Rust equivalent. |
| `toolkits/url_crawl/crawler.py` | 118 | Py | P2 | M | asyncio, pydantic | Pydantic model definitions. Keep in Python — Rust serde structs lack Pydantic's validation/serialization contract. |
| `toolkits/http_requests.py` | 98 | LC | P3 | S | langchain/deepagents | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/file_ops_catalog.py` | 89 | LC | P3 | S | langchain/deepagents | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/datetime.py` | 86 | LC | P3 | S | langchain/deepagents | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/file_ops.py` | 82 | LC | P3 | S | langchain/deepagents | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/_internal/local_path_resolution.py` | 43 | LC | P3 | S | langchain/deepagents | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/progressive/search_tool.py` | 34 | LC | P3 | S | langchain/deepagents, pydantic | LangChain tool definitions. Port tool logic; keep @tool decorator wrappers in Python. |
| `toolkits/shell_compat.py` | 33 | Rust | P2 | S | — | Toolkit logic. Port pure computation to Rust; keep LangChain tool wrappers in Python. |

---

### Module: `tools` — 1 files, 835 lines

**Module recommendation:** `metadata.py` is LangChain-dependent (tool metadata extraction). Keep in Python.

**Breakdown:** 0 Rust-migratable, 1 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `tools/metadata.py` | 835 | LC | P3 | XL | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |

---

### Module: `utils` — 18 files, 2,362 lines

**Module recommendation:** Most files already use `_rust_compat` with corresponding `soothe-nano-utils` crate. Complete remaining fallback logic. `runtime.py` depends on browser-use.

**Breakdown:** 15 Rust-migratable, 1 LangChain-dependent, 2 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `utils/browser_cdp.py` | 298 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/circuit_breaker.py` | 294 | Rust | P0 | M | asyncio | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/token_usage.py` | 267 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `utils/runtime.py` | 260 | Py | P1 | M | browser-use | Browser automation library. Keep in Python — browser-use has no Rust equivalent. |
| `utils/tool_error_handler.py` | 254 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/output_capture.py` | 192 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/text_preview.py` | 188 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/progress.py` | 140 | Rust | P0 | M | asyncio, browser-use | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/prompt_clock.py` | 99 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/logging.py` | 72 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/token_counting.py` | 63 | Rust | P0 | S | tiktoken | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/serde.py` | 61 | Py | P1 | S | langgraph-checkpoint | LangGraph checkpoint integration. Keep in Python — checkpoint protocol is Python-native. |
| `utils/json_parsing.py` | 45 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/formatting.py` | 44 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/subagent_emit.py` | 38 | Rust | P1 | S | — | Pure utility logic. Port to soothe-nano-utils Rust crate. Low risk, high value. |
| `utils/path.py` | 27 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/url_validation.py` | 13 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `utils/thread_id.py` | 7 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |

---

### Module: `ux` — 2 files, 643 lines

**Module recommendation:** `task_namespace.py` is already migrated. `stream_tool_wire.py` is pure logic and Rust-migratable.

**Breakdown:** 2 Rust-migratable, 0 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `ux/task_namespace.py` | 508 | Rust | P0 | M | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |
| `ux/stream_tool_wire.py` | 135 | Rust | P1 | M | — | UX formatting logic. Port to Rust utils crate. |

---

### Module: `workspace` — 5 files, 1,292 lines

**Module recommendation:** `workspace_api.py` is already migrated. `workspace_filesystem.py` and `workspace_paths.py` are LangChain-dependent. `workspace_policy.py` and `workspace_runtime.py` are pure logic.

**Breakdown:** 3 Rust-migratable, 2 LangChain-dependent, 0 Python-only

| File | Lines | Category | Priority | Effort | Dependencies | Recommendation |
|---|---:|---|---|---|---|---|
| `workspace/workspace_filesystem.py` | 824 | LC | P3 | XL | asyncio, langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `workspace/workspace_paths.py` | 190 | LC | P3 | M | langchain/deepagents | Coupled to LangChain/LangGraph ecosystem. Requires ecosystem-level migration strategy. |
| `workspace/workspace_policy.py` | 106 | Rust | P1 | M | — | Workspace path/policy logic. Port to soothe-nano-workspace crate. |
| `workspace/workspace_runtime.py` | 103 | Rust | P1 | M | — | Workspace path/policy logic. Port to soothe-nano-workspace crate. |
| `workspace/workspace_api.py` | 69 | Rust | P0 | S | — | Already partially migrated to Rust via _rust_compat. Complete remaining Python fallback logic in Rust crate. |

---

## Migration Roadmap (Priority-Ordered)

### P0 — Already partially migrated — complete the Rust port (45 files, 8,289 lines)

| File | Lines | Category | Effort | Deps |
|---|---:|---|---|---|
| `security/path_security.py` | 515 | Rust | M | — |
| `ux/task_namespace.py` | 508 | Rust | M | — |
| `security/security_enforcer.py` | 470 | Rust | M | — |
| `security/policy_models.py` | 444 | Rust | M | — |
| `protocols/identity.py` | 439 | Rust | M | pydantic |
| `security/operation_guard.py` | 414 | Rust | M | — |
| `persistence/sqlite_runtime.py` | 361 | Rust | M | asyncio |
| `core/registry.py` | 321 | Rust | M | pydantic |
| `utils/browser_cdp.py` | 298 | Rust | M | — |
| `utils/circuit_breaker.py` | 294 | Rust | M | asyncio |
| `protocols/planner.py` | 254 | Rust | M | pydantic |
| `utils/tool_error_handler.py` | 254 | Rust | M | — |
| `prompts/project_instructions.py` | 214 | Rust | M | — |
| `protocols/durability.py` | 211 | Rust | M | pydantic |
| `protocols/policy.py` | 205 | Rust | M | pydantic |
| `core/events.py` | 200 | Rust | M | pydantic |
| `diagnose/observability.py` | 196 | Rust | M | langfuse |
| `utils/output_capture.py` | 192 | Rust | M | — |
| `utils/text_preview.py` | 188 | Rust | M | — |
| `events/catalog.py` | 178 | Rust | M | — |
| `prompts/context_xml.py` | 174 | Rust | M | — |
| `core/subagent_wire.py` | 160 | Rust | M | — |
| `skills/budget.py` | 150 | Rust | M | — |
| `diagnose/vector_stores.py` | 141 | Rust | M | sqlite-vec, weaviate |
| `utils/progress.py` | 140 | Rust | M | asyncio, browser-use |
| `diagnose/mcp.py` | 123 | Rust | M | — |
| `protocols/memory.py` | 109 | Rust | M | pydantic |
| `diagnose/models.py` | 99 | Rust | S | — |
| `utils/prompt_clock.py` | 99 | Rust | S | — |
| `config/constants.py` | 83 | Rust | S | — |
| `filesystem/discovery_hints.py` | 83 | Rust | S | — |
| `config/env.py` | 82 | Rust | S | — |
| `diagnose/protocols.py` | 79 | Rust | S | sqlite-vec, weaviate |
| `protocols/operation_security.py` | 78 | Rust | S | pydantic |
| `utils/logging.py` | 72 | Rust | S | — |
| `diagnose/models_check.py` | 71 | Rust | S | — |
| `workspace/workspace_api.py` | 69 | Rust | S | — |
| `skills/corpus_match.py` | 64 | Rust | S | — |
| `utils/token_counting.py` | 63 | Rust | S | tiktoken |
| `core/verbosity.py` | 58 | Rust | S | — |
| `utils/json_parsing.py` | 45 | Rust | S | — |
| `utils/formatting.py` | 44 | Rust | S | — |
| `utils/path.py` | 27 | Rust | S | — |
| `utils/url_validation.py` | 13 | Rust | S | — |
| `utils/thread_id.py` | 7 | Rust | S | — |

### P1 — High-value, low-risk — pure logic, no external deps (46 files, 10,469 lines)

| File | Lines | Category | Effort | Deps |
|---|---:|---|---|---|
| `backends/memory/memu/memory_store.py` | 654 | Rust | M | — |
| `backends/memory/memu/memory/memory_agent.py` | 620 | Rust | M | — |
| `backends/memory/memu/memory/actions/link_related_memories.py` | 543 | Rust | M | — |
| `backends/memory/memu/memory/actions/update_memory_with_suggestions.py` | 535 | Rust | M | — |
| `persistence/db_init/runner.py` | 471 | Py | M | psycopg |
| `backends/vector_store/pgvector.py` | 412 | Py | M | psycopg |
| `security/policy_profiles.py` | 411 | Rust | M | — |
| `backends/memory/memu/memory/recall_agent.py` | 401 | Rust | M | — |
| `backends/vector_store/sqlite_vec.py` | 393 | Py | M | sqlite-vec |
| `backends/persistence/postgres_store.py` | 391 | Py | M | asyncio, psycopg |
| `backends/memory/memu/memory/actions/base_action.py` | 347 | Rust | M | — |
| `backends/memory/memu/memory/actions/add_activity_memory.py` | 325 | Rust | M | — |
| `backends/memory/memu/memory/file_manager.py` | 324 | Rust | M | — |
| `backends/vector_store/weaviate.py` | 323 | Py | M | weaviate |
| `backends/memory/memu/memory/actions/cluster_memories.py` | 292 | Rust | M | — |
| `backends/memory/memu/memory/actions/run_theory_of_mind.py` | 277 | Rust | M | — |
| `prompts/system_templates.py` | 275 | Py | M | browser-use |
| `utils/runtime.py` | 260 | Py | M | browser-use |
| `backends/memory/memu/config/markdown_config.py` | 249 | Py | M | pyyaml |
| `backends/durability/base.py` | 243 | Rust | M | — |
| `persistence/postgres_pool_registry.py` | 243 | Py | M | asyncio, psycopg |
| `persistence/postgres_provisioning.py` | 220 | Py | M | asyncio, langgraph-checkpoint, psycopg |
| `backends/memory/memu/memory/actions/generate_suggestions.py` | 217 | Rust | M | — |
| `persistence/retry_utils.py` | 189 | Py | M | asyncio, psycopg |
| `backends/persistence/sqlite_store.py` | 172 | Rust | M | — |
| `filesystem/exceptions.py` | 145 | Py | M | — |
| `protocols/vector_store.py` | 140 | Py | M | pydantic |
| `ux/stream_tool_wire.py` | 135 | Rust | M | — |
| `persistence/postgres_pool_lifecycle.py` | 134 | Py | M | psycopg |
| `backends/memory/memu/memory/embeddings.py` | 125 | Rust | M | — |
| `persistence/shared_metadata_pool.py` | 115 | Py | M | psycopg |
| `workspace/workspace_policy.py` | 106 | Rust | M | — |
| `backends/memory/memu/models.py` | 105 | Py | M | pydantic |
| `backends/memory/memu/llm_client.py` | 103 | Rust | M | — |
| `workspace/workspace_runtime.py` | 103 | Rust | M | — |
| `security/security_api.py` | 81 | Rust | S | — |
| `utils/serde.py` | 61 | Py | S | langgraph-checkpoint |
| `protocols/persistence.py` | 59 | Py | S | — |
| `core/exceptions.py` | 55 | Py | S | — |
| `prompts/identity.py` | 50 | Rust | S | — |
| `backends/durability/sqlite.py` | 39 | Rust | S | — |
| `utils/subagent_emit.py` | 38 | Rust | S | — |
| `backends/memory/memu/llm_adapter.py` | 33 | Rust | S | — |
| `backends/durability/postgresql.py` | 25 | Rust | S | — |
| `config/middleware_access.py` | 16 | Rust | S | — |
| `core/types.py` | 14 | Py | S | — |

### P2 — Medium priority — some deps, requires FFI bridge (146 files, 25,781 lines)

| File | Lines | Category | Effort | Deps |
|---|---:|---|---|---|
| `toolkits/url_crawl/polite_http.py` | 447 | Py | XL | asyncio, deepxiv-sdk, tarzi, tavily |
| `_rust_compat.py` | 1619 | Rust | L | tiktoken |
| `skills/builtin/office/scripts/office/validators/base.py` | 824 | Py | L | — |
| `toolkits/_internal/wizsearch.py` | 786 | Py | M | asyncio, tavily |
| `skills/builtin/drawio/scripts/autolayout.py` | 457 | Py | M | — |
| `skills/builtin/office/scripts/office/validators/docx.py` | 444 | Py | M | — |
| `skills/builtin/office/scripts/office/validators/pptx.py` | 428 | Py | M | — |
| `skills/builtin/office/scripts/comment.py` | 411 | Py | M | — |
| `skills/builtin/mcp-builder/scripts/evaluation.py` | 407 | Py | M | asyncio |
| `plugin/lifecycle.py` | 405 | Py | M | asyncio |
| `skills/builtin/skill-creator/scripts/init_skill.py` | 383 | Py | M | — |
| `skills/builtin/office/scripts/add_slide.py` | 377 | Py | M | — |
| `skills/builtin/drawio/scripts/buildup.py` | 367 | Py | M | — |
| `skills/builtin/drawio/scripts/validate.py` | 356 | Py | M | — |
| `skills/registry.py` | 320 | Py | M | pathspec |
| `skills/builtin/office/scripts/thumbnail.py` | 306 | Py | M | — |
| `skills/builtin/office/scripts/merge_runs.py` | 303 | Py | M | — |
| `skills/builtin/office/scripts/clean.py` | 302 | Py | M | — |
| `skills/builtin/office/scripts/recalc.py` | 301 | Py | M | — |
| `mcp/mcp_events.py` | 289 | Rust | M | — |
| `skills/builtin/drawio/scripts/tfimports.py` | 287 | Py | M | — |
| `skills/builtin/office/scripts/office/validators/redlining.py` | 287 | Py | M | — |
| `skills/builtin/drawio/scripts/timelapse.py` | 286 | Py | M | — |
| `skills/builtin/drawio/scripts/k8simports.py` | 270 | Py | M | pyyaml |
| `skills/builtin/drawio/scripts/compress.py` | 269 | Py | M | — |
| `plugin/registry.py` | 260 | Rust | M | — |
| `llm/registry.py` | 255 | Py | M | litellm |
| `resolve/_resolver_infra.py` | 246 | Py | M | langgraph-checkpoint, psycopg |
| `skills/builtin/drawio/scripts/runbook.py` | 246 | Py | M | — |
| `skills/builtin/drawio/scripts/heatmap.py` | 242 | Py | M | — |
| `resolve/shared_checkpointer_pool.py` | 240 | Py | M | asyncio, langgraph-checkpoint, psycopg |
| `skills/workspace_sync.py` | 240 | Py | M | — |
| `skills/builtin/drawio/scripts/drawiohtml.py` | 238 | Py | M | — |
| `skills/builtin/drawio/scripts/seqlayout.py` | 235 | Py | M | — |
| `skills/builtin/drawio/scripts/aiicons.py` | 234 | Py | M | — |
| `skills/builtin/drawio/scripts/ciimports.py` | 229 | Py | M | pyyaml |
| `skills/builtin/drawio/scripts/prdiff.py` | 221 | Py | M | — |
| `plugin/discovery.py` | 212 | Py | M | browser-use |
| `skills/builtin/drawio/scripts/rustimports.py` | 210 | Py | M | — |
| `toolkits/_internal/backend_ops.py` | 208 | Rust | M | — |
| `skills/builtin/drawio/scripts/raster2drawio.py` | 207 | Py | M | — |
| `skills/builtin/skill-creator/scripts/quick_validate.py` | 204 | Py | M | pyyaml |
| `llm/thinking.py` | 199 | Rust | M | — |
| `skills/builtin/drawio/scripts/c4.py` | 199 | Py | M | — |
| `middleware/_tool_context.py` | 193 | Rust | M | — |
| `skills/builtin/office/scripts/office/soffice.py` | 190 | Py | M | — |
| `toolkits/progressive/registry.py` | 189 | Rust | M | — |
| `skills/builtin/drawio/scripts/openapiimports.py` | 188 | Py | M | pyyaml |
| `skills/builtin/office/scripts/office/helpers/pptx_chart.py` | 188 | Py | M | — |
| `skills/builtin/drawio/scripts/tubemap.py` | 181 | Py | M | — |
| `subagents/academic_research/termination.py` | 181 | Rust | M | — |
| `subagents/deep_research/termination.py` | 181 | Rust | M | — |
| `skills/builtin/drawio/scripts/sqlerd.py` | 179 | Py | M | — |
| `skills/builtin/drawio/scripts/restyle.py` | 178 | Py | M | — |
| `subagents/academic_research/sources/academic_search.py` | 178 | Py | M | deepxiv-sdk, tarzi |
| `skills/builtin/drawio/scripts/drawiodiff.py` | 176 | Py | M | — |
| `toolkits/progressive/budget.py` | 174 | Rust | M | — |
| `skills/builtin/drawio/scripts/shapesearch.py` | 173 | Py | M | — |
| `skills/builtin/office/scripts/office/validate.py` | 172 | Py | M | — |
| `skills/builtin/drawio/scripts/explain.py` | 169 | Py | M | — |
| `mcp/cleanup.py` | 165 | Py | M | asyncio |
| `skills/builtin/drawio/scripts/dockerimports.py` | 165 | Py | M | — |
| `toolkits/_internal/tabular.py` | 164 | Py | M | pandas |
| `skills/builtin/drawio/scripts/jsimports.py` | 163 | Py | M | — |
| `skills/builtin/drawio/scripts/pyclasses.py` | 162 | Py | M | — |
| `skills/builtin/drawio/scripts/drawio2mermaid.py` | 160 | Py | M | — |
| `skills/builtin/drawio/scripts/pyimports.py` | 160 | Py | M | — |
| `plugin/context.py` | 158 | Rust | M | — |
| `mcp/mcp_utils.py` | 157 | Rust | M | — |
| `skills/builtin/mcp-builder/scripts/connections.py` | 151 | Py | M | — |
| `skills/builtin/drawio/scripts/tfstate.py` | 150 | Py | M | — |
| `skills/builtin/drawio/scripts/goimports.py` | 148 | Py | M | — |
| `resolve/_lazy_subagent.py` | 147 | Rust | M | — |
| `mcp/reconnect.py` | 143 | Py | M | asyncio |
| `observability/langfuse/_merge.py` | 143 | Py | M | langfuse |
| `skills/builtin/drawio/scripts/composeimports.py` | 136 | Py | M | pyyaml |
| `skills/builtin/skill-creator/scripts/package_skill.py` | 135 | Py | M | — |
| `skills/builtin/office/scripts/accept_changes.py` | 131 | Py | M | — |
| `skills/builtin/pdf/scripts/extract_form_field_info.py` | 130 | Py | M | — |
| `observability/langfuse/tracer.py` | 129 | Py | M | langfuse |
| `skills/builtin/drawio/scripts/drawio2pptx.py` | 129 | Py | M | — |
| `subagents/browser_use/action_format.py` | 122 | Py | M | browser-use |
| `subagents/academic_research/events.py` | 118 | Py | M | pydantic |
| `toolkits/url_crawl/crawler.py` | 118 | Py | M | asyncio, pydantic |
| `skills/builtin/pdf/scripts/extract_form_structure.py` | 116 | Py | M | — |
| `subagents/deep_research/events.py` | 112 | Py | M | pydantic |
| `llm/response_text.py` | 110 | Rust | M | — |
| `skills/builtin/drawio/scripts/relabel.py` | 110 | Py | M | — |
| `skills/builtin/office/scripts/office/helpers/pptx_theme.py` | 110 | Py | M | — |
| `observability/langfuse/_client.py` | 108 | Py | M | langfuse |
| `skills/builtin/pdf/scripts/fill_pdf_form_with_annotations.py` | 108 | Py | M | — |
| `subagents/academic_research/effort.py` | 108 | Py | M | pydantic |
| `subagents/deep_research/effort.py` | 108 | Py | M | pydantic |
| `observability/langfuse/_trace_io.py` | 107 | Py | M | langfuse |
| `subagents/computer_use/action_format.py` | 104 | Rust | M | — |
| `plugin/events.py` | 103 | Rust | M | — |
| `skills/builtin/pdf/scripts/fill_fillable_fields.py` | 103 | Py | M | — |
| `subagents/academic_research/persistence.py` | 99 | Rust | S | — |
| `subagents/deep_research/persistence.py` | 99 | Rust | S | — |
| `plugin/exceptions.py` | 97 | Py | S | — |
| `subagents/academic_research/protocol.py` | 97 | Py | S | pydantic |
| `subagents/academic_research/display_summary.py` | 93 | Rust | S | — |
| `observability/langfuse/system_hint.py` | 92 | Py | S | langfuse |
| `plugin/emit.py` | 92 | Rust | S | — |
| `subagents/academic_research/references.py` | 92 | Rust | S | — |
| `subagents/deep_research/display_summary.py` | 92 | Rust | S | — |
| `subagents/deep_research/protocol.py` | 92 | Py | S | pydantic |
| `subagents/deep_research/references.py` | 92 | Rust | S | — |
| `subagents/_research_topic_util.py` | 91 | Rust | S | — |
| `plugin/global_registry.py` | 87 | Rust | S | — |
| `skills/builtin/drawio/scripts/svgflow.py` | 86 | Py | S | — |
| `subagents/computer_use/config_model.py` | 84 | Py | S | pyautogui, pydantic |
| `subagents/browser_use/events.py` | 80 | Py | S | browser-use, pydantic |
| `subagents/computer_use/events.py` | 80 | Py | S | pydantic |
| `diagnose/api.py` | 74 | Rust | S | — |
| `skills/builtin/pdf/scripts/check_bounding_boxes.py` | 74 | Py | S | — |
| `_dotenv.py` | 69 | Rust | S | — |
| `plugin/manifest.py` | 62 | Py | S | pydantic |
| `llm/schema_wire.py` | 61 | Py | S | litellm |
| `skills/builtin/office/scripts/office/helpers/pptx_slide.py` | 59 | Py | S | — |
| `skills/builtin/drawio/scripts/encode_drawio_url.py` | 58 | Py | S | — |
| `subagents/research_wire.py` | 56 | Rust | S | — |
| `subagents/_research_json_util.py` | 55 | Rust | S | — |
| `llm/types.py` | 52 | Py | S | litellm |
| `subagents/browser_use/config_model.py` | 50 | Py | S | browser-use, pydantic |
| `plugin/lazy.py` | 48 | Rust | S | — |
| `intention/models.py` | 46 | Py | S | pydantic |
| `skills/builtin/pdf/scripts/create_validation_image.py` | 39 | Py | S | — |
| `skills/builtin/drawio/scripts/repair_png.py` | 38 | Py | S | — |
| `skills/builtin/pdf/scripts/convert_pdf_to_images.py` | 33 | Py | S | — |
| `toolkits/shell_compat.py` | 33 | Rust | S | — |
| `observability/langfuse/_types.py` | 32 | Py | S | langfuse |
| `subagents/_research_timeouts.py` | 32 | Py | S | tavily |
| `logging/context.py` | 28 | Rust | S | — |
| `plugin/cache.py` | 26 | Rust | S | — |
| `agent/subagent_catalog.py` | 19 | Rust | S | — |
| `plugin/health.py` | 19 | Py | S | pydantic |
| `subagents/browser_use/display_summary.py` | 18 | Py | S | browser-use |
| `subagents/computer_use/display_summary.py` | 18 | Rust | S | — |
| `subagents/academic_research/json_util.py` | 17 | Rust | S | — |
| `subagents/deep_research/json_util.py` | 17 | Rust | S | — |
| `observability/langfuse/_names.py` | 16 | Py | S | langfuse |
| `subagents/browser_use/_preview.py` | 16 | Rust | S | — |
| `subagents/computer_use/_preview.py` | 16 | Py | S | browser-use |
| `skills/builtin/pdf/scripts/check_fillable_fields.py` | 13 | Py | S | — |
| `agent/factory.py` | 5 | Py | S | — |

### P3 — Low priority — blocked on ecosystem migration (96 files, 35,601 lines)

| File | Lines | Category | Effort | Deps |
|---|---:|---|---|---|
| `config/models.py` | 2025 | LC | XL | browser-use, deepxiv-sdk, langchain/deepagents, langfuse, langgraph-checkpoint, psycopg, pydantic, sqlite-vec, tarzi, tavily, weaviate |
| `subagents/computer_use/implementation.py` | 1748 | LC | XL | asyncio, browser-use, langchain/deepagents, pyautogui, pydantic |
| `filesystem/local.py` | 1410 | LC | XL | aiofiles, asyncio, langchain/deepagents, wcmatch |
| `toolkits/execution.py` | 1218 | LC | XL | langchain/deepagents, pydantic |
| `config/settings.py` | 1144 | LC | XL | browser-use, deepxiv-sdk, langchain/deepagents, langgraph-checkpoint, pydantic, pyyaml, sqlite-vec, tarzi, weaviate |
| `llm/provider.py` | 1075 | LC | XL | asyncio, langchain/deepagents, litellm, pydantic |
| `toolkits/deepxiv.py` | 920 | LC | XL | deepxiv-sdk, langchain/deepagents, pydantic, tarzi |
| `middleware/edit_coalescing.py` | 900 | LC | XL | aiofiles, asyncio, langchain/deepagents |
| `filesystem/unified.py` | 852 | LC | XL | langchain/deepagents |
| `tools/metadata.py` | 835 | LC | XL | langchain/deepagents |
| `subagents/browser_use/implementation.py` | 832 | LC | XL | asyncio, browser-use, langchain/deepagents, pydantic |
| `workspace/workspace_filesystem.py` | 824 | LC | XL | asyncio, langchain/deepagents |
| `llm/invoke_policy.py` | 791 | LC | L | asyncio, langchain/deepagents |
| `filesystem/workspace.py` | 746 | LC | L | asyncio, langchain/deepagents, pathspec, wcmatch |
| `middleware/system_prompt.py` | 714 | LC | L | browser-use, langchain/deepagents, langfuse |
| `resolve/_resolver_tools.py` | 674 | LC | L | asyncio, browser-use, deepxiv-sdk, langchain/deepagents, tarzi |
| `subagents/plan/engine.py` | 668 | LC | L | langchain/deepagents, pydantic |
| `subagents/academic_research/engine.py` | 628 | LC | L | asyncio, langchain/deepagents |
| `subagents/deep_research/engine.py` | 626 | LC | L | asyncio, langchain/deepagents |
| `middleware/tool_optimization_middleware.py` | 584 | LC | L | asyncio, langchain/deepagents |
| `middleware/model_call_profiler.py` | 582 | LC | L | langchain/deepagents |
| `skills/catalog.py` | 547 | LC | L | langchain/deepagents |
| `agent/builder.py` | 541 | LC | L | asyncio, langchain/deepagents, langgraph-checkpoint |
| `toolkits/data.py` | 496 | LC | L | langchain/deepagents, pydantic |
| `middleware/skill_activation.py` | 483 | LC | L | asyncio, langchain/deepagents |
| `subagents/computer_use/tools.py` | 433 | LC | L | langchain/deepagents, pyautogui, pydantic |
| `toolkits/_internal/document.py` | 433 | LC | L | PyMuPDF, langchain/deepagents, requests |
| `middleware/_builder.py` | 425 | LC | L | langchain/deepagents |
| `toolkits/wizsearch.py` | 403 | LC | L | langchain/deepagents, pydantic, tavily |
| `plugin/decorators.py` | 395 | LC | L | asyncio, langchain/deepagents |
| `llm/structured.py` | 392 | LC | L | jsonschema, langchain/deepagents, pydantic |
| `agent/core_agent.py` | 379 | LC | L | langchain/deepagents, langgraph-checkpoint |
| `observability/langfuse/callback_handler.py` | 325 | LC | L | asyncio, langchain/deepagents, langfuse |
| `plugin/loader.py` | 314 | LC | L | langchain/deepagents |
| `llm/message.py` | 309 | LC | L | langchain/deepagents, litellm, pydantic |
| `middleware/filesystem.py` | 306 | LC | L | langchain/deepagents |
| `mcp/mcp_registry.py` | 304 | LC | L | asyncio, langchain/deepagents |
| `agent/dual_mode.py` | 303 | LC | L | langchain/deepagents, langgraph-checkpoint |
| `middleware/progressive_listing.py` | 294 | LC | M | langchain/deepagents |
| `subagents/deep_research/sources/web_search.py` | 279 | LC | M | langchain/deepagents, tavily |
| `diagnose/providers.py` | 272 | LC | M | asyncio, langchain/deepagents |
| `llm/traced.py` | 271 | LC | M | langchain/deepagents, langfuse |
| `llm/tools.py` | 267 | LC | M | langchain/deepagents, litellm |
| `utils/token_usage.py` | 267 | LC | M | langchain/deepagents |
| `toolkits/image.py` | 262 | LC | M | asyncio, langchain/deepagents, pydantic |
| `logging/setup.py` | 257 | LC | M | browser-use, langchain/deepagents, langfuse |
| `middleware/progressive_tools.py` | 256 | LC | M | langchain/deepagents |
| `skills/index.py` | 252 | LC | M | langchain/deepagents |
| `middleware/mcp_activation.py` | 251 | LC | M | langchain/deepagents |
| `llm/observability.py` | 242 | LC | M | langchain/deepagents |
| `middleware/tool_result_storage.py` | 233 | LC | M | langchain/deepagents |
| `middleware/tool_result_eviction.py` | 229 | LC | M | langchain/deepagents |
| `llm/base.py` | 207 | LC | M | langchain/deepagents, litellm |
| `agent/interaction_mode.py` | 202 | LC | M | langchain/deepagents |
| `mcp/mcp_config.py` | 201 | LC | M | langchain/deepagents |
| `mcp/mcp_registry_support.py` | 197 | LC | M | asyncio, langchain/deepagents |
| `agent/lazy.py` | 195 | LC | M | langchain/deepagents, langgraph-checkpoint |
| `middleware/code_interpreter.py` | 195 | LC | M | langchain-quickjs, langchain/deepagents |
| `workspace/workspace_paths.py` | 190 | LC | M | langchain/deepagents |
| `middleware/tool_result_storage_middleware.py` | 182 | LC | M | langchain/deepagents |
| `protocols/core_agent.py` | 181 | LC | M | langchain/deepagents, langgraph-checkpoint |
| `backends/memory/memu_adapter.py` | 174 | LC | M | langchain/deepagents |
| `llm/factory.py` | 170 | LC | M | langchain/deepagents, litellm |
| `subagents/deep_research/report_classifier.py` | 170 | LC | M | langchain/deepagents, pydantic |
| `mcp/mcp_progressive.py` | 168 | LC | M | langchain/deepagents, pydantic |
| `subagents/academic_research/report_classifier.py` | 168 | LC | M | langchain/deepagents, pydantic |
| `middleware/policy.py` | 162 | LC | M | langchain/deepagents |
| `observability/langfuse/_handlers.py` | 161 | LC | M | langchain/deepagents, langfuse |
| `skills/search.py` | 158 | LC | M | langchain/deepagents |
| `middleware/role_routing.py` | 153 | LC | M | langchain/deepagents |
| `backends/memory/memu/langchain_adapter.py` | 149 | LC | M | langchain/deepagents |
| `diagnose/tool_deps.py` | 148 | LC | M | langchain/deepagents |
| `middleware/read_coalescing.py` | 144 | LC | M | asyncio, langchain/deepagents |
| `middleware/tool_enforcement.py` | 138 | LC | M | langchain/deepagents |
| `skills/builtins.py` | 135 | LC | M | langchain/deepagents |
| `middleware/workspace_context.py` | 133 | LC | M | langchain/deepagents |
| `mcp/mcp_resource_tools.py` | 103 | LC | M | langchain/deepagents, pydantic |
| `toolkits/http_requests.py` | 98 | LC | S | langchain/deepagents |
| `toolkits/file_ops_catalog.py` | 89 | LC | S | langchain/deepagents |
| `skills/discovery_tools.py` | 86 | LC | S | langchain/deepagents, pydantic |
| `toolkits/datetime.py` | 86 | LC | S | langchain/deepagents |
| `toolkits/file_ops.py` | 82 | LC | S | langchain/deepagents |
| `middleware/tool_call_args_registry.py` | 75 | LC | S | langchain/deepagents |
| `middleware/per_turn_model.py` | 73 | LC | S | langchain/deepagents |
| `middleware/tool_error_guard.py` | 70 | LC | S | asyncio, langchain/deepagents |
| `subagents/academic_research/implementation.py` | 68 | LC | S | langchain/deepagents |
| `subagents/deep_research/implementation.py` | 68 | LC | S | langchain/deepagents |
| `protocols/concurrency.py` | 66 | LC | S | langchain/deepagents, pydantic |
| `middleware/tool_call_args_middleware.py` | 61 | LC | S | langchain/deepagents |
| `resolve/_tool_cache.py` | 61 | LC | S | langchain/deepagents |
| `plugin/depends.py` | 55 | LC | S | langchain/deepagents |
| `toolkits/_internal/local_path_resolution.py` | 43 | LC | S | langchain/deepagents |
| `toolkits/progressive/search_tool.py` | 34 | LC | S | langchain/deepagents, pydantic |
| `_upstream_warnings.py` | 32 | LC | S | langchain/deepagents |
| `middleware/tool_name_hints.py` | 32 | LC | S | langchain/deepagents |
| `llm/exceptions.py` | 22 | LC | S | langchain/deepagents |

---

## Appendix A: All Rust-Migratable Files

**109 files, 20,089 lines**

| File | Lines | Already using _rust_compat | Dependencies |
|---|---:|---|---|
| `_dotenv.py` | 69 | No | — |
| `_rust_compat.py` | 1619 | No | tiktoken |
| `agent/subagent_catalog.py` | 19 | No | — |
| `backends/durability/base.py` | 243 | No | — |
| `backends/durability/postgresql.py` | 25 | No | — |
| `backends/durability/sqlite.py` | 39 | No | — |
| `backends/memory/memu/llm_adapter.py` | 33 | No | — |
| `backends/memory/memu/llm_client.py` | 103 | No | — |
| `backends/memory/memu/memory/actions/add_activity_memory.py` | 325 | No | — |
| `backends/memory/memu/memory/actions/base_action.py` | 347 | No | — |
| `backends/memory/memu/memory/actions/cluster_memories.py` | 292 | No | — |
| `backends/memory/memu/memory/actions/generate_suggestions.py` | 217 | No | — |
| `backends/memory/memu/memory/actions/link_related_memories.py` | 543 | No | — |
| `backends/memory/memu/memory/actions/run_theory_of_mind.py` | 277 | No | — |
| `backends/memory/memu/memory/actions/update_memory_with_suggestions.py` | 535 | No | — |
| `backends/memory/memu/memory/embeddings.py` | 125 | No | — |
| `backends/memory/memu/memory/file_manager.py` | 324 | No | — |
| `backends/memory/memu/memory/memory_agent.py` | 620 | No | — |
| `backends/memory/memu/memory/recall_agent.py` | 401 | No | — |
| `backends/memory/memu/memory_store.py` | 654 | No | — |
| `backends/persistence/sqlite_store.py` | 172 | No | — |
| `config/constants.py` | 83 | Yes | — |
| `config/env.py` | 82 | Yes | — |
| `config/middleware_access.py` | 16 | No | — |
| `core/events.py` | 200 | Yes | pydantic |
| `core/registry.py` | 321 | Yes | pydantic |
| `core/subagent_wire.py` | 160 | Yes | — |
| `core/verbosity.py` | 58 | Yes | — |
| `diagnose/api.py` | 74 | No | — |
| `diagnose/mcp.py` | 123 | Yes | — |
| `diagnose/models.py` | 99 | Yes | — |
| `diagnose/models_check.py` | 71 | Yes | — |
| `diagnose/observability.py` | 196 | Yes | langfuse |
| `diagnose/protocols.py` | 79 | Yes | sqlite-vec, weaviate |
| `diagnose/vector_stores.py` | 141 | Yes | sqlite-vec, weaviate |
| `events/catalog.py` | 178 | Yes | — |
| `filesystem/discovery_hints.py` | 83 | Yes | — |
| `llm/response_text.py` | 110 | No | — |
| `llm/thinking.py` | 199 | No | — |
| `logging/context.py` | 28 | No | — |
| `mcp/mcp_events.py` | 289 | No | — |
| `mcp/mcp_utils.py` | 157 | No | — |
| `middleware/_tool_context.py` | 193 | No | — |
| `persistence/sqlite_runtime.py` | 361 | Yes | asyncio |
| `plugin/cache.py` | 26 | No | — |
| `plugin/context.py` | 158 | No | — |
| `plugin/emit.py` | 92 | No | — |
| `plugin/events.py` | 103 | No | — |
| `plugin/global_registry.py` | 87 | No | — |
| `plugin/lazy.py` | 48 | No | — |
| `plugin/registry.py` | 260 | No | — |
| `prompts/context_xml.py` | 174 | Yes | — |
| `prompts/identity.py` | 50 | No | — |
| `prompts/project_instructions.py` | 214 | Yes | — |
| `protocols/durability.py` | 211 | Yes | pydantic |
| `protocols/identity.py` | 439 | Yes | pydantic |
| `protocols/memory.py` | 109 | Yes | pydantic |
| `protocols/operation_security.py` | 78 | Yes | pydantic |
| `protocols/planner.py` | 254 | Yes | pydantic |
| `protocols/policy.py` | 205 | Yes | pydantic |
| `resolve/_lazy_subagent.py` | 147 | No | — |
| `security/operation_guard.py` | 414 | Yes | — |
| `security/path_security.py` | 515 | Yes | — |
| `security/policy_models.py` | 444 | Yes | — |
| `security/policy_profiles.py` | 411 | No | — |
| `security/security_api.py` | 81 | No | — |
| `security/security_enforcer.py` | 470 | Yes | — |
| `skills/budget.py` | 150 | Yes | — |
| `skills/corpus_match.py` | 64 | Yes | — |
| `subagents/_research_json_util.py` | 55 | No | — |
| `subagents/_research_topic_util.py` | 91 | No | — |
| `subagents/academic_research/display_summary.py` | 93 | No | — |
| `subagents/academic_research/json_util.py` | 17 | No | — |
| `subagents/academic_research/persistence.py` | 99 | No | — |
| `subagents/academic_research/references.py` | 92 | No | — |
| `subagents/academic_research/termination.py` | 181 | No | — |
| `subagents/browser_use/_preview.py` | 16 | No | — |
| `subagents/computer_use/action_format.py` | 104 | No | — |
| `subagents/computer_use/display_summary.py` | 18 | No | — |
| `subagents/deep_research/display_summary.py` | 92 | No | — |
| `subagents/deep_research/json_util.py` | 17 | No | — |
| `subagents/deep_research/persistence.py` | 99 | No | — |
| `subagents/deep_research/references.py` | 92 | No | — |
| `subagents/deep_research/termination.py` | 181 | No | — |
| `subagents/research_wire.py` | 56 | No | — |
| `toolkits/_internal/backend_ops.py` | 208 | No | — |
| `toolkits/progressive/budget.py` | 174 | No | — |
| `toolkits/progressive/registry.py` | 189 | No | — |
| `toolkits/shell_compat.py` | 33 | No | — |
| `utils/browser_cdp.py` | 298 | Yes | — |
| `utils/circuit_breaker.py` | 294 | Yes | asyncio |
| `utils/formatting.py` | 44 | Yes | — |
| `utils/json_parsing.py` | 45 | Yes | — |
| `utils/logging.py` | 72 | Yes | — |
| `utils/output_capture.py` | 192 | Yes | — |
| `utils/path.py` | 27 | Yes | — |
| `utils/progress.py` | 140 | Yes | asyncio, browser-use |
| `utils/prompt_clock.py` | 99 | Yes | — |
| `utils/subagent_emit.py` | 38 | No | — |
| `utils/text_preview.py` | 188 | Yes | — |
| `utils/thread_id.py` | 7 | Yes | — |
| `utils/token_counting.py` | 63 | Yes | tiktoken |
| `utils/tool_error_handler.py` | 254 | Yes | — |
| `utils/url_validation.py` | 13 | Yes | — |
| `ux/stream_tool_wire.py` | 135 | No | — |
| `ux/task_namespace.py` | 508 | Yes | — |
| `workspace/workspace_api.py` | 69 | Yes | — |
| `workspace/workspace_policy.py` | 106 | No | — |
| `workspace/workspace_runtime.py` | 103 | No | — |

## Appendix B: All LangChain-Dependent Files

**96 files, 35,601 lines**

| File | Lines | Dependencies |
|---|---:|---|
| `_upstream_warnings.py` | 32 | langchain/deepagents |
| `agent/builder.py` | 541 | asyncio, langchain/deepagents, langgraph-checkpoint |
| `agent/core_agent.py` | 379 | langchain/deepagents, langgraph-checkpoint |
| `agent/dual_mode.py` | 303 | langchain/deepagents, langgraph-checkpoint |
| `agent/interaction_mode.py` | 202 | langchain/deepagents |
| `agent/lazy.py` | 195 | langchain/deepagents, langgraph-checkpoint |
| `backends/memory/memu/langchain_adapter.py` | 149 | langchain/deepagents |
| `backends/memory/memu_adapter.py` | 174 | langchain/deepagents |
| `config/models.py` | 2025 | browser-use, deepxiv-sdk, langchain/deepagents, langfuse, langgraph-checkpoint, psycopg, pydantic, sqlite-vec, tarzi, tavily, weaviate |
| `config/settings.py` | 1144 | browser-use, deepxiv-sdk, langchain/deepagents, langgraph-checkpoint, pydantic, pyyaml, sqlite-vec, tarzi, weaviate |
| `diagnose/providers.py` | 272 | asyncio, langchain/deepagents |
| `diagnose/tool_deps.py` | 148 | langchain/deepagents |
| `filesystem/local.py` | 1410 | aiofiles, asyncio, langchain/deepagents, wcmatch |
| `filesystem/unified.py` | 852 | langchain/deepagents |
| `filesystem/workspace.py` | 746 | asyncio, langchain/deepagents, pathspec, wcmatch |
| `llm/base.py` | 207 | langchain/deepagents, litellm |
| `llm/exceptions.py` | 22 | langchain/deepagents |
| `llm/factory.py` | 170 | langchain/deepagents, litellm |
| `llm/invoke_policy.py` | 791 | asyncio, langchain/deepagents |
| `llm/message.py` | 309 | langchain/deepagents, litellm, pydantic |
| `llm/observability.py` | 242 | langchain/deepagents |
| `llm/provider.py` | 1075 | asyncio, langchain/deepagents, litellm, pydantic |
| `llm/structured.py` | 392 | jsonschema, langchain/deepagents, pydantic |
| `llm/tools.py` | 267 | langchain/deepagents, litellm |
| `llm/traced.py` | 271 | langchain/deepagents, langfuse |
| `logging/setup.py` | 257 | browser-use, langchain/deepagents, langfuse |
| `mcp/mcp_config.py` | 201 | langchain/deepagents |
| `mcp/mcp_progressive.py` | 168 | langchain/deepagents, pydantic |
| `mcp/mcp_registry.py` | 304 | asyncio, langchain/deepagents |
| `mcp/mcp_registry_support.py` | 197 | asyncio, langchain/deepagents |
| `mcp/mcp_resource_tools.py` | 103 | langchain/deepagents, pydantic |
| `middleware/_builder.py` | 425 | langchain/deepagents |
| `middleware/code_interpreter.py` | 195 | langchain-quickjs, langchain/deepagents |
| `middleware/edit_coalescing.py` | 900 | aiofiles, asyncio, langchain/deepagents |
| `middleware/filesystem.py` | 306 | langchain/deepagents |
| `middleware/mcp_activation.py` | 251 | langchain/deepagents |
| `middleware/model_call_profiler.py` | 582 | langchain/deepagents |
| `middleware/per_turn_model.py` | 73 | langchain/deepagents |
| `middleware/policy.py` | 162 | langchain/deepagents |
| `middleware/progressive_listing.py` | 294 | langchain/deepagents |
| `middleware/progressive_tools.py` | 256 | langchain/deepagents |
| `middleware/read_coalescing.py` | 144 | asyncio, langchain/deepagents |
| `middleware/role_routing.py` | 153 | langchain/deepagents |
| `middleware/skill_activation.py` | 483 | asyncio, langchain/deepagents |
| `middleware/system_prompt.py` | 714 | browser-use, langchain/deepagents, langfuse |
| `middleware/tool_call_args_middleware.py` | 61 | langchain/deepagents |
| `middleware/tool_call_args_registry.py` | 75 | langchain/deepagents |
| `middleware/tool_enforcement.py` | 138 | langchain/deepagents |
| `middleware/tool_error_guard.py` | 70 | asyncio, langchain/deepagents |
| `middleware/tool_name_hints.py` | 32 | langchain/deepagents |
| `middleware/tool_optimization_middleware.py` | 584 | asyncio, langchain/deepagents |
| `middleware/tool_result_eviction.py` | 229 | langchain/deepagents |
| `middleware/tool_result_storage.py` | 233 | langchain/deepagents |
| `middleware/tool_result_storage_middleware.py` | 182 | langchain/deepagents |
| `middleware/workspace_context.py` | 133 | langchain/deepagents |
| `observability/langfuse/_handlers.py` | 161 | langchain/deepagents, langfuse |
| `observability/langfuse/callback_handler.py` | 325 | asyncio, langchain/deepagents, langfuse |
| `plugin/decorators.py` | 395 | asyncio, langchain/deepagents |
| `plugin/depends.py` | 55 | langchain/deepagents |
| `plugin/loader.py` | 314 | langchain/deepagents |
| `protocols/concurrency.py` | 66 | langchain/deepagents, pydantic |
| `protocols/core_agent.py` | 181 | langchain/deepagents, langgraph-checkpoint |
| `resolve/_resolver_tools.py` | 674 | asyncio, browser-use, deepxiv-sdk, langchain/deepagents, tarzi |
| `resolve/_tool_cache.py` | 61 | langchain/deepagents |
| `skills/builtins.py` | 135 | langchain/deepagents |
| `skills/catalog.py` | 547 | langchain/deepagents |
| `skills/discovery_tools.py` | 86 | langchain/deepagents, pydantic |
| `skills/index.py` | 252 | langchain/deepagents |
| `skills/search.py` | 158 | langchain/deepagents |
| `subagents/academic_research/engine.py` | 628 | asyncio, langchain/deepagents |
| `subagents/academic_research/implementation.py` | 68 | langchain/deepagents |
| `subagents/academic_research/report_classifier.py` | 168 | langchain/deepagents, pydantic |
| `subagents/browser_use/implementation.py` | 832 | asyncio, browser-use, langchain/deepagents, pydantic |
| `subagents/computer_use/implementation.py` | 1748 | asyncio, browser-use, langchain/deepagents, pyautogui, pydantic |
| `subagents/computer_use/tools.py` | 433 | langchain/deepagents, pyautogui, pydantic |
| `subagents/deep_research/engine.py` | 626 | asyncio, langchain/deepagents |
| `subagents/deep_research/implementation.py` | 68 | langchain/deepagents |
| `subagents/deep_research/report_classifier.py` | 170 | langchain/deepagents, pydantic |
| `subagents/deep_research/sources/web_search.py` | 279 | langchain/deepagents, tavily |
| `subagents/plan/engine.py` | 668 | langchain/deepagents, pydantic |
| `toolkits/_internal/document.py` | 433 | PyMuPDF, langchain/deepagents, requests |
| `toolkits/_internal/local_path_resolution.py` | 43 | langchain/deepagents |
| `toolkits/data.py` | 496 | langchain/deepagents, pydantic |
| `toolkits/datetime.py` | 86 | langchain/deepagents |
| `toolkits/deepxiv.py` | 920 | deepxiv-sdk, langchain/deepagents, pydantic, tarzi |
| `toolkits/execution.py` | 1218 | langchain/deepagents, pydantic |
| `toolkits/file_ops.py` | 82 | langchain/deepagents |
| `toolkits/file_ops_catalog.py` | 89 | langchain/deepagents |
| `toolkits/http_requests.py` | 98 | langchain/deepagents |
| `toolkits/image.py` | 262 | asyncio, langchain/deepagents, pydantic |
| `toolkits/progressive/search_tool.py` | 34 | langchain/deepagents, pydantic |
| `toolkits/wizsearch.py` | 403 | langchain/deepagents, pydantic, tavily |
| `tools/metadata.py` | 835 | langchain/deepagents |
| `utils/token_usage.py` | 267 | langchain/deepagents |
| `workspace/workspace_filesystem.py` | 824 | asyncio, langchain/deepagents |
| `workspace/workspace_paths.py` | 190 | langchain/deepagents |

## Appendix C: All Python-Only Files

**128 files, 24,450 lines**

| File | Lines | Dependencies |
|---|---:|---|
| `agent/factory.py` | 5 | — |
| `backends/memory/memu/config/markdown_config.py` | 249 | pyyaml |
| `backends/memory/memu/models.py` | 105 | pydantic |
| `backends/persistence/postgres_store.py` | 391 | asyncio, psycopg |
| `backends/vector_store/pgvector.py` | 412 | psycopg |
| `backends/vector_store/sqlite_vec.py` | 393 | sqlite-vec |
| `backends/vector_store/weaviate.py` | 323 | weaviate |
| `core/exceptions.py` | 55 | — |
| `core/types.py` | 14 | — |
| `filesystem/exceptions.py` | 145 | — |
| `intention/models.py` | 46 | pydantic |
| `llm/registry.py` | 255 | litellm |
| `llm/schema_wire.py` | 61 | litellm |
| `llm/types.py` | 52 | litellm |
| `mcp/cleanup.py` | 165 | asyncio |
| `mcp/reconnect.py` | 143 | asyncio |
| `observability/langfuse/_client.py` | 108 | langfuse |
| `observability/langfuse/_merge.py` | 143 | langfuse |
| `observability/langfuse/_names.py` | 16 | langfuse |
| `observability/langfuse/_trace_io.py` | 107 | langfuse |
| `observability/langfuse/_types.py` | 32 | langfuse |
| `observability/langfuse/system_hint.py` | 92 | langfuse |
| `observability/langfuse/tracer.py` | 129 | langfuse |
| `persistence/db_init/runner.py` | 471 | psycopg |
| `persistence/postgres_pool_lifecycle.py` | 134 | psycopg |
| `persistence/postgres_pool_registry.py` | 243 | asyncio, psycopg |
| `persistence/postgres_provisioning.py` | 220 | asyncio, langgraph-checkpoint, psycopg |
| `persistence/retry_utils.py` | 189 | asyncio, psycopg |
| `persistence/shared_metadata_pool.py` | 115 | psycopg |
| `plugin/discovery.py` | 212 | browser-use |
| `plugin/exceptions.py` | 97 | — |
| `plugin/health.py` | 19 | pydantic |
| `plugin/lifecycle.py` | 405 | asyncio |
| `plugin/manifest.py` | 62 | pydantic |
| `prompts/system_templates.py` | 275 | browser-use |
| `protocols/persistence.py` | 59 | — |
| `protocols/vector_store.py` | 140 | pydantic |
| `resolve/_resolver_infra.py` | 246 | langgraph-checkpoint, psycopg |
| `resolve/shared_checkpointer_pool.py` | 240 | asyncio, langgraph-checkpoint, psycopg |
| `skills/builtin/drawio/scripts/aiicons.py` | 234 | — |
| `skills/builtin/drawio/scripts/autolayout.py` | 457 | — |
| `skills/builtin/drawio/scripts/buildup.py` | 367 | — |
| `skills/builtin/drawio/scripts/c4.py` | 199 | — |
| `skills/builtin/drawio/scripts/ciimports.py` | 229 | pyyaml |
| `skills/builtin/drawio/scripts/composeimports.py` | 136 | pyyaml |
| `skills/builtin/drawio/scripts/compress.py` | 269 | — |
| `skills/builtin/drawio/scripts/dockerimports.py` | 165 | — |
| `skills/builtin/drawio/scripts/drawio2mermaid.py` | 160 | — |
| `skills/builtin/drawio/scripts/drawio2pptx.py` | 129 | — |
| `skills/builtin/drawio/scripts/drawiodiff.py` | 176 | — |
| `skills/builtin/drawio/scripts/drawiohtml.py` | 238 | — |
| `skills/builtin/drawio/scripts/encode_drawio_url.py` | 58 | — |
| `skills/builtin/drawio/scripts/explain.py` | 169 | — |
| `skills/builtin/drawio/scripts/goimports.py` | 148 | — |
| `skills/builtin/drawio/scripts/heatmap.py` | 242 | — |
| `skills/builtin/drawio/scripts/jsimports.py` | 163 | — |
| `skills/builtin/drawio/scripts/k8simports.py` | 270 | pyyaml |
| `skills/builtin/drawio/scripts/openapiimports.py` | 188 | pyyaml |
| `skills/builtin/drawio/scripts/prdiff.py` | 221 | — |
| `skills/builtin/drawio/scripts/pyclasses.py` | 162 | — |
| `skills/builtin/drawio/scripts/pyimports.py` | 160 | — |
| `skills/builtin/drawio/scripts/raster2drawio.py` | 207 | — |
| `skills/builtin/drawio/scripts/relabel.py` | 110 | — |
| `skills/builtin/drawio/scripts/repair_png.py` | 38 | — |
| `skills/builtin/drawio/scripts/restyle.py` | 178 | — |
| `skills/builtin/drawio/scripts/runbook.py` | 246 | — |
| `skills/builtin/drawio/scripts/rustimports.py` | 210 | — |
| `skills/builtin/drawio/scripts/seqlayout.py` | 235 | — |
| `skills/builtin/drawio/scripts/shapesearch.py` | 173 | — |
| `skills/builtin/drawio/scripts/sqlerd.py` | 179 | — |
| `skills/builtin/drawio/scripts/svgflow.py` | 86 | — |
| `skills/builtin/drawio/scripts/tfimports.py` | 287 | — |
| `skills/builtin/drawio/scripts/tfstate.py` | 150 | — |
| `skills/builtin/drawio/scripts/timelapse.py` | 286 | — |
| `skills/builtin/drawio/scripts/tubemap.py` | 181 | — |
| `skills/builtin/drawio/scripts/validate.py` | 356 | — |
| `skills/builtin/mcp-builder/scripts/connections.py` | 151 | — |
| `skills/builtin/mcp-builder/scripts/evaluation.py` | 407 | asyncio |
| `skills/builtin/office/scripts/accept_changes.py` | 131 | — |
| `skills/builtin/office/scripts/add_slide.py` | 377 | — |
| `skills/builtin/office/scripts/clean.py` | 302 | — |
| `skills/builtin/office/scripts/comment.py` | 411 | — |
| `skills/builtin/office/scripts/merge_runs.py` | 303 | — |
| `skills/builtin/office/scripts/office/helpers/pptx_chart.py` | 188 | — |
| `skills/builtin/office/scripts/office/helpers/pptx_slide.py` | 59 | — |
| `skills/builtin/office/scripts/office/helpers/pptx_theme.py` | 110 | — |
| `skills/builtin/office/scripts/office/soffice.py` | 190 | — |
| `skills/builtin/office/scripts/office/validate.py` | 172 | — |
| `skills/builtin/office/scripts/office/validators/base.py` | 824 | — |
| `skills/builtin/office/scripts/office/validators/docx.py` | 444 | — |
| `skills/builtin/office/scripts/office/validators/pptx.py` | 428 | — |
| `skills/builtin/office/scripts/office/validators/redlining.py` | 287 | — |
| `skills/builtin/office/scripts/recalc.py` | 301 | — |
| `skills/builtin/office/scripts/thumbnail.py` | 306 | — |
| `skills/builtin/pdf/scripts/check_bounding_boxes.py` | 74 | — |
| `skills/builtin/pdf/scripts/check_fillable_fields.py` | 13 | — |
| `skills/builtin/pdf/scripts/convert_pdf_to_images.py` | 33 | — |
| `skills/builtin/pdf/scripts/create_validation_image.py` | 39 | — |
| `skills/builtin/pdf/scripts/extract_form_field_info.py` | 130 | — |
| `skills/builtin/pdf/scripts/extract_form_structure.py` | 116 | — |
| `skills/builtin/pdf/scripts/fill_fillable_fields.py` | 103 | — |
| `skills/builtin/pdf/scripts/fill_pdf_form_with_annotations.py` | 108 | — |
| `skills/builtin/skill-creator/scripts/init_skill.py` | 383 | — |
| `skills/builtin/skill-creator/scripts/package_skill.py` | 135 | — |
| `skills/builtin/skill-creator/scripts/quick_validate.py` | 204 | pyyaml |
| `skills/registry.py` | 320 | pathspec |
| `skills/workspace_sync.py` | 240 | — |
| `subagents/_research_timeouts.py` | 32 | tavily |
| `subagents/academic_research/effort.py` | 108 | pydantic |
| `subagents/academic_research/events.py` | 118 | pydantic |
| `subagents/academic_research/protocol.py` | 97 | pydantic |
| `subagents/academic_research/sources/academic_search.py` | 178 | deepxiv-sdk, tarzi |
| `subagents/browser_use/action_format.py` | 122 | browser-use |
| `subagents/browser_use/config_model.py` | 50 | browser-use, pydantic |
| `subagents/browser_use/display_summary.py` | 18 | browser-use |
| `subagents/browser_use/events.py` | 80 | browser-use, pydantic |
| `subagents/computer_use/_preview.py` | 16 | browser-use |
| `subagents/computer_use/config_model.py` | 84 | pyautogui, pydantic |
| `subagents/computer_use/events.py` | 80 | pydantic |
| `subagents/deep_research/effort.py` | 108 | pydantic |
| `subagents/deep_research/events.py` | 112 | pydantic |
| `subagents/deep_research/protocol.py` | 92 | pydantic |
| `toolkits/_internal/tabular.py` | 164 | pandas |
| `toolkits/_internal/wizsearch.py` | 786 | asyncio, tavily |
| `toolkits/url_crawl/crawler.py` | 118 | asyncio, pydantic |
| `toolkits/url_crawl/polite_http.py` | 447 | asyncio, deepxiv-sdk, tarzi, tavily |
| `utils/runtime.py` | 260 | browser-use |
| `utils/serde.py` | 61 | langgraph-checkpoint |

---

## Methodology

Each of the 333 non-`__init__.py` Python source files in `src/soothe_nano/` was analyzed:

1. **Line count** — `wc -l` per file
2. **Import analysis** — `grep` for `langchain`, `langgraph`, `from langchain_core`, `from pydantic`, `litellm`, `psycopg`, `langfuse`, `tiktoken`, `browser_use`, `pyautogui`, `tarzi`, `deepxiv`, `tavily`, `sqlite_vec`, `weaviate`, `pandas`, `import fitz`, `jsonschema`, `pathspec`, `wcmatch`, `aiofiles`, `import yaml`, `import requests`, `quickjs`, `checkpointer`, `import asyncio`, `from mcp`, `from soothe_deepagents`, `deepagents`, `_rust_compat`
3. **Existing Rust migration** — files already importing from `soothe_nano._rust` via `_rust_compat`
4. **Crate mapping** — cross-referenced with the 14 existing Cargo crates under `crates/`
5. **Categorization** — three-way classification:
   - **Rust-migratable:** Pure logic using only Python stdlib, or already partially migrated via `_rust_compat`
   - **LangChain-dependent:** Imports from `langchain*`, `langgraph*`, or `soothe_deepagents` — blocked on ecosystem migration
   - **Python-only:** Depends on Python-ecosystem libraries with no Rust equivalent (psycopg, langfuse, browser-use, pyautogui, pandas, PyMuPDF) or defines Pydantic models, exception hierarchies, or Protocol interfaces

### Limitations

- Import analysis is pattern-based; transitive dependencies may cause misclassification
- Effort estimates are based on line count and dependency complexity — actual effort depends on logic complexity, test coverage, and API surface
- Priority ranking assumes the existing crate structure is the migration target; a different Rust architecture would change priorities
- Files using `asyncio` are conservatively classified as Python-only (async runtime migration requires a tokio/async-std bridge)
- Skills builtin scripts (drawio, office, pdf, mcp-builder, skill-creator) are classified as Python-only regardless of imports — they are user-extensible tooling scripts