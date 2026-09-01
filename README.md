# soothe-nano

[![PyPI version](https://img.shields.io/pypi/v/soothe-nano.svg?label=PyPI&color=blue)](https://pypi.org/project/soothe-nano/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mirasoth/soothe-nano)

A **ready-to-run coding agent** you can drop into a script, CLI, or app.

Built on [soothe-deepagents](https://github.com/mirasoth/soothe-deepagents) (filesystem, shell, subagents, skills, MCP). Nano adds the pieces you usually wire yourself: workspace safety, progressive tools/skills, research subagents, and a config-driven factory.

## Vision

Give builders a production-shaped `SootheNanoAgent` in a few lines of Python.

- **Start small** — chat, tools, or full composition
- **Stay portable** — embed in notebooks, CLIs, or your own service
- **Compose what you need** — tools, memory, subagents, skills, and MCP via config

## Architecture

```
soothe-deepagents   agent harness (FS, shell, memory, skills base)
        ↓
soothe-sdk          shared contracts (protocols, events)
        ↓
soothe-nano         SootheNanoAgent + toolkits + subagents + MCP
```

```text
create_nano_agent(config)
        │
        ├─ model + middleware stack
        ├─ tools (builtin groups + yours)
        ├─ subagents (planner, research, browser, …)
        ├─ skills (progressive discovery)
        └─ MCP (on-demand activation)
```

## Features

| Area | What nano provides |
|---|---|
| Tools | Builtin groups: shell, file ops, HTTP, search, data, image, … |
| Subagents | Ready: plan, deep/academic research, browser |
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
| Subagents | You define them | Ready plan / research / browser |
| Skills / tools in context | Base support | Progressive loading |
| Workspace | Pluggable backends | Scoped workspace + security defaults |
| Config | Code-first | YAML / `SootheConfig` factory |

Use **deepagents** when you want a minimal harness and full control.  
Use **nano** when you want a coding agent that already knows how to work in a repo.

## When to use nano

| Scenario | Fit |
|---|---|
| Coding assistant in a repo | ✅ Files, shell, plan out of the box |
| Research / browsing agent | ✅ Deep research, academic, browser subagents |
| Embed in your product | ✅ Library API, no daemon required |
| One-shot / headless CLI | ✅ See [fj-ai](https://github.com/caesar0301/fj-ai) |
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

Library examples live in `examples/`:

1. Pure model (no tools)
2. With tools
3. With memory
4. With subagents
5. Full composition

```bash
python packages/soothe-nano/examples/01_pure_nano_example.py
```

## Productive CLI (reference: fj-ai)

[fj-ai](https://github.com/caesar0301/fj-ai) is a production one-shot coding CLI built only on **soothe-nano** (no soothe daemon). Use it as the integration blueprint:

```bash
pip install fj-ai   # or: uv tool install fj-ai
fj explain this repo
fj -f what did we decide last time?
```

### Integration pattern

A headless CLI typically does four things on top of nano:

1. **Load config** — `~/.soothe/config/nano.yml`, or zero-config from `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
2. **Force SQLite** for standalone runs (threads survive across process exits)
3. **Build the agent** with `create_nano_agent`, pin workspace, attach a checkpointer
4. **Stream** `agent.astream(...)` and **close** the `aiosqlite` connection on exit

Minimal sketch (same shape as [fj_ai/agent.py](https://github.com/caesar0301/fj-ai/blob/main/src/fj_ai/agent.py)):

```python
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from soothe_nano import SootheNanoAgent, create_nano_agent
from soothe_nano.config import SOOTHE_HOME, SootheConfig
from soothe_nano.resolve import resolve_checkpointer


def load_config(path: Path | None = None) -> SootheConfig:
    cfg = path or (SOOTHE_HOME / "config" / "nano.yml")
    if cfg.is_file():
        return SootheConfig.from_yaml_file(str(cfg))
    return SootheConfig()  # OPENAI_API_KEY / ANTHROPIC_API_KEY


def apply_cli_defaults(config: SootheConfig) -> SootheConfig:
    durability = config.agent.protocols.durability.model_copy(
        update={"backend": "sqlite", "checkpointer": "sqlite"}
    )
    protocols = config.agent.protocols.model_copy(update={"durability": durability})
    agent = config.agent.model_copy(update={"protocols": protocols})
    persistence = config.persistence.model_copy(update={"default_backend": "sqlite"})
    return config.model_copy(update={"agent": agent, "persistence": persistence})


@asynccontextmanager
async def open_sqlite_checkpointer(config: SootheConfig) -> AsyncIterator[Any | None]:
    result = resolve_checkpointer(apply_cli_defaults(config))
    db_path = result[1] if isinstance(result, tuple) and isinstance(result[1], str) else None
    if not db_path:
        yield None
        return

    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from soothe_sdk.utils.serde import create_soothe_serde

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    checkpointer = AsyncSqliteSaver(conn, serde=create_soothe_serde())
    await checkpointer.setup()
    try:
        yield checkpointer
    finally:
        await conn.close()  # required — aiosqlite uses a non-daemon thread


async def build_agent(
    config: SootheConfig,
    *,
    checkpointer: Any | None = None,
) -> SootheNanoAgent:
    agent = create_nano_agent(apply_cli_defaults(config))
    if checkpointer is not None:
        agent.graph.checkpointer = checkpointer
    return agent


async def run_once(query: str, *, thread_id: str) -> None:
    config = load_config()
    async with open_sqlite_checkpointer(config) as checkpointer:
        agent = await build_agent(config, checkpointer=checkpointer)
        async for chunk in agent.astream(
            query,
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates", "custom"],
        ):
            # render tokens / tool progress to stdout (see fj_ai/stream.py)
            _ = chunk


if __name__ == "__main__":
    asyncio.run(run_once("summarize this repo", thread_id="cli-demo"))
```

### What fj adds on top of nano

| Concern | fj-ai approach |
|---|---|
| UX | One-shot `fj <query…>`; `-f` / `-t` resume threads; `-l` list |
| Persistence | SQLite checkpointer under `$SOOTHE_DATA_DIR` |
| Skills | Package `builtin/` via `register_builtin_skill_root` |
| Workspace | `SOOTHE_WORKSPACE` / cwd for file + shell tools |
| Streaming | Quiet progress line + full final answer (`stream.py`) |
| Setup | `fj setup` writes `~/.soothe/config/nano.yml` |

For a full TUI / StrangeLoop host on the same stack, see [mirasoth/soothe](https://github.com/mirasoth/soothe). For the slim CLI product, clone [caesar0301/fj-ai](https://github.com/caesar0301/fj-ai).

## Development

From `packages/soothe-nano/`:

```bash
make help              # list targets
make sync             # sync dev deps
make format lint       # format + lint
make test-unit         # unit tests
make test-integration  # integration tests (--run-integration)
make examples          # run examples
make build             # build dist/
```
