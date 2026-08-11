# `computer_use` Subagent — CLI Usage Guide

> **How to drive desktop GUIs from a soothe-nano CLI / one-shot script.**
> This guide is the operator-facing companion to the
> [Implementation Guide](./computer_use_implementation_guide.md). It covers
> system requirements, config setup, invocation patterns, and ready-to-paste
> example prompts for the `computer_use` subagent.

## Table of Contents

1. [What It Does](#what-it-does)
2. [System Requirements](#system-requirements)
   - [Python Dependencies](#python-dependencies)
   - [macOS Permissions](#macos-permissions)
   - [Linux Display Server](#linux-display-server)
   - [Windows](#windows)
   - [Retina / HiDPI Displays](#retina--hidpi-displays)
3. [Config Setup](#config-setup)
   - [Zero-Config (Env Vars)](#zero-config-env-vars)
   - [YAML Config File](#yaml-config-file)
   - [Full Field Reference](#full-field-reference)
   - [Model Selection](#model-selection)
4. [CLI Invocation Patterns](#cli-invocation-patterns)
   - [One-Shot CLI (reference: fj-ai)](#one-shot-cli-reference-fj-ai)
   - [Minimal Python Script](#minimal-python-script)
   - [Streaming Wire Events](#streaming-wire-events)
5. [Example Prompts](#example-prompts)
   - [Desktop App Control](#desktop-app-control)
   - [Information Retrieval](#information-retrieval)
   - [Multi-Step Workflows](#multi-step-workflows)
6. [How Delegation Works](#how-delegation-works)
7. [Observability & Logs](#observability--logs)
8. [Troubleshooting](#troubleshooting)
9. [Known Limitations](#known-limitations)

---

## What It Does

The `computer_use` subagent is a **desktop automation specialist** that drives a
GUI through a vision-capable LLM agentic loop:

```
screenshot → reason → act (click / type / key / scroll) → repeat → done
```

It is **enabled by default** in every `SootheConfig` (auto-registered via the
`_merge_subagents` validator in `config/settings.py`). You do not need to opt in
in YAML — only tune or disable it.

**Module location:** `src/soothe_nano/subagents/computer_use/`

| File | Role |
|---|---|
| `__init__.py` | `@plugin` + `@subagent` registration, `on_load` dependency gate |
| `implementation.py` | LangGraph agent loop, `_PyAutoGUIBackend`, synthesis |
| `tools.py` | LangChain `BaseTool` schemas + `_DesktopInputBackend` protocol |
| `config_model.py` | `ComputerUseSubagentConfig` (Pydantic) |
| `events.py` | 3 wire event types (`started` / `step.completed` / `completed`) |
| `action_format.py` | Human-readable step labels for the TUI/CLI |
| `display_summary.py` | Completion-card summary helper |

---

## System Requirements

The subagent captures screenshots and injects mouse/keyboard input via
**pyautogui**, which requires (a) the pyautogui Python package and (b) a running
display server with the right OS-level permissions.

### Python Dependencies

`pyautogui` is **not** declared in `pyproject.toml` yet — install it manually:

```bash
pip install pyautogui
# pyautogui pulls in: Pillow, pygetwindow (Windows), mouseinfo, pymsgbox,
# pytweening, and pyobjc-core/pyobjc-framework (macOS) as needed.
```

The plugin's `on_load()` method performs a soft dependency check. If
`import pyautogui` fails, it raises:

```
PluginError: pyautogui library not installed. Install with: pip install -U soothe-nano
```

> **Note:** The `on_load` message points to `pip install -U soothe-nano` because
> the eventual fix is to add pyautogui to `pyproject.toml` (see
> [Known Limitations](#known-limitations)). For now, install it directly.

### macOS Permissions

macOS ships with WindowServer — no display-server setup is needed — **but** you
must grant two permissions or pyautogui silently no-ops:

1. **System Settings → Privacy & Security → Accessibility**
   - Add the terminal/IDE that runs soothe-nano (Terminal, iTerm2, VS Code, …).
   - Toggle ON. Without this, `click()`, `typewrite()`, and `hotkey()` silently fail.

2. **System Settings → Privacy & Security → Screen Recording**
   - Add the same application and toggle ON.
   - Restart the app if prompted. Without this, `screenshot()` returns a blank
     or permission-denied image.

Verify quickly:

```bash
python -c "import pyautogui; pyautogui.click(100, 100); print('ok')"
```

### Linux Display Server

**Local desktop session (X11):** pyautogui works out of the box.

```bash
# Debian/Ubuntu — screenshot backend + Tk bindings
sudo apt install python3-tk python3-dev scrot
# Wayland alternative: grim slurp
```

Ensure `DISPLAY` (X11) or `WAYLAND_DISPLAY` (Wayland) is set in the session
that launches the agent. Absence of these env vars is the most common root cause
of blank-screenshot / input-failure issues on Linux — the `run_start` log line
now records `display_server` and `display_env` for triage (see
[Observability](#observability--logs)).

**Headless server / VPS:** pyautogui needs a virtual framebuffer:

```bash
sudo apt install xvfb
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
# Launch your target app in the same session, e.g. firefox &
```

### Windows

pyautogui works natively on Windows 10/11 — no display server configuration.

```powershell
pip install pyautogui
# Pillow and pygetwindow install as dependencies.
```

For multi-monitor setups, `region` coordinates are relative to the primary
monitor's top-left corner `(0, 0)`.

### Retina / HiDPI Displays

On Retina/HiDPI screens, pyautogui's `screenshot()` returns a
**physical-resolution** image (e.g. 2×), while `click()` / `moveTo()` consume
**logical** (1×) coordinates. The vision LLM reasons over the screenshot's
physical pixel space, so its chosen coordinates must be divided by the scale
factor before being handed to pyautogui.

Set `coordinate_scale: 2` in config (see [Config Setup](#config-setup)) to enable
this rescaling. The backend's `_rescale_coord()` helper performs the division;
with scale `1` it is a no-op. The `click` / `scroll` results report both the
LLM-space coords (`x`, `y`) and the resolved input coords (`input_x`, `input_y`)
plus `scale` for auditability.

---

## Config Setup

The subagent is auto-enabled; you only need to **tune** it. Configuration is
layered: zero-config from env vars → YAML file → programmatic overrides.

### Zero-Config (Env Vars)

The simplest path — no YAML required. Set a provider API key and go:

```bash
export OPENAI_API_KEY="sk-..."
# or:
export ANTHROPIC_API_KEY="sk-ant-..."
```

`SootheConfig()` with no arguments falls back to these env vars, and the
`computer_use` subagent is already enabled by default. For desktop automation
you still need a **vision-capable model** (see [Model Selection](#model-selection)).

### YAML Config File

For anything beyond defaults, write `~/.soothe/config/nano.yml`
(or any path you pass to `SootheConfig.from_yaml_file()`):

```yaml
# ~/.soothe/config/nano.yml
providers:
  - name: openai
    api_base: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    models:
      - name: gpt-4.1
        roles: [vision, default]

subagents:
  computer_use:
    enabled: true
    model_role: vision        # use the vision-capable model for action decisions
    config:
      max_steps: 20
      input_mode: pyautogui
      coordinate_scale: 2     # Retina/HiDPI displays
      action_delay_s: 0.8
      screenshot_format: jpeg
      screenshot_quality: 85
      screenshot_interval_s: 0.0
      cleanup_on_exit: true
      synthesis_role: default
      synthesis_timeout_sec: 45
```

To **disable** the subagent entirely:

```yaml
subagents:
  computer_use:
    enabled: false
```

### Full Field Reference

`ComputerUseSubagentConfig` (`src/soothe_nano/subagents/computer_use/config_model.py`)
defines every tunable knob. All fields live under
`subagents.computer_use.config.*` in YAML.

| Field | Type | Default | Description |
|---|---|---|---|
| `max_steps` | `int` | `10` | Maximum desktop automation steps per delegated task. |
| `runtime_dir` | `str` | `""` | Base directory for desktop runtime files. Empty = auto-resolved under `SOOTHE_HOME`. |
| `screenshots_dir` | `str` | `""` | Directory for captured screenshots. Empty = `<runtime_dir>/screenshots`. |
| `cleanup_on_exit` | `bool` | `True` | Remove temporary screenshots when the session ends. |
| `screenshot_interval_s` | `float` | `0.0` | Seconds between automatic periodic screenshots. `0` = disabled (action-driven only). Range `0.0`–`30.0`. |
| `screenshot_quality` | `int` | `85` | JPEG quality (1–100) when `screenshot_format` is `jpeg`. |
| `screenshot_format` | `Literal["png","jpeg"]` | `"png"` | Screenshot image format. |
| `input_mode` | `Literal["auto","pyautogui","osascript"]` | `"auto"` | Desktop input backend. `auto`/`pyautogui` → `_PyAutoGUIBackend`. `osascript` not yet implemented. |
| `coordinate_scale` | `int` | `1` | Coordinate scale factor (`1` = 1×, `2` = Retina). Range `1`–`4`. |
| `action_delay_s` | `float` | `0.5` | Delay after each input action for the UI to settle. Range `0.0`–`10.0`. |
| `synthesis_role` | `str` | `"default"` | Router role for post-run result synthesis / quality gate. |
| `synthesis_timeout_sec` | `float` | `30.0` | Timeout budget for the synthesis LLM call. Range `5.0`–`120.0`. |

> **Quality / interval wiring:** `screenshot_quality` and `screenshot_interval_s`
> are validated by Pydantic and flow from `ComputerUseSubagentConfig` into the
> capture loop / backend initialization (the `run_start` log line echoes them
> so you can confirm the active values per run). Screenshots are saved as valid
> image files in the chosen format, ready to be encoded for vision models.

### Model Selection

The subagent resolves its LLM via the soothe-nano router — it does **not**
accept a `model` kwarg. Flow:

1. `subagents.computer_use.model_role` (default `"default"`).
2. `soothe_config.resolve_model(role)` → `"provider:model"` spec.
3. `_resolve_computer_llm_credentials()` splits the spec and pulls
   `base_url` / `api_key` from the `ProviderRegistry`.
4. Model is instantiated as `ChatOpenAI(model=..., base_url=..., api_key=...)`.

> **Important:** The action-decision LLM must be **vision-capable** (e.g.
> `gpt-4o`, `gpt-4.1`, `qwen-vl-max`) because the agent interprets pixel
> coordinates from screen captures. Pin a vision model to a role and point
> `model_role` at it:

```yaml
providers:
  - name: openai
    models:
      - name: gpt-4.1
        roles: [vision, default]

subagents:
  computer_use:
    model_role: vision
```

---

## CLI Invocation Patterns

soothe-nano is a library, not a packaged CLI binary — so "CLI usage" means a
thin one-shot script built on `create_nano_agent`. The reference production CLI
is [fj-ai](https://github.com/caesar0301/fj-ai); the patterns below mirror its
shape.

### One-Shot CLI (reference: fj-ai)

A headless CLI built on nano typically does four things:

1. **Load config** — `~/.soothe/config/nano.yml`, or zero-config from env vars.
2. **Force SQLite** persistence (threads survive across process exits).
3. **Build the agent** with `create_nano_agent`, pin workspace, attach a checkpointer.
4. **Stream** `agent.astream(...)` and **close** the `aiosqlite` connection on exit.

Minimal sketch (adapted from
[fj_ai/agent.py](https://github.com/caesar0301/fj-ai/blob/main/src/fj_ai/agent.py)):

```python
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from soothe_nano import create_nano_agent
from soothe_nano.config import SOOTHE_HOME, SootheConfig
from soothe_nano.resolve import resolve_checkpointer


def load_config(path: Path | None = None) -> SootheConfig:
    cfg = path or (SOOTHE_HOME / "config" / "nano.yml")
    if cfg.is_file():
        return SootheConfig.from_yaml_file(str(cfg))
    return SootheConfig()  # OPENAI_API_KEY / ANTHROPIC_API_KEY


@asynccontextmanager
async def open_sqlite_checkpointer(config: SootheConfig) -> AsyncIterator[Any | None]:
    result = resolve_checkpointer(config)
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
        await conn.close()


async def run_once(query: str, *, thread_id: str) -> None:
    config = load_config()
    agent = create_nano_agent(config)
    async with open_sqlite_checkpointer(config) as checkpointer:
        if checkpointer is not None:
            agent.graph.checkpointer = checkpointer
        async for chunk in agent.astream(
            query,
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates", "custom"],
        ):
            _ = chunk  # render tokens / tool progress to stdout


if __name__ == "__main__":
    asyncio.run(run_once("Open Calculator and compute 25 * 17", thread_id="cli-demo"))
```

### Minimal Python Script

For a one-liner without persistence/streaming concerns:

```python
import asyncio
from soothe_nano import create_nano_agent
from soothe_nano.config import SootheConfig

agent = create_nano_agent(SootheConfig())  # env-var config; computer_use is enabled by default

asyncio.run(agent.ainvoke("Take a screenshot of my desktop and tell me what's visible."))
```

The main agent auto-delegates to `computer_use` when the task triggers the
`COMPUTER_CONTEXT` / `WORKSPACE` routing keys (see
[How Delegation Works](#how-delegation-works)).

### Streaming Wire Events

To observe `computer_use` progress in real time, stream the `custom` channel
and filter for the three `soothe.subagent.computer_use.*` event types:

```python
async for chunk in agent.astream(task, stream_mode="custom"):
    event = chunk
    if event["type"].startswith("soothe.subagent.computer_use"):
        # started / step.completed / completed
        print(event.get("summary_template") or event["type"])
```

| Event | Wire Type | Key Fields |
|---|---|---|
| `ComputerUseStartedEvent` | `soothe.subagent.computer_use.started` | `task_preview` |
| `ComputerUseStepCompletedEvent` | `soothe.subagent.computer_use.step.completed` | `step_index`, `tool_name`, `action_preview`, `status`, `duration_ms` |
| `ComputerUseCompletedEvent` | `soothe.subagent.computer_use.completed` | `duration_ms`, `success`, `summary` |

All three are registered with `VerbosityTier.NORMAL` (default client-wire
visibility) and forwarded to LangGraph's `custom` stream channel via
`emit_subagent_wire_event()`.

---

## Example Prompts

The main agent routes desktop-GUI tasks to `computer_use` automatically — you
do not need to name the subagent. Just describe what you want.

### Desktop App Control

```
1. "Open Calculator and compute 25 * 17."
   → screenshot → click Calculator icon → click 2, 5, *, 1, 7, = → screenshot → done

2. "Open System Settings, navigate to Displays, and tell me the current resolution."
   → screenshot → click Apple menu → System Settings → Displays → read resolution → done

3. "Open Notes and create a new note titled 'Meeting Notes' with today's date."
   → screenshot → click Notes → File → New Note → type title → type date → done

4. "Open Terminal, run 'ls -la' and report the largest file in my home directory."
   → screenshot → click Terminal → type 'ls -la' → key enter → screenshot → read output → done

5. "Open Firefox, search for 'LangGraph tutorial', and open the first result."
   → screenshot → click Firefox → click address bar → type query → key enter
   → screenshot → click first result → screenshot → done
```

### Information Retrieval

```
6. "Take a screenshot of my desktop and tell me what applications are visible."
   → screenshot → describe visible windows → done

7. "Switch to the next desktop space and take a screenshot."
   → screenshot → hotkey 'ctrl,right' → screenshot → done
```

### Multi-Step Workflows

```
8. "Open the Downloads folder in Finder and list the 3 most recently downloaded files."
   → screenshot → click Finder → click Downloads → screenshot → read file list → done

9. "Open Mail, find the most recent unread message, and summarize its subject and sender."
   → screenshot → click Mail → click Inbox → screenshot → read top unread → done

10. "Open Spotify, play the first track in 'Liked Songs', then take a screenshot showing the now-playing bar."
    → screenshot → click Spotify → click Liked Songs → click first track → screenshot → done
```

**Programmatic delegation** (when you want to bypass the router and call the
subagent directly):

```python
from soothe_nano.config import SootheConfig
from soothe_nano.subagents.computer_use import create_computer_use_subagent
from soothe_nano.subagents.computer_use.config_model import ComputerUseSubagentConfig

config = SootheConfig()  # or SootheConfig.from_yaml_file("nano.yml")
subagent = create_computer_use_subagent(
    max_steps=15,
    config=ComputerUseSubagentConfig(input_mode="pyautogui", coordinate_scale=2),
    soothe_config=config,
)
# subagent["runnable"] is a compiled LangGraph
result = await subagent["runnable"].ainvoke(
    {"messages": [{"role": "user", "content": "Open Calculator and compute 25 * 17"}]}
)
print(result["answer"])
```

---

## How Delegation Works

You do not invoke `computer_use` by name. The main agent's task-tool router
selects it when a prompt matches its trigger keys and description:

- **Triggers:** `WORKSPACE`, `COMPUTER_CONTEXT`
- **Description (registered):** *"Desktop automation specialist for GUI tasks.
  Can take screenshots, click at screen coordinates, type text, press keyboard
  keys and hotkeys, and scroll. Use for desktop application control, visual UI
  interaction, and screen-based automation."*
- **System context** (injected into the subagent): `<COMPUTER_CONTEXT>` with
  `<SCREEN_RULES>` (always screenshot first, coordinates from top-left `(0, 0)`,
  verify targets before clicking), `<INPUT_INTERPRETATION>`, and
  `<BEST_PRACTICES>`.

The subagent then runs its own agentic loop: screenshot → decide action via the
vision LLM (`_decide_next_action`) → execute via the backend (`_execute_step`)
→ record in `_StepHistory` → repeat until `done` or `max_steps`. After the
loop, a structured synthesis call (`_ComputerUseSynthesisDecision`) acts as a
quality gate: it can pass the raw result through or synthesize a better answer
strictly from the trajectory evidence.

**Routing boundary — when NOT to use `computer_use`:**

| Task | Use instead |
|---|---|
| Web URLs / browser automation | `browser_use` subagent |
| Local file reads / writes | `read_file` / `write_file` tools |
| Shell commands | `run_command` tool |

The `COMPUTER_DESCRIPTION` constant in `implementation.py` encodes this
boundary so the router does not mis-route.

---

## Observability & Logs

Each run emits structured log lines (parallel to the wire events) via
`_log_computer_event()`. Search your logs for `computer_use event=`:

| Log event | When | Notable fields |
|---|---|---|
| `run_start` | Loop begins | `run_id`, `model_role`, `base_url`, `platform`, `display_server`, `coordinate_scale`, `screenshot_interval_s`, `screenshot_quality`, `screenshot_format`, `input_mode`, `action_delay_s` |
| `task_preview` | After task extraction | `run_id`, `preview` (first 400 chars) |
| `backend_ready` | Backend initialized | `run_id`, `backend`, `coordinate_scale` |
| `backend_missing` | pyautogui import failed | `run_id`, `backend`, `error` |
| `step_begin` | Before each LLM action decision | `run_id`, `step`, `max_steps`, `elapsed_s` |
| `step_end` | After action executed | `run_id`, `step`, `dt_s`, `tool`, `action`, `done` |
| `run_done` | Early exit on `done` action | `run_id`, `step` |
| `no_progress` | Loop ended without meaningful action | `run_id`, `model`, `steps` |
| `no_content` | Loop ended with no `done` result | `run_id`, `steps`, `model` |
| `synthesis_begin` / `synthesis_end` | Quality-gate LLM call | `run_id`, `role`, `use_raw`, `quality` |
| `synthesis_applied` | Synthesized answer replaced raw | `run_id` |
| `run_end` | Loop finished | `run_id`, `total_s`, `steps`, `success`, `result_preview` |
| `temp_cleanup` | Screenshots cleaned up | `run_id` |
| `run_failed` | Uncaught exception | `run_id` (+ stack trace) |

The `run_start` line now includes **cross-platform metadata** —
`platform`, `platform_release`, `machine`, `display_server`, `display_env` —
plus the active `coordinate_scale`, `screenshot_interval_s`,
`screenshot_quality`, `screenshot_format`, `input_mode`, and `action_delay_s`
values. A single log line therefore tells you the OS, display-server state,
and the effective config knobs for that run, which covers the most common
blank-screenshot and input-failure root causes.

---

## Troubleshooting

### `PluginError: pyautogui library not installed`

Install it: `pip install pyautogui`
([Python Dependencies](#python-dependencies)).

### Mouse clicks do nothing (macOS)

pyautogui requires **Accessibility** permission. Test:
`python -c "import pyautogui; pyautogui.click(100, 100)"`. If it doesn't
register, grant the permission under
System Settings → Privacy & Security → Accessibility
([macOS Permissions](#macos-permissions)).

### Screenshots are blank/black (macOS)

Grant **Screen Recording** permission and restart the terminal/IDE
([macOS Permissions](#macos-permissions)).

### Coordinates are off on Retina displays

Set `coordinate_scale: 2` in config. The backend then divides LLM-space
coordinates by 2 before calling pyautogui
([Retina / HiDPI Displays](#retina--hidpi-displays)).

### `no_progress` error

The agent ran `max_steps` steps without taking a meaningful action (only
screenshots or waits). Check:
- The model is **vision-capable** (e.g. `gpt-4.1`, not a text-only model).
- API credentials are valid (`base_url` / `api_key` in the `run_start` log).
- The `display_server` field in `run_start` is not `unknown` on Linux.

### Agent runs out of steps

Complex multi-click tasks may exceed the default `max_steps: 10`. Raise it:

```yaml
subagents:
  computer_use:
    config:
      max_steps: 25
```

### No input backend configured

If `input_mode` is not `pyautogui`/`auto` and no backend is injected, the
fallback `_DesktopInputBackend()` raises `NotImplementedError` on every action:

```json
{"action": "screenshot", "error": "capture_screenshot not implemented"}
```

**Fix:** set `input_mode: pyautogui` in YAML, or pass a concrete `backend=`
when calling `create_computer_use_subagent()` programmatically.

---

## Known Limitations

These are open gaps (mirrored in the
[Implementation Guide](./computer_use_implementation_guide.md#known-gaps--next-steps)):

1. **`pyautogui` not in `pyproject.toml`** — must be installed manually.
   Planned fix: add `[project.optional-dependencies] desktop = ["pyautogui>=0.9.54"]`.

2. **`osascript` backend not implemented** — `input_mode` accepts `"osascript"`
   but only `_PyAutoGUIBackend` exists. `"auto"` currently resolves to
   `pyautogui` when available, else the no-op base.

3. **`config_model.backend` vs `input_mode`** — the graph builder references
   `computer_config.backend`, but `ComputerUseSubagentConfig` defines
   `input_mode`. Until reconciled, prefer `input_mode: pyautogui` in YAML.

4. **Screenshot-to-LLM image passing** — `_decide_next_action()` currently sends
   a **text trajectory** to the LLM, not the screenshot image as a multimodal
   content block. True vision-driven automation requires loading the screenshot
   and passing it as `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`.
   Screenshots are saved in a valid image format (png/jpeg) ready for this
   encoding step.

5. **No unit tests** for the `computer_use` module yet — the `browser_use`
   test suite can be mirrored.

---

*For the architectural deep-dive (agent loop, backend protocol, action types,
wire events, registration touchpoints), see the
[Implementation Guide](./computer_use_implementation_guide.md).*
