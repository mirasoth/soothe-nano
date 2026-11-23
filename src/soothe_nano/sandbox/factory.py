"""Sandbox backend factory: registry-based backend construction.

Each sandbox backend (ArcBox, future Docker/Kata/gVisor/…) registers a
factory function here. The :class:`AgentBuilder` calls
:func:`create_sandbox_backend` with a :class:`SandboxBackendConfig`, which
dispatches to the registered factory by ``type``. New backends are added by:

1. Defining a backend config model in ``config/models.py``.
2. Implementing the backend class (inheriting ``BaseSandbox``).
3. Registering a factory here via :func:`register_backend_factory`.

This decouples the builder from any specific backend — it never imports a
backend module directly; the factory does the lazy import.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from soothe_nano.config.models import (
    ArcBoxBackendConfig,
    OsLocalSandboxConfig,
    SandboxBackendConfig,
    _register_backend_type,
)

if TYPE_CHECKING:
    from soothe_deepagents.backends.protocol import BackendProtocol

logger = logging.getLogger(__name__)

# Register the built-in backend types.
_register_backend_type("arcbox")
_register_backend_type("os_sandbox")


# Type of a factory function: takes the backend-specific config and returns
# a BackendProtocol (specifically a SandboxBackendProtocol).
BackendFactory = Callable[[Any], "BackendProtocol"]


class SandboxBackendFactory:
    """Registry of sandbox backend factory functions, keyed by type name.

    Backends register themselves at import time (or explicitly). The builder
    resolves the factory by ``SandboxBackendConfig.type`` and delegates
    construction. This is the single extension point for new backends.
    """

    _factories: dict[str, BackendFactory] = {}

    @classmethod
    def register(cls, backend_type: str, factory: BackendFactory) -> None:
        """Register a factory function for a backend type.

        Args:
            backend_type: Type discriminator string (e.g. ``"arcbox"``).
            factory: Callable that takes the backend-specific config model
                and returns a ``BackendProtocol``.
        """
        cls._factories[backend_type] = factory
        _register_backend_type(backend_type)
        logger.debug("Registered sandbox backend factory: %s", backend_type)

    @classmethod
    def create(cls, config: SandboxBackendConfig) -> BackendProtocol:
        """Create a sandbox backend from the discriminated config.

        Dispatches to the registered factory for ``config.type``. Raises
        ``ValueError`` for unknown types.

        Args:
            config: The resolved ``SandboxBackendConfig`` from ``SandboxConfig``.
        """
        factory = cls._factories.get(config.type)
        if factory is None:
            known = ", ".join(sorted(cls._factories)) or "(none)"
            msg = (
                f"No sandbox backend factory registered for type "
                f"{config.type!r}. Known types: {known}."
            )
            raise ValueError(msg)

        if config.type == "arcbox":
            if config.arcbox is None:
                msg = "sandbox.backend.type='arcbox' requires sandbox.backend.arcbox config"
                raise ValueError(msg)
            return factory(config.arcbox)
        if config.type == "os_sandbox":
            if config.os_sandbox is None:
                msg = "sandbox.backend.type='os_sandbox' requires sandbox.backend.os_sandbox config"
                raise ValueError(msg)
            return factory(config.os_sandbox)

        # Future backends: add dispatch branches here as new config sub-fields
        # are introduced. The discriminated-union pattern keeps each backend's
        # config isolated.
        msg = f"Sandbox backend type {config.type!r} has no config dispatch"
        raise ValueError(msg)


def _arcbox_factory(cfg: ArcBoxBackendConfig) -> BackendProtocol:
    """Create an ``ArcBoxBackend`` from ``ArcBoxBackendConfig``.

    Lazy import so the arcbox module (and its SDK dependency) is only loaded
    when the arcbox backend is actually selected.
    """
    from soothe_nano.sandbox.arcbox import ArcBoxBackend

    return ArcBoxBackend.from_config(
        image=cfg.image,
        vcpus=cfg.vcpus,
        mem_mib=cfg.mem_mib,
        network=cfg.network,
        workspace_root=cfg.workspace_root,
        default_timeout=cfg.default_timeout,
        connect_timeout=cfg.connect_timeout,
        idle_timeout_seconds=cfg.idle_timeout_seconds,
        min_free_bytes=cfg.min_free_bytes,
        api_url=cfg.api_url,
        api_key=cfg.api_key,
        socket_path=cfg.socket_path,
    )


def _os_sandbox_factory(cfg: OsLocalSandboxConfig) -> BackendProtocol:
    """Create an ``OsLocalSandbox`` from ``OsLocalSandboxConfig``.

    Lazy import so the backend module is only loaded when os_sandbox is
    actually selected. Construction runs the tier capability probe and
    fails loudly when prerequisites are missing (never a host fallback).
    """
    from soothe_nano.sandbox.os_local import OsLocalSandbox

    return OsLocalSandbox(cfg)


# Register the built-in factories.
SandboxBackendFactory.register("arcbox", _arcbox_factory)
SandboxBackendFactory.register("os_sandbox", _os_sandbox_factory)


def create_sandbox_backend(config: SandboxBackendConfig) -> BackendProtocol:
    """Convenience wrapper for :meth:`SandboxBackendFactory.create`."""
    return SandboxBackendFactory.create(config)
