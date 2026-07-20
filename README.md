# soothe-nano

A **ready-to-run coding agent** you can drop into a script or app.

Built on [soothe-deepagents](https://github.com/mirasoth/soothe-deepagents) (filesystem, shell, subagents, skills, MCP). Nano adds the pieces you usually wire yourself: workspace safety, progressive tools/skills, research & explore subagents, and a config-driven factory.

## Vision

Give builders a production-shaped coding CoreAgent in a few lines of Python.

- **Start small** — chat, tools, or full composition
- **Stay portable** — embed in notebooks, CLIs, or your own service
- **Compose what you need** — tools, memory, subagents, skills, and MCP via config

## Architecture

```
soothe-deepagents   agent harness (FS, shell, memory, skills base)
        ↓
soothe-sdk          shared contracts (protocols, events)
        ↓
soothe-nano         coding CoreAgent + toolkits + subagents + MCP
```

```text
create_nano_agent(config)
        │
        ├─ model + middleware stack
        ├─ tools (builtin groups + yours)
        ├─ subagents (explorer, planner, research, browser, …)
        ├─ skills (progressive discovery)
        └─ MCP (on-demand activation)
```

## Features

| Area | What nano provides |
|---|---|
| Tools | Builtin groups: shell, file ops, HTTP, search, data, … |
| Subagents | Ready: explore, plan, deep/academic research, browser |
| Skills / tools in context | Progressive loading — activate what the turn needs |
| Workspace | Scoped workspace + security defaults |
| Config | YAML / `SootheConfig` factory |
| Memory | Optional long-term memory via protocols |
| MCP | Registry and on-demand adapters |

## vs deepagents

| | deepagents | soothe-nano |
|---|---|---|
| What you get | Opinionated harness | Harness **plus** coding product defaults |
| Tools | Bring your own | Builtin groups out of the box |
| Subagents | You define them | Ready explore / plan / research / browser |
| Skills / tools in context | Base support | Progressive loading |
| Workspace | Pluggable backends | Scoped workspace + security defaults |
| Config | Code-first | YAML / `SootheConfig` factory |

Use **deepagents** when you want a minimal harness and full control.  
Use **nano** when you want a coding agent that already knows how to work in a repo.

## When to use nano

| Scenario | Fit |
|---|---|
| Coding assistant in a repo | ✅ Files, shell, explore/plan out of the box |
| Research / browsing agent | ✅ Deep research, academic, browser subagents |
| Embed in your product | ✅ Library API, no daemon required |
| Plugin / toolkit author | ✅ Depends on nano only |
| Simple Q&A chat | ✅ Strip tools/subagents as needed |

## Install

```bash
uv add soothe-nano
```

## Quick start

```python
from soothe_nano import create_nano_agent
from soothe_nano.config import SootheConfig

agent = create_nano_agent(SootheConfig())
# agent.ainvoke / streaming — see examples/
```

Examples live in `examples/`:

1. Pure model (no tools)
2. With tools
3. With memory
4. With subagents
5. Full composition

```bash
python packages/soothe-nano/examples/01_pure_nano_example.py
```

## Package layout

```
soothe_nano/
  agent/       CodingCoreAgent, create_nano_agent
  config/      SootheConfig
  toolkits/    Builtin tool groups
  subagents/   explore, plan, research, browser, …
  middleware/  Progressive tools/skills, workspace, policy
  skills/      Catalog + progressive search
  mcp/         MCP registry / adapters
  backends/    Persistence helpers
```

## Development

From `packages/soothe-nano/`:

```bash
make help              # list targets
make sync-dev          # sync deps
make format lint       # format + lint
make test-unit         # unit tests
make test-integration  # integration tests (--run-integration)
make examples          # run examples
make build             # build dist/
```
