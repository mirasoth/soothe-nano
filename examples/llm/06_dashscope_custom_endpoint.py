"""Example 06 — DashScope / custom OpenAI-compatible endpoint via ``soothe_nano.llm``.

This is the provider class that motivated the unified module: custom
OpenAI-compatible endpoints (DashScope, oMLX, vLLM, LMStudio) routed through
litellm's ``openai/`` prefix plus an ``api_base`` override.

Before the unified module, the old ``OpenAICompatModelWrapper`` dropped the
bound ``tools=`` kwarg on the way to the provider (it called
``RunnableBinding._agenerate`` directly, bypassing the kwargs merge), so the
model never received tools and emitted tool-call intent as JSON-as-text.
``ChatLitellmModel`` passes ``tools=`` directly to litellm, so native tool
calls work — this example is also the regression test for that fix.

Run:
    DASHSCOPE_API_KEY=... \
    DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
    python examples/llm/06_dashscope_custom_endpoint.py
"""

from __future__ import annotations

import asyncio
import os

from _helpers import banner, get_weather, print_response, require_env

from soothe_nano.llm import ChatLitellmModel


async def main() -> None:
    banner("Example 06: DashScope (custom OpenAI-compatible) via soothe_nano.llm")
    api_key = require_env("DASHSCOPE_API_KEY")
    api_base = os.environ.get(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # ``openai/`` prefix + api_base override = any OpenAI-compatible server.
    model = ChatLitellmModel(
        model="openai/qwen3.6-flash",
        api_base=api_base,
        api_key=api_key,
        temperature=0,
    )
    print(f"model: {model.model}  api_base: {model.api_base}")

    from langchain_core.messages import HumanMessage, SystemMessage

    # 1) Plain chat
    r = await model.ainvoke(
        [
            SystemMessage(content="Be concise."),
            HumanMessage(content="What is the capital of Japan?"),
        ]
    )
    print_response(r, label="plain chat")

    # 2) Native tool calling — THE REGRESSION TEST.
    #    This must return structured tool_calls (previously returned []
    #    with JSON-as-text content because tools= was dropped).
    bound = model.bind_tools([get_weather])
    r = await bound.ainvoke(
        [
            SystemMessage(content="Use the get_weather tool to answer."),
            HumanMessage(content="What's the weather in Paris?"),
        ]
    )
    print_response(r, label="tool-calling")
    assert r.tool_calls, (
        "REGRESSION: expected native tool_calls from DashScope. "
        "The unified module must pass tools= to litellm so the model emits "
        "structured tool_calls, not JSON-as-text."
    )
    print("  ✓ regression check passed — native tool_calls work")


if __name__ == "__main__":
    asyncio.run(main())
