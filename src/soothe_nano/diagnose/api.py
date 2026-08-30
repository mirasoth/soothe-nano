"""Public nano diagnose API for soothed doctor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from soothe_nano.diagnose.models import CategoryResult

VITAL_CATEGORIES: list[str] = [
    "tool_deps",
    "providers",
    "observability",
]

DEEP_CATEGORIES: list[str] = [
    "mcp_servers",
    "vector_stores",
    "models",
    "protocols",
]

ALL_CATEGORIES: list[str] = [*VITAL_CATEGORIES, *DEEP_CATEGORIES]


async def diagnose(
    config: Any | None = None,
    *,
    deep: bool = False,
    live_llm: bool = False,
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run nano-owned diagnose categories and return dict-contract results.

    Args:
        config: Duck-typed agent config (providers, mcp_servers, …). Do not
            pass host-only types that create reverse imports.
        deep: Include deep categories when `categories` is None.
        live_llm: Perform a live invoke against `router.default`.
        categories: Explicit category filter (subset of nano categories).

    Returns:
        List of category dicts matching `CategoryResult.to_dict()`.
    """
    from soothe_nano.diagnose.mcp import check_mcp_servers
    from soothe_nano.diagnose.models_check import check_models
    from soothe_nano.diagnose.observability import check_observability
    from soothe_nano.diagnose.protocols import check_protocols
    from soothe_nano.diagnose.providers import check_providers
    from soothe_nano.diagnose.tool_deps import check_tool_deps
    from soothe_nano.diagnose.vector_stores import check_vector_stores

    check_methods: dict[str, Callable[[], Awaitable[CategoryResult]]] = {
        "tool_deps": check_tool_deps,
        "providers": lambda: check_providers(config, live_llm=live_llm),
        "observability": lambda: check_observability(config),
        "mcp_servers": lambda: check_mcp_servers(config),
        "vector_stores": lambda: check_vector_stores(config),
        "models": lambda: check_models(config),
        "protocols": lambda: check_protocols(config),
    }

    if categories is not None:
        selected = [c for c in categories if c in check_methods]
    else:
        selected = list(VITAL_CATEGORIES)
        if deep:
            selected.extend(DEEP_CATEGORIES)

    results: list[dict[str, Any]] = []
    for name in selected:
        result = await check_methods[name]()
        results.append(result.to_dict())
    return results
