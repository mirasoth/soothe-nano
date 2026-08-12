"""Nano agent + computer_use: WeChat Favorites article-link harvester.

This example drives the existing WeChat desktop app on macOS via the
first-party ``computer_use`` subagent. The agentic loop:

    1. Brings the running WeChat window to the front via Spotlight
       (``cmd+space`` → "WeChat" → ``enter``).
    2. Navigates to **Favorites** (收藏) — click the sidebar entry.
    3. Scrolls through the favorites list, opens each favorited article
       one by one, and reads the URL that appears in the article view /
       share sheet.
    4. Collects every discovered article link, then prints the **latest
       five** links (most recently added favorites first).

Two invocation styles are shown (mirroring example 06):

- **Style 1 — Routed delegation:** the main nano agent auto-selects the
  ``computer_use`` subagent from the plain-language task description.
- **Style 2 — Direct invocation:** bypass the router and call the
  ``computer_use`` subagent's compiled LangGraph runnable directly,
  giving tighter control over ``max_steps`` (favorites browsing needs
  more steps than the default 10).

Prerequisites
-------------
- WeChat for Mac installed and signed in (the app window must exist).
- ``pip install pyautogui`` (not yet a declared dependency).
- macOS: grant *Accessibility* + *Screen Recording* to your terminal/IDE.
- A **vision-capable model** (e.g. ``gpt-4.1``, ``gpt-4o``, ``qwen-vl-max``)
  pinned to the ``vision`` role and referenced via
  ``subagents.computer_use.model_role``. See
  ``docs/computer_use_cli_guide.md`` § Model Selection.

Run:
    python examples/07_nano_computer_use_weixin_favorites.py
"""

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Make local ``_shared`` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _shared.config import load_nano_example_config
from _shared.streaming import stream_nano_agent

from soothe_nano import create_nano_agent

load_dotenv()


# ─── Link extraction helpers ────────────────────────────────────────────

# WeChat article links come in a few shapes — the canonical
# ``mp.weixin.qq.com/s/...`` short link, the ``?__biz=...`` long form,
# and occasionally ``mp.weixin.qq.com/s?mid=...``. Match all of them so
# we don't miss a harvested URL regardless of how the share sheet shows it.
_URL_PATTERN = re.compile(
    r"https?://mp\.weixin\.qq\.com/(?:s(?:/|\?)[^\s\"'<>\\]*|\?[^\s\"'<>\\]*)",
    re.IGNORECASE,
)


def extract_links(text: str) -> list[str]:
    """Pull WeChat article URLs out of free-form agent output.

    The computer_use subagent returns a natural-language answer that
    embeds the URLs it saw while browsing. We scan that text for the
    ``mp.weixin.qq.com`` links and de-duplicate while preserving order
    (order reflects the agent's browse order = recency in Favorites).
    """
    seen: set[str] = set()
    links: list[str] = []
    for match in _URL_PATTERN.findall(text or ""):
        link = match.rstrip(".,);]'\"")
        if link not in seen:
            seen.add(link)
            links.append(link)
    return links


def print_latest_links(answer: str, *, n: int = 5) -> list[str]:
    """Parse agent output for links and print the latest ``n``.

    Returns the (possibly truncated) link list so callers can assert on it.
    """
    links = extract_links(answer)
    latest = links[:n]

    print("\n" + "─" * 60)
    print(f"Discovered WeChat article links ({len(links)} total)")
    print("─" * 60)
    if not latest:
        print("No mp.weixin.qq.com links were found in the agent output.")
        print(
            "Tip: raise max_steps, ensure WeChat is signed in, or check the "
            "vision model is reading the article view / share sheet correctly."
        )
    else:
        for idx, link in enumerate(latest, 1):
            print(f"  {idx}. {link}")
        if len(links) > n:
            print(f"  … (+{len(links) - n} more, not shown)")
    print("─" * 60)
    return latest


# ─── Style 1: Routed delegation through the main nano agent ─────────────


async def run_routed_delegation(agent) -> list[str]:
    """Let the nano router pick ``computer_use`` automatically.

    The main agent's task-tool router selects ``computer_use`` when a
    prompt matches its ``WORKSPACE`` / ``COMPUTER_CONTEXT`` trigger keys.
    Describe the desktop task in plain language — do NOT name the subagent.
    """
    print("\n" + "=" * 60)
    print("Style 1: Routed Delegation (router selects computer_use)")
    print("=" * 60)

    task = (
        "Bring the WeChat desktop app to the front on this Mac — press "
        "cmd+space, type WeChat, and press enter. Then click the Favorites "
        "(收藏) icon in the narrow left sidebar. Scroll through the favorites "
        "list so you can see all saved articles. For each favorited article, "
        "click it to open the article view, then find the article's URL — it's "
        "shown in the article header or via the Share → Copy Link menu. Collect "
        "every article link you can see. When you've browsed all favorites, "
        "list the five most recently added article URLs, one per line, prefixed "
        "with the number. Use the mp.weixin.qq.com link exactly as shown."
    )
    answer = await stream_nano_agent(agent, task, thread_id="weixin-favorites-routed")
    return print_latest_links(answer)


# ─── Style 2: Direct subagent invocation (bypass the router) ────────────


async def run_direct_invocation(config) -> list[str]:
    """Call the ``computer_use`` subagent runnable directly.

    Bypasses the main agent's routing layer and hands the task straight
    to the desktop automation loop. We bump ``max_steps`` because
    favorites browsing needs many screenshot/click/scroll steps.
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
        max_steps=30,
        config=ComputerUseSubagentConfig(
            input_mode="pyautogui",
            # The backend measures the real screenshot-to-input ratio on its
            # first capture, so this only matters before that probe lands.
            coordinate_scale=1,
            action_delay_s=0.8,
        ),
        soothe_config=config,
    )

    # ``subagent["runnable"]`` is a compiled LangGraph that accepts a
    # messages dict and returns ``{"answer": str, ...}``.
    runnable = subagent["runnable"]

    print("\n[Direct] Invoking computer_use runnable: browse WeChat Favorites…")
    result: dict[str, Any] = await runnable.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Bring the WeChat desktop app to the front: press "
                        "cmd+space, type WeChat, press enter. Click the "
                        "Favorites (收藏) icon in the narrow left sidebar. "
                        "Scroll down through the favorites list so every saved "
                        "article is visible. Open each favorited article one by "
                        "one by clicking it, and read the article URL — shown in "
                        "the article header or via Share → Copy Link. After "
                        "browsing all favorites, report the five most recently "
                        "added article URLs, one per line, numbered 1–5. Print "
                        "each mp.weixin.qq.com link exactly as shown."
                    ),
                }
            ]
        }
    )
    answer = result.get("answer", "") or str(result)
    print(f"\n[Direct] Answer:\n{answer}")
    return print_latest_links(answer)


# ─── Entry point ────────────────────────────────────────────────────────


async def main() -> None:
    """Run the WeChat Favorites link-harvesting examples."""
    print("=" * 60)
    print("Example 07: Nano Agent + computer_use (WeChat Favorites)")
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

    # Style 2 — direct subagent runnable invocation (higher max_steps).
    await run_direct_invocation(config)

    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)
    print(
        "\nTip: WeChat's Favorites view shows saved articles in reverse "
        "chronological order by default, so the first five the agent opens "
        "are the latest five. If the list is long, bump max_steps so the loop "
        "can scroll and open every item."
    )
    print(
        "Troubleshooting: blank screenshots or silent clicks usually mean "
        "missing macOS Accessibility/Screen Recording permissions. See "
        "docs/computer_use_cli_guide.md."
    )


if __name__ == "__main__":
    asyncio.run(main())
