"""Unified multi-provider LLM module.

A single litellm-backed module covering both the agent-graph path and the
direct-call path. litellm is the universal provider engine; the
``BaseLLMClient`` pattern forms the high-level direct-call surface, while
``LLMFactory`` + ``ProviderRegistry`` resolve config to litellm model strings.

Architecture:
- :class:`ChatLitellmModel` — langchain ``BaseChatModel`` adapter over litellm
  (the agent-graph path; fixes the tool-calling regression by construction).
- :class:`LLMFactory` / :class:`ProviderRegistry` — resolve ``provider:model``
  specs from :class:`SootheConfig` to litellm model strings + capabilities.
- :class:`BaseLLMClient` / :class:`LLMClient` — direct-call surface for cron,
  embeddings, rerank, image understanding.
- :mod:`structured` / :mod:`observability` — re-export the proven nano helpers
  (method fallback chain, Langfuse token tracking).
- :mod:`tools` — tool binding + tool-call extraction + text-embedded recovery.

Usage:
    from soothe_nano.llm import LLMFactory, ChatLitellmModel

    factory = LLMFactory(config)
    model = factory.create_chat_model("default")  # ChatLitellmModel
    bound = model.bind_tools([get_weather, search])
    # bound._generate passes tools= directly to litellm → native tool_calls
"""

from __future__ import annotations

from soothe_nano.llm.base import BaseLLMClient, LLMClient
from soothe_nano.llm.exceptions import ContentPolicyError, LLMError, StructuredOutputError
from soothe_nano.llm.factory import LLMFactory
from soothe_nano.llm.invoke_policy import (
    EnhancedTimeoutError,
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
    run_with_llm_call_policy_sync,
)
from soothe_nano.llm.observability import (
    SootheLLMTokenUsageCallbackHandler,
    SootheTokenUsageChatModel,
    bind_llm_token_observability,
    extract_token_counts_from_llm_result,
    get_llm_token_usage_callback_handler,
)
from soothe_nano.llm.provider import ChatLitellmModel
from soothe_nano.llm.registry import ProviderCapabilities, ProviderRegistry, ResolvedProvider
from soothe_nano.llm.response_text import (
    llm_response_text,
    parse_json_object,
    text_from_message_content,
)
from soothe_nano.llm.schema_wire import (
    DEFAULT_DIRECT_LLM_SCHEMA_NAME,
    build_json_schema_response_format,
    resolve_schema_name,
    validate_response_schema,
)
from soothe_nano.llm.structured import (
    ensure_json_keyword_in_messages,
    invoke_structured_chat,
    invoke_structured_chat_typed,
    messages_contain_json_keyword,
    normalize_structured_result,
    post_validate_structured_dict,
    wrap_json_keyword_safe,
)
from soothe_nano.llm.thinking import ThinkingStreamFilter, strip_thinking
from soothe_nano.llm.traced import (
    ainvoke_structured_traced,
    ainvoke_traced,
    build_traced_invoke_config,
)
from soothe_nano.llm.tools import (
    bind_tools_litellm,
    extract_tool_calls_from_litellm,
    recover_text_tool_calls,
)
from soothe_nano.llm.types import ModelRole, ProviderType

__all__ = [
    # Engine
    "ChatLitellmModel",
    "LLMFactory",
    "ProviderRegistry",
    "ProviderCapabilities",
    "ResolvedProvider",
    # Direct-call client
    "BaseLLMClient",
    "LLMClient",
    # Types
    "ModelRole",
    "ProviderType",
    # Tool binding + extraction
    "bind_tools_litellm",
    "extract_tool_calls_from_litellm",
    "recover_text_tool_calls",
    # Structured output
    "invoke_structured_chat",
    "invoke_structured_chat_typed",
    "StructuredOutputError",
    "ensure_json_keyword_in_messages",
    "messages_contain_json_keyword",
    "normalize_structured_result",
    "post_validate_structured_dict",
    "wrap_json_keyword_safe",
    # Observability
    "SootheTokenUsageChatModel",
    "SootheLLMTokenUsageCallbackHandler",
    "get_llm_token_usage_callback_handler",
    "bind_llm_token_observability",
    "extract_token_counts_from_llm_result",
    # Invoke policy
    "EnhancedTimeoutError",
    "await_with_llm_call_policy",
    "llm_rate_limit_config_from",
    "run_with_llm_call_policy_sync",
    # Response text
    "llm_response_text",
    "parse_json_object",
    "text_from_message_content",
    # Schema helpers
    "DEFAULT_DIRECT_LLM_SCHEMA_NAME",
    "build_json_schema_response_format",
    "resolve_schema_name",
    "validate_response_schema",
    # Thinking filter
    "ThinkingStreamFilter",
    "strip_thinking",
    # Unified traced LLM invocation
    "ainvoke_traced",
    "ainvoke_structured_traced",
    "build_traced_invoke_config",
    # Exceptions
    "LLMError",
    "ContentPolicyError",
]
