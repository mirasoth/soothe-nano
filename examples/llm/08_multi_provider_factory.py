"""Example 08 — Multi-provider factory + config-driven routing via ``soothe_nano.llm``.

Shows the config-driven path used in production: a ``SootheConfig`` with
multiple providers and router profiles, resolved by :class:`LLMFactory` into
``ChatLitellmModel`` instances per *role* (default / fast / think). This is
how the Soothe daemon wires the agent — the same pattern works for any app
that wants to mix providers by role.

This example builds the config inline so it runs without a nano.yml file.
Set the API keys for whichever providers you want to exercise.

Run:
    OPENAI_API_KEY=sk-... GEMINI_API_KEY=... python examples/llm/08_multi_provider_factory.py
"""

from __future__ import annotations

import asyncio
import os

from _helpers import banner, get_weather, print_response
from langchain_core.messages import HumanMessage, SystemMessage

from soothe_nano.config import SootheConfig
from soothe_nano.llm import LLMFactory


def build_config() -> SootheConfig:
    """Build a multi-provider config inline (no YAML file required).

    Providers are resolved by name in the router profiles; the factory turns
    each ``provider:model`` spec into a ``ChatLitellmModel``. The router only
    references providers whose API keys are actually set, so the example never
    tries to call an unconfigured provider.
    """
    providers: list[dict] = []
    # Each entry: (role, spec, env_var_needed). Only added to the router when
    # the env var is present, so we never route to an unconfigured provider.
    candidates: list[tuple[str, str, str, dict]] = []
    if os.environ.get("OPENAI_API_KEY"):
        providers.append(
            {"name": "openai", "provider_type": "openai", "api_key": "${OPENAI_API_KEY}"}
        )
        candidates.append(
            (
                "default",
                "openai:gpt-4o-mini",
                "OPENAI_API_KEY",
                {"name": "openai", "provider_type": "openai", "api_key": "${OPENAI_API_KEY}"},
            )
        )
        candidates.append(
            (
                "think",
                "openai:gpt-4o-mini",
                "OPENAI_API_KEY",
                {"name": "openai", "provider_type": "openai", "api_key": "${OPENAI_API_KEY}"},
            )
        )
    if os.environ.get("GEMINI_API_KEY"):
        providers.append(
            {"name": "gemini", "provider_type": "gemini", "api_key": "${GEMINI_API_KEY}"}
        )
        candidates.append(
            (
                "fast",
                "gemini:gemini-2.0-flash",
                "GEMINI_API_KEY",
                {"name": "gemini", "provider_type": "gemini", "api_key": "${GEMINI_API_KEY}"},
            )
        )
    if os.environ.get("DASHSCOPE_API_KEY"):
        providers.append(
            {
                "name": "dashscope",
                "provider_type": "openai",
                "api_key": "${DASHSCOPE_API_KEY}",
                "api_base_url": "${DASHSCOPE_BASE_URL}",
            }
        )
        candidates.append(
            (
                "fast",
                "dashscope:qwen3.6-flash",
                "DASHSCOPE_API_KEY",
                {
                    "name": "dashscope",
                    "provider_type": "openai",
                    "api_key": "${DASHSCOPE_API_KEY}",
                    "api_base_url": "${DASHSCOPE_BASE_URL}",
                },
            )
        )

    if not providers:
        print("[skipped] set at least one of OPENAI_API_KEY / GEMINI_API_KEY / DASHSCOPE_API_KEY")
        raise SystemExit(0)

    # Deduplicate providers by name.
    seen: set[str] = set()
    unique_providers: list[dict] = []
    for p in providers:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique_providers.append(p)

    # Build the router from the candidate roles that have keys set.
    router: dict[str, str] = {}
    for role, spec, env_var, _provider in candidates:
        router.setdefault(role, spec)

    # Fill any unfilled role with the first configured spec so the example
    # never routes to a provider without credentials (SootheConfig would
    # otherwise default an unset role to ``openai:gpt-4o-mini``).
    if router:
        fallback_spec = next(iter(router.values()))
        for role in ("default", "fast", "think"):
            router.setdefault(role, fallback_spec)

    return SootheConfig.model_validate(
        {
            "providers": unique_providers,
            "router_profiles": [{"name": "multi", "router": router}],
            "active_router_profile": "multi",
        }
    )


async def run_role(factory: LLMFactory, role: str, *, user: str) -> None:
    """Run one chat turn with the model resolved for a role."""
    model = factory.create_chat_model(role)
    print(f"\n--- role={role}  model={model.model} ---")
    try:
        # Bound wait so an unreachable/stale-key provider fails fast instead
        # of hanging on litellm's internal retry for minutes.
        r = await asyncio.wait_for(
            model.ainvoke([SystemMessage(content="Be concise."), HumanMessage(content=user)]),
            timeout=30,
        )
    except (TimeoutError, Exception) as exc:
        # A provider may reject a stale/invalid key or be unreachable. Don't
        # abort the whole example — show the error and continue to the next role.
        print(f"  [skipped role {role}] {type(exc).__name__}: {str(exc)[:120]}")
        return
    print_response(r, label=f"{role} response")


async def main() -> None:
    banner("Example 08: Multi-provider factory via soothe_nano.llm")
    cfg = build_config()
    factory = LLMFactory(cfg)

    print("active router profile:", cfg.active_router_profile)
    print("providers:", [p.name for p in cfg.providers])

    # Each role resolves to a different provider/model — one adapter shape.
    await run_role(factory, "default", user="What is 2+2?")
    await run_role(factory, "fast", user="Name a red fruit.")
    await run_role(factory, "think", user="What is 3*7?")

    # Tool calling works across providers through the same adapter.
    model = factory.create_chat_model("default")
    bound = model.bind_tools([get_weather])
    try:
        r = await asyncio.wait_for(
            bound.ainvoke(
                [
                    SystemMessage(content="Use the get_weather tool."),
                    HumanMessage(content="What's the weather in Paris?"),
                ]
            ),
            timeout=30,
        )
    except (TimeoutError, Exception) as exc:
        print(f"\n--- tool-calling skipped: {type(exc).__name__}: {str(exc)[:120]}")
        return
    print("\n--- tool-calling across providers ---")
    print_response(r, label="default role + tools")
    if r.tool_calls:
        print("  ✓ native tool_calls")


if __name__ == "__main__":
    asyncio.run(main())
