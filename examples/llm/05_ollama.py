"""Example 05 — Ollama (local model) via ``soothe_nano.llm``.

Ollama runs models locally. litellm's ``ollama/`` prefix routes to the local
Ollama server (default http://localhost:11434). No API key required — this
example works fully offline once Ollama is running.

Prereq:
    ollama pull llama3.1   # or any model you have locally
    ollama serve           # if not already running

Run:
    python examples/llm/05_ollama.py
"""

from __future__ import annotations

import asyncio

from _helpers import banner, get_weather, print_response

from soothe_nano.llm import ChatLitellmModel

# Default local Ollama endpoint. Override with OLLAMA_API_BASE if yours differs.
OLLAMA_BASE = "http://localhost:11434"


async def main() -> None:
    banner("Example 05: Ollama (local) via soothe_nano.llm")

    model = ChatLitellmModel(
        model="ollama/llama3.1",
        api_base=OLLAMA_BASE,
        temperature=0,
    )
    print(f"model: {model.model}  api_base: {model.api_base}")

    from langchain_core.messages import HumanMessage, SystemMessage

    # 1) Plain chat
    r = await model.ainvoke(
        [SystemMessage(content="Be concise."), HumanMessage(content="List three primary colors.")]
    )
    print_response(r, label="plain chat")

    # 2) Native tool calling — Ollama's newer models support the OpenAI tools API.
    bound = model.bind_tools([get_weather])
    r = await bound.ainvoke(
        [
            SystemMessage(content="Use the get_weather tool to answer."),
            HumanMessage(content="What's the weather in Oslo?"),
        ]
    )
    print_response(r, label="tool-calling")
    # Note: some local models may emit tool calls as text; the adapter's
    # text-recovery safety net (recover_text_tool_calls) catches that.
    if r.tool_calls:
        print("  ✓ native tool_calls")
    else:
        print("  (no native tool_calls — the model may not support tool calling;")


if __name__ == "__main__":
    asyncio.run(main())
