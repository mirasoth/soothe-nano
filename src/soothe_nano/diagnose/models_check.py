"""Embedding / models diagnose checks.

Delegates category-result construction to the Rust extension. Python
retains the config attribute introspection.
"""

from __future__ import annotations

from typing import Any

from soothe_nano._rust_compat import (
    check_models_no_config_rust,
    check_models_no_profile_rust,
    check_models_ok_rust,
)
from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
)


def _rebuild_category(result_dict: dict[str, Any]) -> CategoryResult:
    """Rebuild a Python CategoryResult from a Rust-produced dict."""
    checks = [
        CheckResult(
            name=c["name"],
            status=CheckStatus(c["status"]),
            message=c["message"],
            details=c.get("details", {}),
        )
        for c in result_dict["checks"]
    ]
    return CategoryResult(
        category=result_dict["category"],
        status=CheckStatus(result_dict["status"]),
        checks=checks,
        message=result_dict.get("message"),
    )


async def check_models(config: Any | None = None) -> CategoryResult:
    """Verify a dedicated embedding profile is configured."""
    if config is None:
        result_dict = check_models_no_config_rust()
        return _rebuild_category(result_dict)

    embedding_profile = getattr(config, "embedding_profile", None)
    resolve_model = getattr(config, "resolve_model", None)
    resolved = resolve_model("embedding") if callable(resolve_model) else None
    skillify = getattr(config, "skillify", None)
    skillify_model_role = getattr(skillify, "model_role", "embedding")
    skillify_resolved = resolve_model(skillify_model_role) if callable(resolve_model) else None
    embedding_dims = getattr(config, "embedding_dims", None)

    if not embedding_profile:
        result_dict = check_models_no_profile_rust(
            resolved=resolved,
            skillify_model_role=skillify_model_role,
            skillify_resolved=skillify_resolved,
            embedding_dims=embedding_dims,
        )
    else:
        result_dict = check_models_ok_rust(
            resolved=resolved or "",
            skillify_model_role=skillify_model_role,
            skillify_resolved=skillify_resolved,
            embedding_dims=embedding_dims,
        )

    return _rebuild_category(result_dict)
