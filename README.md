# soothe-nano

[![PyPI version](https://img.shields.io/pypi/v/soothe-nano.svg?label=PyPI&color=blue)](https://pypi.org/project/soothe-nano/)
[![Python](https://img.shields.io/pypi/pyversions/soothe-nano.svg?label=Python)](https://pypi.org/project/soothe-nano/)

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
soothe-nano         SootheNanoAgent + toolkits + subagents + MCP
                    + shared contracts (protocols, events, plugin API)
```

```text
create_nano_agent(config)
        │
        ├─ model + middleware stack
        ├─ tools (builtin groups + yours)
        ├─ subagents (planner, research, browser, computer_use, …)
        ├─ skills (progressive discovery)
        └─ MCP (on-demand activation)
```

## Features

| Area | What nano provides |
|---|---|
| Tools | Builtin groups: shell, file ops, HTTP, search, data, image, datetime |
| Subagents | Ready: plan, deep/academic research, browser_use, computer_use |
| Skills / tools in context | Progressive loading — activate what the turn needs |
| Workspace | Scoped workspace + security defaults |
| Config | YAML / `SootheConfig` factory |
| Memory | Optional long-term memory via protocols |
| MCP | Registry and on-demand adapters |
| Plugins | Decorator API (`@plugin`, `@tool`, `@tool_group`, `@subagent`) with discovery, registry, and lifecycle |
| Observability | Langfuse tracing hooks, event registry, verbosity tiers |
| Resilience | `PersistentRetryRunner` for 429/529/transient errors with exponential backoff + model fallback |

## vs deepagents

| | deepagents | soothe-nano |
|---|---|---|
| What you get | Opinionated harness | Harness **plus** coding product defaults |
| Tools | Bring your own | Builtin groups out of the box |
| Subagents | You define them | Ready plan / research / browser / computer_use |
| Skills / tools in context | Base support | Progressive loading |
| Workspace | Pluggable backends | Scoped workspace + security defaults |
| Config | Code-first | YAML / `SootheConfig` factory |
| Plugin authoring | — | Decorator API + discovery + registry |
| Shared contracts | — | Protocols, events, plugin API (self-contained since 1.4) |

Use **deepagents** when you want a minimal harness and full control.  
Use **nano** when you want a coding agent that already knows how to work in a repo.

## When to use nano

| Scenario | Fit |
|---|---|
| Coding assistant in a repo | ✅ Files, shell, plan out of the box |
| Research / browsing agent | ✅ Deep research, academic, browser_use subagents |
| Desktop GUI automation | ✅ computer_use subagent (screenshots, clicks, keyboard) |
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

For interactive + background execution in one runtime, use the dual-mode factory:

```python
from soothe_nano import create_dual_mode_nano_agent, InteractionMode
from soothe_nano.config import SootheConfig

agent = create_dual_mode_nano_agent(SootheConfig(), mode=InteractionMode.INTERACTIVE)
```

## Examples

Library examples live in `examples/`:

1. `01_pure_nano_example.py` — Pure model (no tools)
2. `02_nano_with_tools_example.py` — With tools
3. `03_nano_with_memory_example.py` — With memory
4. `04_nano_with_subagents_example.py` — With subagents
5. `05_nano_full_composition_example.py` — Full composition
6. `06_nano_computer_use_example.py` — Desktop GUI automation
7. `07_nano_computer_use_weixin_favorites.py` — WeChat favorites harvesting

LLM provider examples in `examples/llm/` (OpenAI, Gemini, OpenRouter, Anthropic, Ollama, DashScope/custom OpenAI-compatible endpoints, structured output, multi-provider factory):

```bash
python examples/01_pure_nano_example.py
```

## Plugin authoring

```python
from soothe_nano.plugin import plugin, tool, subagent

@plugin("my-toolkit")
class MyToolkit:
    @tool
    def do_thing(self, x: str) -> str:
        """Do a thing."""
        return f"did: {x}"
```

Plugins are discovered from entry points, config, or the filesystem and loaded with dependency resolution via the `PluginLifecycleManager`.
