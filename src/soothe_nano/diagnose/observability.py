"""Observability and tracing diagnose checks."""

from __future__ import annotations

import importlib.util
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

from soothe_sdk.observability.langfuse import resolve_langfuse_config_str

from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)

_DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com"


def _langfuse_host(lf: Any) -> str:
    host = resolve_langfuse_config_str(lf.host) or os.environ.get("LANGFUSE_HOST", "").strip()
    return (host or _DEFAULT_LANGFUSE_HOST).rstrip("/")


def _probe_langfuse_health(host: str, timeout: float = 3.0) -> CheckResult:
    """Probe Langfuse public health endpoint."""
    url = urljoin(host + "/", "api/public/health")
    try:
        req = urllib.request.Request(url, method="GET")  # noqa: S310
        req.add_header("User-Agent", "Soothe-Doctor/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            status = getattr(response, "status", 200)
            if status in (200, 204):
                return CheckResult(
                    name="langfuse_health",
                    status=CheckStatus.OK,
                    message=f"Langfuse healthy at {host}",
                    details={"host": host, "url": url, "http_status": status},
                )
            return CheckResult(
                name="langfuse_health",
                status=CheckStatus.WARNING,
                message=f"Langfuse health returned HTTP {status}",
                details={
                    "host": host,
                    "url": url,
                    "http_status": status,
                    "remediation": "Check Langfuse service status and observability.langfuse.host",
                },
            )
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return CheckResult(
                name="langfuse_health",
                status=CheckStatus.WARNING,
                message=f"Langfuse reachable but health endpoint returned HTTP {exc.code}",
                details={
                    "host": host,
                    "url": url,
                    "http_status": exc.code,
                    "remediation": "Verify host URL; credentials are checked separately",
                },
            )
        return CheckResult(
            name="langfuse_health",
            status=CheckStatus.WARNING,
            message=f"Langfuse health check HTTP error: {exc.code}",
            details={
                "host": host,
                "url": url,
                "remediation": "Check Langfuse service status and network access",
            },
        )
    except Exception as exc:
        return CheckResult(
            name="langfuse_health",
            status=CheckStatus.WARNING,
            message=f"Langfuse unreachable: {exc}",
            details={
                "host": host,
                "url": url,
                "remediation": "Check observability.langfuse.host and network connectivity",
            },
        )


def _check_langfuse_from_config(config: Any | None) -> list[CheckResult]:
    """Check Langfuse integration when enabled in ``observability.langfuse``."""
    if config is None:
        return [
            CheckResult(
                name="langfuse",
                status=CheckStatus.SKIPPED,
                message="Langfuse: no config loaded (skipped)",
            )
        ]

    observability = getattr(config, "observability", None)
    lf = getattr(observability, "langfuse", None) if observability is not None else None
    if lf is None or not getattr(lf, "enabled", False):
        return [
            CheckResult(
                name="langfuse",
                status=CheckStatus.SKIPPED,
                message="Langfuse disabled (observability.langfuse.enabled=false)",
                details={"enabled": False},
            )
        ]

    checks: list[CheckResult] = []
    if importlib.util.find_spec("langfuse") is None:
        checks.append(
            CheckResult(
                name="langfuse",
                status=CheckStatus.WARNING,
                message="Langfuse enabled but the langfuse package is not installed",
                details={
                    "enabled": True,
                    "remediation": "pip install langfuse",
                },
            )
        )
    else:
        checks.append(
            CheckResult(
                name="langfuse",
                status=CheckStatus.OK,
                message="Langfuse package installed",
                details={"enabled": True},
            )
        )

    pub = (
        resolve_langfuse_config_str(lf.public_key)
        or os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    )
    sec = (
        resolve_langfuse_config_str(lf.secret_key)
        or os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    )
    host = _langfuse_host(lf)
    cred_details: dict[str, Any] = {
        "enabled": True,
        "public_key_present": bool(pub),
        "secret_key_present": bool(sec),
        "host": host,
    }
    if pub and sec:
        checks.append(
            CheckResult(
                name="langfuse_credentials",
                status=CheckStatus.OK,
                message="Langfuse credentials available",
                details=cred_details,
            )
        )
    else:
        checks.append(
            CheckResult(
                name="langfuse_credentials",
                status=CheckStatus.WARNING,
                message="Langfuse enabled but credentials are incomplete",
                details={
                    **cred_details,
                    "remediation": (
                        "Set observability.langfuse.public_key / secret_key "
                        "(or LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY)"
                    ),
                },
            )
        )

    checks.append(_probe_langfuse_health(host))
    return checks


async def check_observability(config: Any | None = None) -> CategoryResult:
    """Check observability and tracing (Langfuse when enabled)."""
    checks = _check_langfuse_from_config(config)
    return CategoryResult(
        category="observability",
        status=aggregate_status([check.status for check in checks]),
        checks=checks,
    )
