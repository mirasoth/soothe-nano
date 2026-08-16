"""Example 03 — OpenRouter (multi-model gateway) via ``soothe_nano.llm``.

OpenRouter exposes many models behind one API. litellm's ``openrouter/``
prefix routes accordingly; the model string after the prefix is the
OpenRouter model slug (e.g. ``anthropic/claude-3.5-sonnet``). The same
adapter works unchanged.

Run:
    OPENROUTER_API_KEY=... python examples/llm/03_openrouter.py
"""

from __future__ import annotations

import asyncio

from _helpers import banner, get_weather, print_response, require_env

from soothe_nano.llm import ChatLitellmModel


async def main() -> None:
    banner("Example 03: OpenRouter via soothe_nano.llm")
    require_env("OPENROUTER_API_KEY")  # litellm reads OPENROUTER_API_KEY

    # The OpenRouter model slug is the part after ``openrouter/``.
    model = ChatLitellmModel(
        model="openrouter/anthropic/claude-3.5-sonnet",
        temperature=0,
    )
    print(f"model: {model.model}")

    from langchain_core.messages import HumanMessage, SystemMessage

    # 1) Plain chat
    r = await model.ainvoke(
        [
            SystemMessage(content="Be concise."),
            HumanMessage(content="Explain recursion in one sentence."),
        ]
    )
    print_response(r, label="plain chat")

    # 2) Native tool calling — OpenRouter passes tools through to the backing model.
    bound = model.bind_tools([get_weather])
    r = await bound.ainvoke(
        [
            SystemMessage(content="Use the get_weather tool to answer."),
            HumanMessage(content="What's the weather in Berlin?"),
        ]
    )
    print_response(r, label="tool-calling")
    assert r.tool_calls, "expected native tool_calls via OpenRouter"


if __name__ == "__main__":
    asyncio.run(main())
