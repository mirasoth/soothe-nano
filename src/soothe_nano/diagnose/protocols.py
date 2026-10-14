"""Protocol backend import diagnose checks.

Delegates check-result construction and status aggregation to the Rust
extension. Python retains the ``__import__`` probing.
"""

from __future__ import annotations

from typing import Any

from soothe_nano._rust_compat import check_protocols_from_results_rust
from soothe_nano.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
)

_PROTOCOL_MODULES: list[tuple[str, str]] = [
    ("MemU Memory", "soothe_nano.backends.memory.memu_adapter"),
    ("PostgreSQL Durability", "soothe_nano.backends.durability.postgresql"),
    ("SQLite Durability", "soothe_nano.backends.durability.sqlite"),
    ("PGVector", "soothe_nano.backends.vector_store.pgvector"),
    ("Weaviate", "soothe_nano.backends.vector_store.weaviate"),
    ("sqlite_vec", "soothe_nano.backends.vector_store.sqlite_vec"),
]


def _check_import(module_path: str, name: str) -> CheckResult:
    """Check if a module can be imported."""
    try:
        __import__(module_path)
        return CheckResult(
            name=name,
            status=CheckStatus.OK,
            message=f"{name} import successful",
        )
    except ImportError as e:
        return CheckResult(
            name=name,
            status=CheckStatus.ERROR,
            message=f"{name} import failed: {e}",
            details={"module": module_path, "remediation": f"Install required package for {name}"},
        )


async def check_protocols(config: Any | None = None) -> CategoryResult:  # noqa: ARG001
    """Check protocol backends (import-only)."""
    # Run imports and collect results for Rust delegation.
    import_results: list[tuple[str, str, bool, str]] = []
    checks: list[CheckResult] = []
    for name, module_path in _PROTOCOL_MODULES:
        try:
            __import__(module_path)
            import_results.append((name, module_path, True, ""))
            checks.append(
                CheckResult(name=name, status=CheckStatus.OK, message=f"{name} import successful")
            )
        except ImportError as e:
            import_results.append((name, module_path, False, str(e)))
            checks.append(
                CheckResult(
                    name=name,
                    status=CheckStatus.ERROR,
                    message=f"{name} import failed: {e}",
                    details={
                        "module": module_path,
                        "remediation": f"Install required package for {name}",
                    },
                )
            )

    # Delegate category dict construction to Rust, then rebuild Python dataclasses.
    result_dict = check_protocols_from_results_rust(import_results)
    return CategoryResult(
        category=result_dict["category"],
        status=CheckStatus(result_dict["status"]),
        checks=checks,
        message=result_dict.get("message"),
    )
