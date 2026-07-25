"""Unit tests for soothe_nano diagnose API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from soothe_nano.diagnose import diagnose
from soothe_nano.diagnose.models import CheckStatus
from soothe_nano.diagnose.models_check import check_models
from soothe_nano.diagnose.tool_deps import check_tool_deps


@pytest.mark.asyncio
async def test_tool_deps_reports_rg_fd_git(monkeypatch: pytest.MonkeyPatch) -> None:
    from soothe_nano.diagnose import tool_deps as mod

    monkeypatch.setattr(mod, "_bin_version", lambda _p: "tool 14.0.0")

    fake_rg = MagicMock(return_value="/usr/bin/rg")
    fake_fd = MagicMock(return_value="/usr/bin/fd")
    monkeypatch.setattr(
        "soothe_deepagents.backends.grep_search.get_rg_bin",
        fake_rg,
        raising=False,
    )
    monkeypatch.setattr(
        "soothe_deepagents.backends.glob_search.get_fd_bin",
        fake_fd,
        raising=False,
    )
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)

    # Patch inside _check_rg/_check_fd import paths by stubbing modules used in try
    import soothe_deepagents.backends.glob_search as glob_search
    import soothe_deepagents.backends.grep_search as grep_search

    monkeypatch.setattr(grep_search, "get_rg_bin", lambda: "/usr/bin/rg")
    monkeypatch.setattr(glob_search, "get_fd_bin", lambda: "/usr/bin/fd")

    result = await check_tool_deps()
    assert result.category == "tool_deps"
    names = {c.name: c for c in result.checks}
    assert names["rg"].status == CheckStatus.OK
    assert names["fd"].status == CheckStatus.OK
    assert names["git"].status == CheckStatus.OK


@pytest.mark.asyncio
async def test_diagnose_filters_categories() -> None:
    results = await diagnose(None, categories=["tool_deps"])
    assert len(results) == 1
    assert results[0]["category"] == "tool_deps"


@pytest.mark.asyncio
async def test_providers_only_configured() -> None:
    from soothe_nano.diagnose.providers import check_providers

    p = SimpleNamespace(name="openrouter", api_key="sk-test", provider_type="openai")
    cfg = SimpleNamespace(
        providers=[p],
        router=SimpleNamespace(default="openrouter:model"),
        active_router_profile="default",
        embedding_model=None,
        embedding_profile=[],
    )
    result = await check_providers(cfg, live_llm=False)
    assert len(result.checks) == 1
    assert result.checks[0].name == "openrouter"
    assert result.checks[0].status == CheckStatus.OK


@pytest.mark.asyncio
async def test_providers_unused_env_ref_does_not_fail_category() -> None:
    """Alternate-profile providers with bad keys must not fail when unused."""
    from soothe_nano.diagnose.providers import check_providers

    dashscope = SimpleNamespace(name="dashscope", api_key="sk-ok", provider_type="openai")
    agnes = SimpleNamespace(name="agnes", api_key="${AGNESAI_API_KEY}", provider_type="openai")
    omlx = SimpleNamespace(name="omlx", api_key="local", provider_type="openai")
    cfg = SimpleNamespace(
        providers=[dashscope, agnes, omlx],
        router=SimpleNamespace(
            default="dashscope:glm",
            fast="dashscope:flash",
            think=None,
            image="dashscope:vision",
            ocr="omlx:ocr",
        ),
        active_router_profile="production",
        embedding_model="dashscope:text-embedding-v4",
        embedding_profile=[],
    )
    result = await check_providers(cfg, live_llm=False)
    by_name = {c.name: c for c in result.checks}
    assert by_name["dashscope"].status == CheckStatus.OK
    assert by_name["omlx"].status == CheckStatus.OK
    assert by_name["agnes"].status == CheckStatus.INFO
    assert "not used by active profile" in by_name["agnes"].message
    assert result.status == CheckStatus.OK


@pytest.mark.asyncio
async def test_providers_active_env_ref_fails_category() -> None:
    from soothe_nano.diagnose.providers import check_providers

    agnes = SimpleNamespace(name="agnes", api_key="${AGNESAI_API_KEY}", provider_type="openai")
    cfg = SimpleNamespace(
        providers=[agnes],
        router=SimpleNamespace(
            default="agnes:agnes-2.0-flash", think=None, fast=None, image=None, ocr=None
        ),
        active_router_profile="agnes-eval",
        embedding_model=None,
        embedding_profile=[],
    )
    result = await check_providers(cfg, live_llm=False)
    assert result.status == CheckStatus.ERROR
    assert result.checks[0].status == CheckStatus.ERROR


@pytest.mark.asyncio
async def test_observability_skips_when_langfuse_disabled() -> None:
    from soothe_nano.diagnose.observability import check_observability

    cfg = SimpleNamespace(observability=SimpleNamespace(langfuse=SimpleNamespace(enabled=False)))
    result = await check_observability(cfg)
    assert result.checks[0].status == CheckStatus.SKIPPED
    assert result.checks[0].name == "langfuse"


@pytest.mark.asyncio
async def test_embedding_role_warning_when_unset() -> None:
    config = SimpleNamespace(
        embedding_profile=[],
        embedding_dims=1536,
        resolve_model=lambda role: "openai:gpt-4o-mini",
        skillify=SimpleNamespace(model_role="embedding"),
    )
    result = await check_models(config)
    assert result.checks[0].status == CheckStatus.WARNING
    assert "not configured" in result.checks[0].message


@pytest.mark.asyncio
async def test_embedding_role_ok_when_configured() -> None:
    config = SimpleNamespace(
        embedding_profile=[{"model_role": "dashscope:text-embedding-v4", "embedding_dims": 1024}],
        skillify=SimpleNamespace(model_role="embedding"),
        embedding_dims=1024,
        resolve_model=lambda role: (
            "dashscope:text-embedding-v4" if role == "embedding" else "openai:gpt-4o"
        ),
    )
    result = await check_models(config)
    assert result.checks[0].status == CheckStatus.OK
