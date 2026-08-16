"""Example 02 — Google Gemini via ``soothe_nano.llm``.

litellm's ``gemini/`` prefix routes to the Gemini API. The same
``ChatLitellmModel`` adapter works unchanged — only the model string differs.
Native tool calling works out of the box.

Run:
    GEMINI_API_KEY=... python examples/llm/02_gemini.py
"""

from __future__ import annotations

import asyncio

from _helpers import banner, get_weather, print_response, require_env

from soothe_nano.llm import ChatLitellmModel


async def main() -> None:
    banner("Example 02: Google Gemini via soothe_nano.llm")
    require_env("GEMINI_API_KEY")  # litellm reads GEMINI_API_KEY automatically

    model = ChatLitellmModel(
        model="gemini/gemini-2.0-flash",
        temperature=0,
    )
    print(f"model: {model.model}")

    from langchain_core.messages import HumanMessage, SystemMessage

    # 1) Plain chat
    r = await model.ainvoke(
        [SystemMessage(content="Be concise."), HumanMessage(content="Name the capital of France.")]
    )
    print_response(r, label="plain chat")

    # 2) Native tool calling
    bound = model.bind_tools([get_weather])
    r = await bound.ainvoke(
        [
            SystemMessage(content="Use the get_weather tool to answer."),
            HumanMessage(content="What's the weather in Tokyo?"),
        ]
    )
    print_response(r, label="tool-calling")
    assert r.tool_calls, "expected native tool_calls from Gemini"


if __name__ == "__main__":
    asyncio.run(main())
