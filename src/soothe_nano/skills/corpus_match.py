"""Corpus matching helpers for skill name/tag prefetch.

All string-matching functions are Rust-backed (no Python fallback).
"""

from __future__ import annotations

from soothe_nano._rust_compat import (
    earliest_corpus_match_rust as earliest_corpus_match,
)
from soothe_nano._rust_compat import (
    match_variants_for_token_rust as match_variants_for_token,
)

# User-facing phrasings for built-in core skills (name → extra match tokens).
BUILTIN_SKILL_ALIASES: dict[str, frozenset[str]] = {
    "clawhub": frozenset(
        {
            "claw hub",
            "claw hub registry",
            "clawhub registry",
            "community skill registry",
        }
    ),
    "github": frozenset(
        {
            "git hub",
            "github cli",
            "gh cli",
        }
    ),
    "skill-creator": frozenset(
        {
            "skill creator",
            "create skill",
            "create a skill",
            "new skill",
            "write skill",
            "agentskill",
            "skill authoring",
        }
    ),
    "mcp-builder": frozenset(
        {
            "mcp builder",
            "mcp server",
            "model context protocol",
            "build mcp",
            "create mcp",
        }
    ),
    "weather": frozenset(
        {
            "wttr",
            "wttr.in",
        }
    ),
}

__all__: tuple[str, ...] = (
    "BUILTIN_SKILL_ALIASES",
    "earliest_corpus_match",
    "match_variants_for_token",
)
