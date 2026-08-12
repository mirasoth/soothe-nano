"""Nano agent with computer_use subagent example.

This example demonstrates driving the desktop GUI — cursor movement, clicks,
typing, and keyboard shortcuts — by delegating to the first-party
``computer_use`` subagent. It shows two invocation styles:

1. **Routed delegation** — the main nano agent auto-selects the
   ``computer_use`` subagent based on the task description (no subagent name
   needed). This is the production-style path.
2. **Direct invocation** — bypass the router and call the subagent's compiled
   LangGraph runnable directly. Useful for tight control / testing.

Prerequisites
-------------
The ``computer_use`` subagent is **enabled by default** in every
``SootheConfig``, but it needs a running display server and, on macOS, the
proper privacy permissions:

- ``pip install pyautogui``  (not yet a declared dependency)
- macOS: grant *Accessibility* + *Screen Recording* to your terminal/IDE
- Linux: ensure ``DISPLAY`` / ``WAYLAND_DISPLAY`` is set (or ``Xvfb``)
- Windows: works natively

A **vision-capable model** (e.g. ``gpt-4.1``, ``gpt-4o``, ``qwen-vl-max``)
must be pinned to the ``vision`` role and referenced via
``subagents.computer_use.model_role``. See
``docs/computer_use_cli_guide.md`` § Model Selection.

Run:
    python examples/06_nano_computer_use_example.py
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make local ``_shared`` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _shared.config import load_nano_example_config
from _shared.streaming import stream_nano_agent

from soothe_nano import create_nano_agent

load_dotenv()


# ─── Style 1: Routed delegation through the main nano agent ─────────────


async def run_routed_delegation(agent) -> None:
    """Let the nano router pick ``computer_use`` automatically.

    The main agent's task-tool router selects ``computer_use`` when a prompt
    matches its ``WORKSPACE`` / ``COMPUTER_CONTEXT`` trigger keys. Just
    describe the desktop task in plain language — do NOT name the subagent.
    """
    print("\n" + "=" * 60)
    print("Style 1: Routed Delegation (router selects computer_use)")
    print("=" * 60)

    # Cursor + click + type workflow: the vision LLM will screenshot first,
    # locate the target, click it, then type.
    task = (
        "Take a screenshot of my desktop, then click on the search/spotlight "
        "area at the top-right of the screen, type 'Calculator', press enter, "
        "and report what opened."
    )
    await stream_nano_agent(agent, task, thread_id="computer-use-routed")


# ─── Style 2: Direct subagent invocation (bypass the router) ────────────


async def run_direct_invocation(config) -> None:
    """Call the ``computer_use`` subagent runnable directly.

    This bypasses the main agent's routing layer and hands the task straight
    to the desktop automation loop. Returns the synthesized answer from the
    subagent's quality-gate synthesis step.
    """
    print("\n" + "=" * 60)
    print("Style 2: Direct Subagent Invocation (bypass router)")
    print("=" * 60)

    # Imported lazily so the example still loads if the plugin is disabled.
    from soothe_nano.subagents.computer_use import create_computer_use_subagent
    from soothe_nano.subagents.computer_use.config_model import (
        ComputerUseSubagentConfig,
    )

    subagent = create_computer_use_subagent(
        max_steps=15,
        config=ComputerUseSubagentConfig(
            input_mode="pyautogui",
            # Set to 2 on Retina/HiDPI displays — the screenshot is physical
            # pixels but pyautogui consumes logical (1x) coordinates.
            coordinate_scale=2,
            action_delay_s=0.8,
        ),
        soothe_config=config,
    )

    # ``subagent["runnable"]`` is a compiled LangGraph that accepts a
    # messages dict and returns ``{"answer": str, ...}``.
    runnable = subagent["runnable"]

    print("\n[Direct] Invoking computer_use runnable: move cursor + click…")
    result = await runnable.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Take a screenshot, move the cursor to the Apple menu "
                        "at the top-left, click it, then take another "
                        "screenshot showing the menu that opened."
                    ),
                }
            ]
        }
    )
    print(f"\n[Direct] Answer: {result.get('answer', result)}")


# ─── Entry point ────────────────────────────────────────────────────────


async def main() -> None:
    """Run the computer_use cursor-control examples."""
    print("=" * 60)
    print("Example 06: Nano Agent + computer_use (Cursor Control)")
    print("=" * 60)

    config = load_nano_example_config()
    print(f"\n[Config] Model: {config.router.default}")

    # Confirm the computer_use subagent is registered before we rely on it.
    cu_cfg = config.subagents.get("computer_use")
    if cu_cfg and hasattr(cu_cfg, "enabled"):
        print(f"[Config] computer_use: {'enabled' if cu_cfg.enabled else 'disabled'}")
        if not cu_cfg.enabled:
            print(
                "\nNote: computer_use is disabled in config. "
                "Set subagents.computer_use.enabled: true to run this example."
            )
    else:
        print("[Config] computer_use: default (enabled)")

    agent = create_nano_agent(config)
    print(f"\n[Agent] Subagents available: {len(agent.subagents)}")
    for sub in agent.subagents:
        print(f"  - {getattr(sub, 'name', 'unknown')}")

    # Style 1 — full nano agent, router-driven delegation.
    await run_routed_delegation(agent)

    # Style 2 — direct subagent runnable invocation.
    await run_direct_invocation(config)

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)
    print(
        "\nTip: Cursor coordinates come from the vision LLM reading the "
        "screenshot. On Retina/HiDPI, set coordinate_scale=2 so physical "
        "pixels are divided to logical pyautogui coordinates."
    )
    print(
        "Troubleshooting: blank screenshots or silent clicks usually mean "
        "missing macOS Accessibility/Screen Recording permissions. See "
        "docs/computer_use_cli_guide.md."
    )


if __name__ == "__main__":
    asyncio.run(main())
