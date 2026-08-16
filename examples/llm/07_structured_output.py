"""Example 07 — Structured output via ``soothe_nano.llm``.

Shows the two structured-output paths:

1. ``ChatLitellmModel.with_structured_output(schema)`` — returns a runnable
   that parses the response into a pydantic model. Uses ``response_format:
   json_schema`` for providers that support it, falling back to text parsing.

2. ``invoke_structured_chat`` — the sanctioned entry point with a method
   fallback chain (function_calling → json_schema → json_mode) and
   post-validation against the schema. Use this in production code.

Run:
    OPENAI_API_KEY=sk-... python examples/llm/07_structured_output.py
"""

from __future__ import annotations

import asyncio

from _helpers import banner, require_env
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from soothe_nano.llm import ChatLitellmModel, invoke_structured_chat


class Sentiment(BaseModel):
    """A sentiment classification result."""

    label: str = Field(description="positive, negative, or neutral")
    confidence: float = Field(description="0.0 to 1.0", ge=0.0, le=1.0)
    reason: str = Field(description="one-sentence justification")


async def main() -> None:
    banner("Example 07: Structured output via soothe_nano.llm")
    require_env("OPENAI_API_KEY")

    model = ChatLitellmModel(
        model="openai/gpt-4o-mini",
        temperature=0,
    )
    print(f"model: {model.model}")

    messages = [
        SystemMessage(content="Classify the sentiment of the user's text."),
        HumanMessage(content="I really love how simple this is — it just works!"),
    ]

    # 1) with_structured_output — simple path
    structured = model.with_structured_output(Sentiment)
    result = await structured.ainvoke(messages)
    print(f"\n[with_structured_output] type={type(result).__name__}")
    print(f"  {result}")

    # 2) invoke_structured_chat — production path with method fallback + validation
    schema = Sentiment.model_json_schema()
    data = await invoke_structured_chat(
        model,
        messages,
        json_schema=schema,
        schema_name="Sentiment",
        strict=True,
    )
    parsed = Sentiment(**data)
    print("\n[invoke_structured_chat] validated pydantic instance:")
    print(f"  label={parsed.label}  confidence={parsed.confidence}")
    print(f"  reason={parsed.reason}")


if __name__ == "__main__":
    asyncio.run(main())
