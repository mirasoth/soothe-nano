"""Embedding / models diagnose checks."""

from __future__ import annotations

from typing import Any

from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)


async def check_models(config: Any | None = None) -> CategoryResult:
    """Verify a dedicated embedding profile is configured."""
    if config is None:
        checks = [
            CheckResult(
                name="embedding_role_configured",
                status=CheckStatus.SKIPPED,
                message="No agent config loaded",
            )
        ]
        return CategoryResult(
            category="models",
            status=aggregate_status([c.status for c in checks]),
            checks=checks,
        )

    embedding_profiles = getattr(config, "embedding_profile", None) or []
    resolve_model = getattr(config, "resolve_model", None)
    resolved = resolve_model("embedding") if callable(resolve_model) else None
    skillify = getattr(config, "skillify", None)
    skillify_model_role = getattr(skillify, "model_role", "embedding")
    skillify_resolved = resolve_model(skillify_model_role) if callable(resolve_model) else None
    embedding_dims = getattr(config, "embedding_dims", None)

    if not embedding_profiles:
        checks = [
            CheckResult(
                name="embedding_role_configured",
                status=CheckStatus.WARNING,
                message=(
                    "embedding_profile is not configured; embeddings may drift across restarts"
                ),
                details={
                    "resolved": resolved,
                    "skillify_model_role": skillify_model_role,
                    "skillify_resolved": skillify_resolved,
                    "embedding_dims": embedding_dims,
                    "remediation": (
                        "Set top-level embedding_profile with a stable model + dimensions, "
                        "for example model_role=openai:text-embedding-3-small "
                        "and embedding_dims=1536"
                    ),
                },
            )
        ]
    else:
        checks = [
            CheckResult(
                name="embedding_role_configured",
                status=CheckStatus.OK,
                message=f"Embedding role configured ({resolved})",
                details={
                    "embedding_profile_entries": len(embedding_profiles),
                    "skillify_model_role": skillify_model_role,
                    "skillify_resolved": skillify_resolved,
                    "embedding_dims": embedding_dims,
                },
            )
        ]

    return CategoryResult(
        category="models",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
    )
