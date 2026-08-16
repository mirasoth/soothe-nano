"""Example 01 — OpenAI (native provider) via ``soothe_nano.llm``.

The simplest provider: litellm's ``openai/`` prefix routes to the official
OpenAI API. ``ChatLitellmModel`` passes ``tools=`` directly to litellm, so the
model returns native structured ``tool_calls``.

Run:
    OPENAI_API_KEY=sk-... python examples/llm/01_openai.py
"""

from __future__ import annotations

import asyncio

from _helpers import banner, get_weather, print_response, require_env

from soothe_nano.llm import ChatLitellmModel


async def main() -> None:
    banner("Example 01: OpenAI via soothe_nano.llm")
    api_key = require_env("OPENAI_API_KEY")

    model = ChatLitellmModel(
        model="openai/gpt-4o-mini",
        api_key=api_key,
        temperature=0,
    )
    print(f"model: {model.model}")

    # 1) Plain chat
    from langchain_core.messages import HumanMessage, SystemMessage

    r = await model.ainvoke(
        [SystemMessage(content="Be concise."), HumanMessage(content="What is 2+2?")]
    )
    print_response(r, label="plain chat")

    # 2) Native tool calling
    bound = model.bind_tools([get_weather])
    r = await bound.ainvoke(
        [
            SystemMessage(content="Use the get_weather tool to answer."),
            HumanMessage(content="What's the weather in Paris?"),
        ]
    )
    print_response(r, label="tool-calling")
    assert r.tool_calls, "expected native tool_calls (this is the regression fix)"


if __name__ == "__main__":
    asyncio.run(main())
