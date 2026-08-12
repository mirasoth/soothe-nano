# `computer_use` Subagent — Implementation Guide

> **Desktop automation plugin for soothe-nano.** This guide documents how to
> enable the `computer_use` capability, configure the OS-level display server
> it requires, and drive desktop applications through natural-language prompts.

## Table of Contents

1. [Overview](#overview)
2. [System Dependencies](#system-dependencies)
   - [OS-Level Display Server Setup](#os-level-display-server-setup)
   - [Python Dependencies](#python-dependencies)
3. [Configuration](#configuration)
   - [Enabling the Subagent](#enabling-the-subagent)
   - [Full Configuration Reference](#full-configuration-reference)
   - [Model Selection](#model-selection)
4. [Architecture Summary](#architecture-summary)
5. [Usage Workflows](#usage-workflows)
   - [Example Prompts for Desktop App Control](#example-prompts-for-desktop-app-control)
6. [Troubleshooting](#troubleshooting)
7. [Known Gaps & Next Steps](#known-gaps--next-steps)

---

## Overview

The `computer_use` subagent is a **desktop automation specialist** that drives a
GUI through a vision-capable LLM agentic loop:

```
screenshot → reason → act (click / type / key / scroll) → repeat → done
```

It is architecturally parallel to the `browser_use` subagent:

| Layer | Pattern |
|---|---|
| Plugin registration | `@plugin(name="computer_use")` + `@subagent(name="computer_use")` |
| Graph topology | Single-node LangGraph: `START → run_computer_use → END` |
| Step loop | Manual loop, `max_steps` cap, early-exit on `done` action |
| Post-run synthesis | Structured LLM call (`_ComputerUseSynthesisDecision`) with quality gate |
| Wire events | `started` / `step.completed` / `completed` via `emit_subagent_wire_event` |
| Logging | Structured `computer_use event=X key=v` lines (parallel to wire events) |

**Module location:** `src/soothe_nano/subagents/computer_use/`

```
computer_use/
├── __init__.py            # @plugin + @subagent registration, on_load dependency gate
├── implementation.py      # LangGraph agent loop, backends, synthesis
├── tools.py               # LangChain BaseTool schemas + _DesktopInputBackend protocol
├── config_model.py        # ComputerUseSubagentConfig (Pydantic)
├── events.py              # 3 wire event types (started/step/completed)
├── action_format.py       # Human-readable step labels for TUI
├── display_summary.py     # Completion-card summary helper
└── _preview.py            # Text truncation helper for logging
```

---

## System Dependencies

### OS-Level Display Server Setup

The `computer_use` subagent captures screenshots and injects mouse/keyboard
input via **pyautogui**, which requires a running display server. Setup differs
by platform:

#### macOS

macOS ships with a display server (WindowServer). No additional setup is needed,
**but you must grant accessibility and screen-recording permissions**:

1. **System Settings → Privacy & Security → Accessibility**
   - Add the terminal/IDE that runs soothe-nano (e.g. Terminal, iTerm2, VS Code).
   - Toggle the switch ON.

2. **System Settings → Privacy & Security → Screen Recording**
   - Add the same application.
   - Toggle ON. A restart of the application may be required.

Without accessibility permission, pyautogui's `click()`, `typewrite()`, and
`hotkey()` calls will silently fail. Without screen-recording permission,
`screenshot()` returns a blank or permission-denied image.

> **Retina/HiDPI note:** On Retina displays, set
> `coordinate_scale: 2` in the config (see [Configuration](#configuration)) so
> the LLM's pixel coordinates map correctly to physical pixels.

#### Linux

**Desktop session (local):** pyautogui works out of the box with X11. For
Wayland, you may need:

```bash
# Debian/Ubuntu
sudo apt install python3-tk python3-dev scrot
# scrot or gnome-screenshot provides the screenshot backend
# For Wayland, install: grim slurp
```

Ensure the `DISPLAY` or `WAYLAND_DISPLAY` environment variable is set in the
session that launches soothe-nano.

**Headless server (remote/VPS):** pyautogui needs a virtual framebuffer:

```bash
sudo apt install xvfb
# Launch a virtual display before starting the agent:
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
```

Then launch your desktop application (e.g. `firefox &`) in the same `DISPLAY`
session.

#### Windows

pyautogui works natively on Windows 10/11 with no display server configuration.
Install:

```powershell
pip install pyautogui
# Pillow and pygetwindow are installed as dependencies automatically
```

For multi-monitor setups, `region` coordinates are relative to the primary
monitor's top-left corner `(0, 0)`.

### Python Dependencies

The `computer_use` subagent depends on **pyautogui**, which is declared in
`pyproject.toml` and installed with the package. It must be importable from
**the interpreter that runs soothe-nano**; if the agent is launched with a
different Python, install it there as well:

```bash
pip install pyautogui
# pyautogui pulls in: Pillow, pygetwindow (Windows), mouseinfo, pymsgbox,
# pytweening, and pyobjc-core/pyobjc-framework (macOS) as needed.
```

On macOS the `screencapture` CLI serves screenshots without pyautogui, so a
missing install stays invisible until the first click. `_ensure_pagu()` raises
`DesktopInputUnavailableError`, `_execute_step` converts it into a step-level
`{"error": ...}`, and the run logs `input_unavailable` at startup.

The plugin's `on_load()` method performs a soft dependency check — if
`import pyautogui` fails, it raises `PluginError`:

```
pyautogui library not installed. Install with: pip install -U soothe-nano
```

> **Note:** The `on_load` error message points to `pip install -U soothe-nano`
> because the eventual fix is to add pyautogui to `pyproject.toml`. For now,
> install it manually as shown above.

---

## Configuration

### Enabling the Subagent

The `computer_use` subagent is **enabled by default**. The config validator
`_merge_subagents` in `src/soothe_nano/config/settings.py` (line 459) inserts:

```python
"computer_use": SubagentConfig(enabled=True, model_role="default")
```

into every `SootheConfig` instance. No YAML is required to activate it.

To **disable** it, override in your YAML config:

```yaml
subagents:
  computer_use:
    enabled: false
```

To **tune** it:

```yaml
subagents:
  computer_use:
    enabled: true
    model_role: vision       # use a vision-capable model for action decisions
    config:
      max_steps: 20
      input_mode: pyautogui
      coordinate_scale: 2    # Retina displays
      action_delay_s: 0.8
      cleanup_on_exit: true
      synthesis_role: default
      synthesis_timeout_sec: 45
```

### Full Configuration Reference

The `ComputerUseSubagentConfig` Pydantic model
(`src/soothe_nano/subagents/computer_use/config_model.py`) defines all
tunable knobs:

| Field | Type | Default | Description |
|---|---|---|---|
| `max_steps` | `int` | `99` | Maximum desktop automation steps per delegated task. |
| `runtime_dir` | `str` | `""` | Base directory for desktop runtime files. Empty = auto-resolved under `SOOTHE_HOME`. |
| `screenshots_dir` | `str` | `""` | Directory for captured screenshots. Empty = `<runtime_dir>/screenshots`. |
| `cleanup_on_exit` | `bool` | `True` | Remove temporary screenshots when session ends. |
| `screenshot_interval_s` | `float` | `0.0` | Seconds between automatic periodic screenshots. `0` = disabled. |
| `screenshot_quality` | `int` | `85` | JPEG quality (1–100) when format is `jpeg`. |
| `screenshot_format` | `Literal["png","jpeg"]` | `"png"` | Screenshot image format. |
| `input_mode` | `Literal["auto","pyautogui","osascript"]` | `"auto"` | Desktop input backend. `auto` selects the best platform backend. |
| `coordinate_scale` | `int` | `1` | Coordinate scale factor (`1` = 1x, `2` = Retina). |
| `action_delay_s` | `float` | `0.5` | Delay after each input action for UI to settle. |
| `synthesis_role` | `str` | `"default"` | Router role for post-run result synthesis/quality gate. |
| `synthesis_timeout_sec` | `float` | `30.0` | Timeout budget for the synthesis LLM call. |

### Model Selection

The `computer_use` subagent resolves its LLM via the soothe-nano router — it
does **not** accept a `model` kwarg. Resolution flow:

1. `resolve_subagents()` checks `subagents.computer_use.model_role`
   (default: `"default"`).
2. `soothe_config.resolve_model(role)` returns a `"provider:model"` spec.
3. `_resolve_computer_llm_credentials()` splits the spec and extracts
   `base_url` / `api_key` from the `ProviderRegistry`.
4. The model is instantiated as `ChatOpenAI(model=..., base_url=..., api_key=...)`.

**Important:** The action-decision LLM must be **vision-capable** (e.g.
`gpt-4o`, `gpt-4.1`, `qwen-vl-max`) because the agent sends screenshot context
and needs to interpret pixel coordinates. Set a vision-capable model:

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

## Architecture Summary

### Agent Loop (`implementation.py`)

The single graph node `_run_computer_use_async()` executes:

```
1. Extract task from messages[-1].content
2. Emit ComputerUseStartedEvent (task_preview)
3. Resolve LLM credentials (model_role → provider:model → base_url/api_key)
4. Initialize backend (_PyAutoGUIBackend if input_mode == "pyautogui")
5. _capture_observation(backend) → prime the loop with a screenshot
6. For step_idx in range(max_steps):
   a. _decide_next_action(llm, task, history, max_steps, screenshot_path, ...)
      → _ComputerAction
      - Builds system prompt describing all available actions
      - Sends trajectory (last 8 steps) + steps remaining
      - Attaches the latest screenshot as an image_url data URI
      - Nudges to act after repeated observe-only actions
      - invoke_structured_chat_typed(llm, messages, _ComputerAction)
   b. _execute_step(action, backend) → dict result
      - Dispatches to backend.acapture_screenshot / aclick / akeyboard / ascroll
   c. history.add(step, action, result)
   d. _capture_observation(backend, delay_s=action_delay_s) → refresh the view
      the next decision sees (skipped for screenshot / done actions)
   e. Emit ComputerUseStepCompletedEvent (step_index, tool_name, action_preview)
   f. If history.is_done(): break
7. Extract final_result from 'done' action's 'reason' field
8. _synthesize_computer_use_result(...) → _ComputerUseSynthesisDecision
   - Quality gate: answer_quality = "sufficient" | "insufficient"
   - Can synthesize a better answer from trajectory evidence
9. Emit ComputerUseCompletedEvent (duration_ms, success, summary)
10. Cleanup: cleanup_computer_temp_files() if cleanup_on_exit
11. Return {"messages": [AIMessage(content=result)], "answer": result}
```

### Action Types (`_ComputerAction`)

The vision LLM chooses one action per step via structured output:

| `action_type` | Fields Used | Backend Method |
|---|---|---|
| `screenshot` | `reason` | `acapture_screenshot()` |
| `click` | `x, y, button, click_type` | `aclick()` |
| `double_click` | `x, y` | `aclick(click_type="double")` |
| `right_click` | `x, y` | `aclick(button="right")` |
| `type` | `text` | `akeyboard(action_type="type")` |
| `key` | `key` | `akeyboard(action_type="key")` |
| `hotkey` | `keys` (comma-separated) | `akeyboard(action_type="hotkey")` |
| `scroll` | `x, y, direction, amount` | `ascroll()` |
| `wait` | — | `asyncio.sleep(0.5)` |
| `done` | `reason` (final result) | (no-op, terminates loop) |

### Backend Protocol (`_DesktopInputBackend`)

The backend is a swappable protocol with sync + async variants:

```python
class _DesktopInputBackend:
    def capture_screenshot(...) -> dict
    def acapture_screenshot(...) -> dict   # delegates to sync by default
    def click(...) -> dict
    def aclick(...) -> dict
    def keyboard(...) -> dict
    def akeyboard(...) -> dict
    def scroll(...) -> dict
    def ascroll(...) -> dict
    def close() -> None
    def aclose() -> None
```

The default concrete implementation is `_PyAutoGUIBackend`, which lazily
imports pyautogui, sets `FAILSAFE=True` and `PAUSE=0.1`, and saves screenshots
to the session's screenshots directory.

### Wire Events (`events.py`)

Three event types registered with `VerbosityTier.NORMAL`:

| Event | Wire Type | Key Fields |
|---|---|---|
| `ComputerUseStartedEvent` | `soothe.subagent.computer_use.started` | `task_preview` |
| `ComputerUseStepCompletedEvent` | `soothe.subagent.computer_use.step.completed` | `step_index, tool_name, action_preview, status, duration_ms` |
| `ComputerUseCompletedEvent` | `soothe.subagent.computer_use.completed` | `duration_ms, success, summary` |

All extend `SubagentEvent` from `soothe_sdk.core.events` and are forwarded to
LangGraph's `custom` stream channel via `emit_subagent_wire_event()`.

---

## Usage Workflows

### Example Prompts for Desktop App Control

The `computer_use` subagent is invoked automatically by the main agent when a
task requires desktop GUI interaction. You can also delegate explicitly.

**Natural-language prompts** (the main agent routes to `computer_use` when
`COMPUTER_CONTEXT` triggers fire):

```
1. "Open Calculator and compute 25 * 17."
   → screenshot → click Calculator icon → click 2, 5, *, 1, 7, = → screenshot → done

2. "Open System Settings, navigate to Displays, and tell me the current resolution."
   → screenshot → click Apple menu → System Settings → Displays → read resolution → done

3. "Open Notes and create a new note titled 'Meeting Notes' with today's date."
   → screenshot → click Notes → File → New Note → type title → type date → done

4. "Take a screenshot of my desktop and tell me what applications are visible."
   → screenshot → describe visible windows → done

5. "Open Terminal, run 'ls -la' and report the largest file in my home directory."
   → screenshot → click Terminal → type 'ls -la' → key enter → screenshot → read output → done

6. "Open Firefox, search for 'LangGraph tutorial', and open the first result."
   → screenshot → click Firefox → click address bar → type search query → key enter
   → screenshot → click first result → screenshot → done

7. "Switch to the next desktop space and take a screenshot."
   → screenshot → hotkey 'ctrl,right' → screenshot → done

8. "Open the Downloads folder in Finder and list the 3 most recently downloaded files."
   → screenshot → click Finder → click Downloads → screenshot → read file list → done
```

**Programmatic delegation** (Python API):

```python
from soothe_nano import create_nano_agent
from soothe_nano.config import load_config

config = load_config("soothe.yaml")
agent = create_nano_agent(config)

# The main agent auto-delegates to computer_use when the task is desktop-GUI
result = await agent.ainvoke("Open Calculator and compute 25 * 17")
```

**Explicit subagent call** (advanced):

```python
from soothe_nano.subagents.computer_use import create_computer_use_subagent

subagent = create_computer_use_subagent(
    max_steps=15,
    config=ComputerUseSubagentConfig(input_mode="pyautogui", coordinate_scale=2),
    soothe_config=config,
)
# subagent["runnable"] is a compiled LangGraph
result = await subagent["runnable"].ainvoke(
    {"messages": [{"role": "user", "content": "Open Calculator and compute 25 * 17"}]}
)
```

### Wire Event Consumption

Stream the three wire events for progress monitoring:

```python
async for chunk in agent.astream(task, stream_mode="custom"):
    event = chunk
    if event["type"].startswith("soothe.subagent.computer_use"):
        # started / step.completed / completed
        print(event["summary_template"])
```

---

## Troubleshooting

### pyautogui not installed

```
PluginError: pyautogui library not installed.
```

**Fix:** `pip install pyautogui` (see [Python Dependencies](#python-dependencies)).

### No input backend configured

If `input_mode` is not `"pyautogui"` and no backend is injected, the fallback
`_DesktopInputBackend()` raises `NotImplementedError` on every action:

```json
{"action": "screenshot", "error": "capture_screenshot not implemented"}
```

**Fix:** Set `input_mode: pyautogui` in YAML, or pass a concrete `backend=`
when calling `create_computer_use_subagent()` programmatically.

### Mouse clicks do nothing (macOS)

pyautogui requires **Accessibility** permission. Verify:

```bash
# Test in Python:
python -c "import pyautogui; pyautogui.click(100, 100)"
```

If the click doesn't register, grant accessibility permission
(see [macOS setup](#macos)).

### Screenshots are blank/black (macOS)

pyautogui requires **Screen Recording** permission. Grant it and restart the
terminal/IDE.

### Coordinates are off on Retina displays

On HiDPI/Retina screens, pyautogui reports logical (scaled) coordinates while
the LLM may reason in physical pixels. Set `coordinate_scale: 2` in the config
to indicate 2x scaling.

### Agent runs out of steps

If `max_steps` (default 99) is too low for complex tasks:

```yaml
subagents:
  computer_use:
    config:
      max_steps: 25
```

The agent emits a `no_progress` error when it never takes a meaningful action
(only screenshots or waits). Check that the model is vision-capable and that
API credentials are valid.

---

## Known Gaps & Next Steps

The `computer_use` subagent was scaffolded to mirror `browser_use` but has
several gaps that must be closed before production use:

### 1. `config_model.backend` field missing

`implementation.py` line 734 references `computer_config.backend`, but
`ComputerUseSubagentConfig` defines `input_mode`, not `backend`. This will
raise `AttributeError` at runtime when the backend auto-initialization branch
is hit.

**Fix:** Either:
- (a) Add `backend: Literal["pyautogui","osascript"] = "pyautogui"` to
  `ComputerUseSubagentConfig`, or
- (b) Change line 734 to use `computer_config.input_mode`:
  ```python
  if computer_config.input_mode in ("auto", "pyautogui"):
  ```

### 2. `osascript` backend not implemented

`input_mode` accepts `"osascript"` in the config, but only `_PyAutoGUIBackend`
is implemented. The `"auto"` mode should select the best available platform
backend; currently it falls through to the no-op `_DesktopInputBackend()`.

**Fix:** Implement an `_OSAScriptBackend` for macOS AppleScript-based input,
and make `"auto"` resolve to `pyautogui` when available, `osascript` on
macOS as fallback.

### 3. `screenshot_interval_s` not wired

The field exists in the config model but is not consumed. Periodic capture is
not implemented; the loop captures a screenshot before the first step and
after every action that touches the UI, which covers the same need for the
agentic path.

---

## Registration Touchpoints (Reference)

For maintainers, the `computer_use` subagent is wired at these locations:

| File | Line(s) | Purpose |
|---|---|---|
| `subagents/computer_use/__init__.py` | 23–49 | `@plugin` + `on_load()` dependency gate |
| `subagents/computer_use/__init__.py` | 51–80 | `@subagent` decorator with system_context + triggers |
| `subagents/__init__.py` | 5 | Import events for wire-type registration |
| `resolve/_resolver_tools.py` | 97, 106 | `SUBAGENT_FACTORIES` registration |
| `resolve/_resolver_tools.py` | 583 | `model_override = None` (router-resolved) |
| `resolve/_resolver_tools.py` | 616–634 | Config branch: builds `ComputerUseSubagentConfig` |
| `resolve/_lazy_subagent.py` | 23–28 | Lazy description for task-tool routing |
| `config/settings.py` | 459 | `_merge_subagents` auto-enables `computer_use` |
| `utils/runtime.py` | 224–242 | Runtime dir + screenshots dir + cleanup helpers |
