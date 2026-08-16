"""High-level ``BaseLLMClient`` for direct (non-agent-graph) LLM callers.

A simpler ``completion()`` / ``structured_completion()`` / ``embed()`` /
``rerank()`` surface for callers that talk to the LLM layer directly — cron
extraction, image understanding, embed/rerank services — without the
langchain ``BaseChatModel`` ceremony.

The concrete :class:`LLMClient` delegates to litellm so the direct path and
the agent-graph path share one provider engine and one credential resolver.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Abstract client interface for direct LLM access.

    Implementations route through litellm so credentials and provider
    capabilities are resolved the same way as the langchain adapter path.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.debug = bool(kwargs.pop("debug", False))

    @abstractmethod
    def completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> str:
        """Generate a chat completion, returning the assistant text."""

    @abstractmethod
    async def acompletion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> str:
        """Async chat completion."""

    @abstractmethod
    def structured_completion(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> T:
        """Generate a structured completion validated against a pydantic model."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single text."""

    @abstractmethod
    def embed_batch(self, chunks: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""

    @abstractmethod
    def rerank(self, query: str, chunks: list[str]) -> list[tuple[float, int, str]]:
        """Rerank chunks against a query, returning (score, index, text)."""


class LLMClient(BaseLLMClient):
    """litellm-backed concrete client for direct LLM access.

    For agent-graph callers, use :class:`~soothe_nano.llm.provider.ChatLitellmModel`
    via :class:`~soothe_nano.llm.factory.LLMFactory`. This client is for simpler
    direct-call paths (cron, embeddings, rerank, image understanding) where the
    langchain ``BaseChatModel`` interface isn't needed.
    """

    def __init__(
        self,
        model: str,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        embed_model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        import litellm

        self._litellm = litellm
        self.model = model
        self.api_base = api_base
        self.api_key = api_key
        self.embed_model = embed_model
        self.temperature = temperature

    def _call_kwargs(self, **extra: Any) -> dict[str, Any]:
        kw: dict[str, Any] = {"model": self.model, "temperature": self.temperature}
        if self.api_base:
            kw["api_base"] = self.api_base
        if self.api_key:
            kw["api_key"] = self.api_key
        kw.update(extra)
        return kw

    def completion(self, messages, temperature=0.7, max_tokens=None, stream=False, **kwargs):
        r = self._litellm.completion(
            messages=messages,
            stream=stream,
            max_tokens=max_tokens,
            temperature=temperature,
            **self._call_kwargs(**kwargs),
        )
        if stream:
            return r
        return r.choices[0].message.content

    async def acompletion(self, messages, temperature=0.7, max_tokens=None, stream=False, **kwargs):
        r = await self._litellm.acompletion(
            messages=messages,
            stream=stream,
            max_tokens=max_tokens,
            temperature=temperature,
            **self._call_kwargs(**kwargs),
        )
        if stream:
            return r
        return r.choices[0].message.content

    def structured_completion(
        self, messages, response_model, temperature=0.7, max_tokens=None, **kwargs
    ):
        """Structured completion via litellm ``response_format`` + pydantic parse."""
        import json

        schema = response_model.model_json_schema()
        r = self._litellm.completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
            **self._call_kwargs(**kwargs),
        )
        content = r.choices[0].message.content
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            import re

            m = re.search(r"\{.*\}", content or "", re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        return response_model.model_validate(data)

    def embed(self, text: str) -> list[float]:
        r = self._litellm.embedding(
            model=self.embed_model or self.model,
            input=[text],
            **self._call_kwargs(),
        )
        return r.data[0]["embedding"]

    def embed_batch(self, chunks: list[str]) -> list[list[float]]:
        r = self._litellm.embedding(
            model=self.embed_model or self.model,
            input=chunks,
            **self._call_kwargs(),
        )
        return [d["embedding"] for d in r.data]

    def rerank(self, query: str, chunks: list[str]) -> list[tuple[float, int, str]]:
        """Rerank via litellm's rerank endpoint (DashScope text-rerank, Cohere, ...)."""
        r = self._litellm.rerank(
            model=self.embed_model or self.model,
            query=query,
            documents=chunks,
            **self._call_kwargs(),
        )
        out: list[tuple[float, int, str]] = []
        for item in r.results:
            out.append(
                (
                    float(getattr(item, "relevance_score", 0.0)),
                    int(getattr(item, "index", 0)),
                    chunks[int(getattr(item, "index", 0))],
                )
            )
        return sorted(out, key=lambda x: x[0], reverse=True)


__all__ = [
    "BaseLLMClient",
    "LLMClient",
]
