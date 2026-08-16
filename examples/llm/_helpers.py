"""Shared helpers for soothe-nano.llm provider examples.

These examples demonstrate the unified ``soothe_nano.llm`` module — the
litellm-backed LLM layer. Each example shows how to talk to a different
provider (Gemini, OpenRouter, Anthropic, Ollama, OpenAI, DashScope) through
the same :class:`~soothe_nano.llm.ChatLitellmModel` adapter, including native
tool calling and structured output.

Run any example directly:

    python examples/llm/01_openai.py
    GEMINI_API_KEY=... python examples/llm/02_gemini.py
    OPENROUTER_API_KEY=... python examples/llm/03_openrouter.py
    ANTHROPIC_API_KEY=... python examples/llm/04_anthropic.py
    python examples/llm/05_ollama.py
    python examples/llm/06_dashscope_custom_endpoint.py
    python examples/llm/07_structured_output.py
    python examples/llm/08_multi_provider_factory.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Ensure the standalone repo's `src/` is importable when run as a script.
_here = Path(__file__).resolve()
_src_root = _here.parents[2] / "src"
if _src_root.is_dir() and str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402


def banner(title: str) -> None:
    """Print a visible section banner."""
    print()
    print("=" * 64)
    print(f"  {title}")
    print("=" * 64)


def require_env(var: str) -> str:
    """Return the env var or exit with a helpful message."""
    val = os.environ.get(var, "").strip()
    if not val:
        print(
            f"\n[skipped] set {var} to run this example "
            f"(e.g. {var}=sk-... python {Path(sys.argv[0]).name})"
        )
        sys.exit(0)
    return val


def print_response(message: AIMessage, *, label: str = "Response") -> None:
    """Pretty-print an AIMessage and any tool calls it carries."""
    print(f"\n[{label}]")
    if isinstance(message.content, str) and message.content:
        print(message.content)
    tcs = getattr(message, "tool_calls", None) or []
    if tcs:
        print(f"  tool_calls ({len(tcs)}):")
        for tc in tcs:
            print(f"    - {tc.get('name')}({tc.get('args')})")
    if not message.content and not tcs:
        print("  (empty)")


async def chat_once(
    model: Any,
    *,
    system: str,
    user: str,
) -> AIMessage:
    """Run a single one-shot chat turn and return the AIMessage."""
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    return await model.ainvoke(messages)


# A trivial tool used across examples to demonstrate native tool calling.
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to look up, e.g. "Paris" or "Tokyo".
    """
    # In a real app this would call a weather API. The example returns a stub
    # so it runs without network access beyond the LLM provider itself.
    return f"It is sunny and 22°C in {city}."


def weather_tool_schema() -> list:
    """Return the weather tool as a list for ``bind_tools``."""
    return [get_weather]


__all__ = [
    "banner",
    "chat_once",
    "get_weather",
    "print_response",
    "require_env",
    "weather_tool_schema",
]
