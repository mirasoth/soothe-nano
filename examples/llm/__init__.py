"""Provider examples for the unified ``soothe_nano.llm`` module.

These examples show how to talk to different LLM providers through the single
:class:`~soothe_nano.llm.ChatLitellmModel` adapter (litellm-backed):

01_openai.py                     - OpenAI (native)
02_gemini.py                     - Google Gemini
03_openrouter.py                 - OpenRouter multi-model gateway
04_anthropic.py                  - Anthropic Claude
05_ollama.py                     - Ollama (local, no API key)
06_dashscope_custom_endpoint.py - DashScope / custom OpenAI-compatible (the regression test)
07_structured_output.py          - Structured output (json_schema + fallback chain)
08_multi_provider_factory.py     - Config-driven multi-provider routing by role

Each example is runnable directly:

    python examples/llm/01_openai.py

Most examples skip cleanly (exit 0) when the relevant API key is unset, so you
can run the whole folder without configuring every provider.
"""
