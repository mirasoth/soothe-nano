"""LLM provider connectivity diagnose checks."""

from __future__ import annotations

import asyncio
from typing import Any

from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)

_ROUTER_ROLES = ("default", "think", "fast", "image", "ocr")


def _unresolved_env_ref(value: str | None) -> bool:
    return bool(value and "${" in value)


def _provider_from_spec(spec: str | None) -> str | None:
    """Extract provider name from a ``provider:model`` router/embedding spec."""
    if not spec or not isinstance(spec, str):
        return None
    provider, _, model = spec.partition(":")
    if not model:
        return None
    provider = provider.strip()
    return provider or None


def active_provider_names(config: Any) -> set[str]:
    """Providers referenced by the active router profile and embedding config.

    Unused ``providers[]`` entries (e.g. alternate profile backends) must not
    fail the providers category when the active profile is healthy.
    """
    names: set[str] = set()

    def _add(spec: str | None) -> None:
        name = _provider_from_spec(spec)
        if name:
            names.add(name)

    router = getattr(config, "router", None)
    if router is not None:
        for role in _ROUTER_ROLES:
            _add(getattr(router, role, None))

    _add(getattr(config, "embedding_model", None))

    for entry in getattr(config, "embedding_profile", None) or []:
        if isinstance(entry, dict):
            _add(entry.get("model_role"))
        else:
            _add(getattr(entry, "model_role", None))

    return names


def _demote_inactive_provider_check(
    check: CheckResult,
    *,
    active: set[str],
    profile_name: str | None,
) -> CheckResult:
    """Downgrade credential failures for providers not used by the active profile."""
    if not active or check.name in active:
        return check
    if check.status not in (CheckStatus.ERROR, CheckStatus.WARNING):
        return check

    profile_label = profile_name or "active"
    return CheckResult(
        name=check.name,
        status=CheckStatus.INFO,
        message=(
            f"{check.message} (not used by active profile '{profile_label}')"
            if check.message
            else f"{check.name}: not used by active profile '{profile_label}'"
        ),
        details={
            **check.details,
            "active_profile": profile_name,
            "required_by_active_profile": False,
            "impact": "Does not affect the active router/embedding providers",
        },
    )


async def _check_provider_credentials(
    provider_name: str,
    api_key: str | None,
    provider_type: str,
) -> CheckResult:
    """Validate that a configured provider has usable credentials."""
    if _unresolved_env_ref(api_key):
        return CheckResult(
            name=provider_name,
            status=CheckStatus.ERROR,
            message=f"{provider_name}: API key still contains unresolved ${{ENV}} reference",
            details={
                "provider_type": provider_type,
                "remediation": f"Export the env var referenced by {provider_name}.api_key",
            },
        )

    if provider_type == "ollama":
        return CheckResult(
            name=provider_name,
            status=CheckStatus.OK,
            message=f"{provider_name}: configured (local/keyless provider_type={provider_type})",
            details={"provider_type": provider_type, "api_key_present": bool(api_key)},
        )

    if not api_key:
        return CheckResult(
            name=provider_name,
            status=CheckStatus.ERROR,
            message=f"{provider_name}: API key not set",
            details={
                "provider_type": provider_type,
                "remediation": (
                    f"Set {provider_name}.api_key in config or the corresponding env var"
                ),
            },
        )

    return CheckResult(
        name=provider_name,
        status=CheckStatus.OK,
        message=f"{provider_name}: credentials present (provider_type={provider_type})",
        details={"provider_type": provider_type, "api_key_present": True},
    )


async def _live_invoke_default(config: Any) -> CheckResult:
    """Optional live invoke against the default router model."""
    try:
        from langchain_core.messages import HumanMessage

        from soothe_nano.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )
        from soothe_nano.llm.observability import create_llm_call_metadata

        model = config.create_chat_model("default")
        llm_config = llm_rate_limit_config_from(config).model_copy(
            update={
                "call_timeout_seconds": 5,
                "call_timeout_max_seconds": 5,
                "max_rate_limit_retries": 1,
                "max_timeout_retries": 0,
            }
        )

        async def test_call() -> Any:
            return await model.ainvoke(
                [HumanMessage(content="ping")],
                config={
                    "metadata": create_llm_call_metadata(
                        purpose="health_check",
                        component="nano.diagnose.providers",
                        phase="doctor",
                        provider="default",
                    )
                },
            )

        await await_with_llm_call_policy(test_call, config=llm_config)
        default = getattr(getattr(config, "router", None), "default", None)
        return CheckResult(
            name="default_model_live",
            status=CheckStatus.OK,
            message=f"Default model live invoke OK ({default})",
            details={"default": default},
        )
    except TimeoutError:
        return CheckResult(
            name="default_model_live",
            status=CheckStatus.WARNING,
            message="Default model live invoke timed out (5s)",
            details={"impact": "Provider may be slow or unreachable"},
        )
    except Exception as exc:
        error_msg = str(exc)
        lower = error_msg.lower()
        if "api_key" in lower or "unauthorized" in lower or "401" in lower:
            return CheckResult(
                name="default_model_live",
                status=CheckStatus.ERROR,
                message="Default model live invoke failed: invalid credentials",
                details={"error": error_msg, "remediation": "Check provider API key"},
            )
        if "rate limit" in lower:
            return CheckResult(
                name="default_model_live",
                status=CheckStatus.WARNING,
                message="Default model live invoke rate limited",
                details={"error": error_msg},
            )
        return CheckResult(
            name="default_model_live",
            status=CheckStatus.ERROR,
            message=f"Default model live invoke failed: {error_msg}",
            details={"remediation": "Check provider endpoint and network"},
        )


async def check_providers(
    config: Any | None = None,
    *,
    live_llm: bool = False,
) -> CategoryResult:
    """Check configured LLM providers (credentials; optional live invoke)."""
    if config is None:
        return CategoryResult(
            category="providers",
            status=CheckStatus.SKIPPED,
            checks=[
                CheckResult(
                    name="providers",
                    status=CheckStatus.SKIPPED,
                    message="Skipped (no config loaded)",
                )
            ],
        )

    providers = getattr(config, "providers", None) or []
    if not providers:
        return CategoryResult(
            category="providers",
            status=CheckStatus.ERROR,
            checks=[
                CheckResult(
                    name="providers",
                    status=CheckStatus.ERROR,
                    message="No LLM providers configured",
                    details={
                        "remediation": (
                            "Add providers[] in nano.yml or set OPENAI_API_KEY / ANTHROPIC_API_KEY"
                        ),
                    },
                )
            ],
        )

    active = active_provider_names(config)
    profile_name = getattr(config, "active_router_profile", None)
    provider_by_name = {p.name: p for p in providers}

    tasks = [_check_provider_credentials(p.name, p.api_key, p.provider_type) for p in providers]
    checks = [
        _demote_inactive_provider_check(c, active=active, profile_name=profile_name)
        for c in await asyncio.gather(*tasks)
    ]

    # Missing providers referenced by the active profile are hard failures.
    for name in sorted(active):
        if name not in provider_by_name:
            checks.append(
                CheckResult(
                    name=name,
                    status=CheckStatus.ERROR,
                    message=(
                        f"{name}: referenced by active profile "
                        f"'{profile_name or 'active'}' but not in providers[]"
                    ),
                    details={
                        "active_profile": profile_name,
                        "required_by_active_profile": True,
                        "remediation": f"Add a providers[] entry named '{name}'",
                    },
                )
            )

    if live_llm:
        checks.append(await _live_invoke_default(config))

    # Category health follows active-profile providers (+ live invoke), not unused ones.
    status_checks = [
        c
        for c in checks
        if c.name == "default_model_live"
        or not active
        or c.name in active
        or c.details.get("required_by_active_profile") is True
    ]
    return CategoryResult(
        category="providers",
        status=aggregate_status([c.status for c in status_checks]),
        checks=checks,
    )
