"""Example 04 — Anthropic Claude (native provider) via ``soothe_nano.llm``.

litellm's ``anthropic/`` prefix routes to the Anthropic API. Claude supports
native tool calling and extended thinking; the adapter handles both.

Run:
    ANTHROPIC_API_KEY=... python examples/llm/04_anthropic.py
"""

from __future__ import annotations

import asyncio

from _helpers import banner, get_weather, print_response, require_env

from soothe_nano.llm import ChatLitellmModel


async def main() -> None:
    banner("Example 04: Anthropic Claude via soothe_nano.llm")
    require_env("ANTHROPIC_API_KEY")  # litellm reads ANTHROPIC_API_KEY

    model = ChatLitellmModel(
        model="anthropic/claude-3-5-sonnet-20241022",
        temperature=0,
    )
    print(f"model: {model.model}")

    from langchain_core.messages import HumanMessage, SystemMessage

    # 1) Plain chat
    r = await model.ainvoke(
        [
            SystemMessage(content="Be concise."),
            HumanMessage(content="What is the meaning of life in 10 words?"),
        ]
    )
    print_response(r, label="plain chat")

    # 2) Native tool calling
    bound = model.bind_tools([get_weather])
    r = await bound.ainvoke(
        [
            SystemMessage(content="Use the get_weather tool to answer."),
            HumanMessage(content="What's the weather in London?"),
        ]
    )
    print_response(r, label="tool-calling")
    assert r.tool_calls, "expected native tool_calls from Claude"


if __name__ == "__main__":
    asyncio.run(main())
