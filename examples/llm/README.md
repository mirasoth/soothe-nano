# `soothe_nano.llm` provider examples

These examples demonstrate the unified `soothe_nano.llm` module — the
litellm-backed LLM layer. Every provider is reached through the same
`ChatLitellmModel` adapter; only the litellm **model string** differs.

## Why this exists

Before the unified module, the `OpenAICompatModelWrapper` dropped the bound
`tools=` kwarg on the way to custom OpenAI-compatible endpoints (DashScope,
oMLX, vLLM): it called `RunnableBinding._agenerate` directly, bypassing the
kwargs merge. The model never received `tools=`, so it emitted tool-call
intent as JSON-as-text and `AIMessage.tool_calls` stayed empty — the agent
answered from injected context or hallucination instead of investigating.

`ChatLitellmModel` fixes this by construction: `bind_tools` stores tool
schemas on the instance, and `_generate`/`_agenerate`/`_astream` pass them
directly to `litellm.completion(tools=...)`. litellm returns native
structured `tool_calls` for DashScope (verified non-streaming **and**
streaming). Example 06 is the regression test for this fix.

## Run

Each example is standalone and runnable directly. Most skip cleanly (exit 0)
when the relevant API key is unset, so you can run the whole folder without
configuring every provider.

```sh
# OpenAI
OPENAI_API_KEY=sk-... python examples/llm/01_openai.py

# Google Gemini
GEMINI_API_KEY=... python examples/llm/02_gemini.py

# OpenRouter (multi-model gateway)
OPENROUTER_API_KEY=... python examples/llm/03_openrouter.py

# Anthropic Claude
ANTHROPIC_API_KEY=... python examples/llm/04_anthropic.py

# Ollama (local, no key; run `ollama serve` first)
python examples/llm/05_ollama.py

# DashScope / custom OpenAI-compatible endpoint (the regression test)
DASHSCOPE_API_KEY=... \
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
python examples/llm/06_dashscope_custom_endpoint.py

# Structured output (pydantic schema validation)
OPENAI_API_KEY=sk-... python examples/llm/07_structured_output.py

# Multi-provider factory (config-driven routing by role)
OPENAI_API_KEY=sk-... GEMINI_API_KEY=... python examples/llm/08_multi_provider_factory.py
```

## litellm model-string conventions

The provider is selected by the **prefix** of the model string:

| Prefix | Provider | Example |
|---|---|---|
| `openai/` | OpenAI, or any custom OpenAI-compatible endpoint (+ `api_base`) | `openai/gpt-4o-mini` |
| `gemini/` | Google Gemini | `gemini/gemini-2.0-flash` |
| `openrouter/` | OpenRouter (model slug follows) | `openrouter/anthropic/claude-3.5-sonnet` |
| `anthropic/` | Anthropic Claude | `anthropic/claude-3-5-sonnet-20241022` |
| `ollama/` | Ollama (local) | `ollama/llama3.1` |
| `groq/` | Groq | `groq/llama-3.1-8b-instant` |
| `vertex_ai/` | Google Vertex AI | `vertex_ai/gemini-1.5-pro` |

Custom OpenAI-compatible endpoints (DashScope, oMLX, vLLM, LMStudio) use the
`openai/` prefix **plus an `api_base` override** — see example 06.

## What the adapter provides

- **Native tool calling** — `bind_tools([...])` stores schemas on the instance;
  `_generate` passes `tools=` directly to litellm.
- **Streaming** — `_astream` yields `AIMessageChunk` with `tool_call_chunks`.
- **Structured output** — `with_structured_output(schema)` (json_schema) with
  instructor/text-parse fallback for providers that reject `json_schema`.
- **Thinking-token stripping** — inline `<think>...</think>` blocks removed.
- **Broken-streaming self-heal** — if `stream=True` returns "No generations
  found in stream", the adapter retries non-streaming automatically.
- **Token observability** — `ChatResult.llm_output` carries `token_usage` for
  the Langfuse callback chain.
