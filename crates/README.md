# soothe-nano Rust Crates

Rust workspace for nano's compute-heavy, I/O-bound, and security-critical
layers. The agent loop, LangChain/LangGraph/DeepAgents integration, litellm
provider, MCP transport, and middleware stay Python — Rust accelerates the
hot paths the loop calls into.

## Layout

```
crates/
├── Cargo.toml                         # workspace manifest
│
│   ── Leaf crates (no internal deps) ──
│
├── soothe-nano-utils/                 # circuit breaker, thread ID, JSON
│   │                                    repair, text preview, URL validation
│   └── (depends on: serde, regex, uuid)
│
├── soothe-nano-events/                # event type definitions (serde structs)
│   └── (depends on: serde)
│
├── soothe-nano-tokens/                # tiktoken-rs wrapper, token counting
│   └── (depends on: tiktoken-rs, dashmap)
│
│   ── Mid-level crates ──
│
├── soothe-nano-workspace/             # path resolution, workspace isolation
│   └── (depends on: utils)
│
├── soothe-nano-config/                # config models, env expansion, YAML
│   └── (depends on: events)
│
├── soothe-nano-security/              # path validation, policy, rate limiting
│   └── (depends on: workspace, utils)
│
├── soothe-nano-prompts/               # system prompt templates, context XML
│   └── (depends on: config)
│
│   ── I/O crates ──
│
├── soothe-nano-persist/               # SQLite runtime, persist stores, durability
│   └── (depends on: config, utils)
│
├── soothe-nano-filesystem/            # local fs ops: read/write/edit/grep/glob
│   └── (depends on: security, workspace, utils)
│
├── soothe-nano-skills/                # skill discovery, corpus matching, budget
│   └── (depends on: tokens, filesystem, utils)
│
│   ── PyO3 bridge ──
│
└── soothe-nano-sys/                   # PyO3 extension module (.so/.pyd)
    └── (depends on: ALL crates + pyo3)
```

## Dependency Graph

```
                    soothe-nano-sys  (PyO3 — the only crate with pyo3)
                   /    |    |    |    \      \       \        \        \
                  /     |    |    |     \      \       \        \        \
          security  persist  fs  config  tokens  prompts  events  utils  skills
           /  \      /  \    /|\   |
      workspace utils config  security  events
          |        |    |    /|\  workspace  utils
         utils    utils    utils  utils
```

## Key Design Rule

**Only `soothe-nano-sys` depends on `pyo3`.** All other crates are pure Rust
libraries — testable in isolation, reusable outside Python, and free of GIL
concerns. The Rust core is a standalone library that *happens* to also be
exposed via PyO3.

## Building

```bash
# From the project root:
cd crates && cargo test          # run all Rust unit tests
cd crates && cargo build         # build all crates (no Python needed)
cd crates && cargo build --release  # optimized build
```

The PyO3 extension module is built by maturin from the project root:

```bash
maturin develop --manifest-path crates/Cargo.toml
# produces: src/soothe_nano/_rust.cpython-311-darwin.so
```

## Python Import

```python
from soothe_nano._rust import (
    PathValidator, LocalFilesystem, TokenCounter,
    SqliteStoreRuntime, SkillDiscovery, ...
)
```

## Crate → Python Module Mapping

| Rust crate | Ports from |
|---|---|
| `soothe-nano-utils` | `utils/{circuit_breaker,thread_id,json_parsing,path,output_capture,text_preview,url_validation}.py` |
| `soothe-nano-events` | `events/catalog.py` |
| `soothe-nano-tokens` | `utils/token_counting.py` |
| `soothe-nano-workspace` | `workspace/{workspace_api,workspace_paths,workspace_policy,workspace_runtime}.py`, `paths/sqlite_paths.py` |
| `soothe-nano-config` | `config/{models,settings,env,constants}.py` |
| `soothe-nano-security` | `security/{path_security,policy_models,policy_profiles,security_enforcer,operation_guard}.py` |
| `soothe-nano-prompts` | `prompts/{system_templates,context_xml,identity,project_instructions}.py` |
| `soothe-nano-persist` | `persistence/sqlite_runtime.py`, `backends/persistence/{sqlite_store,postgres_store}.py`, `backends/durability/` |
| `soothe-nano-filesystem` | `filesystem/local.py`, `toolkits/file_ops.py`, `toolkits/file_ops_catalog.py` |
| `soothe-nano-skills` | `skills/{discovery_tools,corpus_match,budget,search}.py` |
| `soothe-nano-sys` | (PyO3 bridge — no Python counterpart) |
