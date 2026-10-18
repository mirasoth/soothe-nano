"""Unified assistant identity for system prompts."""

from __future__ import annotations


class PromptIdentity:
    """Assistant identity block builders for system prompts."""

    @staticmethod
    def normalize_name(assistant_name: str) -> str:
        """Return a non-empty configured assistant display name."""
        name = (assistant_name or "Soothe").strip()
        return name or "Soothe"

    @staticmethod
    def identity_block(assistant_name: str) -> str:
        """Build the cache-stable `<ASSISTANT_IDENTITY>` XML block.

        Reads `ASSISTANT_IDENTITY_FRAGMENT` at call time so host-side
        persona overrides (patching the fragments module) reach this
        hot path.

        Args:
            assistant_name: Configured assistant display name (e.g. `Soothe`).

        Returns:
            Formatted identity block (single source of truth for prompt injection).
        """
        from soothe_nano.prompts.fragments import ASSISTANT_IDENTITY_FRAGMENT

        name = PromptIdentity.normalize_name(assistant_name)
        return ASSISTANT_IDENTITY_FRAGMENT.format(assistant_name=name).strip()

    @staticmethod
    def prepend_identity(system_body: str, assistant_name: str) -> str:
        """Prepend the canonical identity block to a system prompt body.

        Use for CoreAgent system prompts (`resolve_system_prompt`, middleware).

        Args:
            system_body: Phase-specific instructions without identity.
            assistant_name: Configured assistant display name.

        Returns:
            Identity block followed by the body.
        """
        identity = PromptIdentity.identity_block(assistant_name)
        body = system_body.strip()
        if not body:
            return identity
        return f"{identity}\n\n{body}"


__all__ = ["PromptIdentity"]
