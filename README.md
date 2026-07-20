# soothe-nano

A **ready-to-run coding agent** you can drop into a script or app.

Built on [soothe-deepagents](https://github.com/mirasoth/soothe-deepagents) (filesystem, shell, subagents, skills, MCP). Nano adds the pieces you usually wire yourself: workspace safety, progressive tools/skills, research & explore subagents, and a config-driven factory.

No StrangeLoop, Autopilot, or daemon — just the agent.

## Vision

Give builders a production-shaped coding CoreAgent without standing up the full Soothe host.

- **Start small** — chat, tools, or full composition in a few lines
- **Stay portable** — embed in notebooks, CLIs, or your own service
- **Grow later** — same agent surface powers the full `soothe` stack when you need planning loops and 24/7 autonomy

## Architecture

```
soothe-deepagents   agent harness (FS, shell, memory, skills base)
        ↓
soothe-sdk          shared contracts (protocols, events)
        ↓
soothe-nano         coding CoreAgent + toolkits + subagents + MCP
        ↓
soothe (optional)   StrangeLoop / Autopilot / Context Engine / runner
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

## vs deepagents

| | deepagents | soothe-nano |
|---|---|---|
| What you get | Opinionated harness | Harness **plus** coding product defaults |
| Tools | Bring your own | Builtin groups: shell, file ops, HTTP, search, data, … |
| Subagents | You define them | Ready: explore, plan, deep/academic research, browser |
| Skills / tools in context | Base support | Progressive loading — activate what the turn needs |
| Workspace | Pluggable backends | Scoped workspace + security defaults |
| Config | Code-first | YAML/`SootheConfig` factory |
| Host loop | — | Not included (use full `soothe` for that) |

Use **deepagents** when you want a minimal harness and full control.  
Use **nano** when you want a coding agent that already knows how to work in a repo.

## When to use nano

| Scenario | Fit |
|---|---|
| Coding assistant in a repo | ✅ Files, shell, explore/plan out of the box |
| Research / browsing agent | ✅ Deep research, academic, browser subagents |
| Embed in your product | ✅ Library API, no daemon required |
| Plugin / toolkit author | ✅ Depends on nano, not full `soothe` |
| Simple Q&A chat | ✅ Strip tools/subagents as needed |
| Multi-goal 24/7 autonomy | → Full `soothe` (StrangeLoop + Autopilot) |

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

Examples live in `examples/nano_agent/`:

1. Pure model (no tools)
2. With tools
3. With memory
4. With subagents
5. Full composition

```bash
python packages/soothe-nano/examples/nano_agent/01_pure_nano_example.py
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

## In the Soothe family

| Package | Role |
|---|---|
| `soothe-nano` | Coding CoreAgent (this package) |
| `soothe` | Host: StrangeLoop, Autopilot, runner |
| `soothe-daemon` / `soothe-cli` | Long-running server + TUI |
| `soothe-plugins` | Community plugins on nano |
