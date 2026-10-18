"""Unified deferred skill search (substring / corpus matching)."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import HumanMessage

from soothe_nano.skills.index import SkillIndexEntry
from soothe_nano.skills.registry import ProgressiveSkillRegistry


class SkillSearcher:
    """Deferred-skill search bound to a ``ProgressiveSkillRegistry``.

    Semantic Skillify search is owned by the soothe host and is not invoked
    from CoreAgent; the host registry provides substring/corpus matching only.
    """

    def __init__(self, registry: ProgressiveSkillRegistry) -> None:
        self._registry = registry

    def prefetch_core_from_corpus(
        self,
        goal: str,
        core_entries: Sequence[SkillIndexEntry],
        *,
        discovered: set[str],
        limit: int,
    ) -> list[SkillIndexEntry]:
        """Match core skills by name/tags in the goal text only (no semantic search)."""
        return self._registry.match_deferred_in_corpus(
            goal,
            core_entries,
            discovered=discovered,
            limit=limit,
        )

    async def prefetch_from_goal(
        self,
        goal: str,
        entries: Sequence[SkillIndexEntry],
        *,
        discovered: set[str],
        limit: int,
    ) -> list[SkillIndexEntry]:
        """Match skills from a user goal (name/tag corpus match + substring)."""
        corpus_matches = self._registry.match_deferred_in_corpus(
            goal,
            entries,
            discovered=discovered,
            limit=limit,
        )
        discovered_with_corpus = discovered | {entry.name for entry in corpus_matches}
        searched = await self.search(
            goal,
            entries,
            discovered=discovered_with_corpus,
            limit=limit,
        )
        return self.merge_search_results(
            corpus_matches,
            [(0.0, entry) for entry in searched],
            limit=limit,
        )

    async def search(
        self,
        query: str,
        deferred: Sequence[SkillIndexEntry],
        *,
        discovered: set[str],
        limit: int,
    ) -> list[SkillIndexEntry]:
        """Search deferred skills via substring matching."""
        return self._registry.search_deferred(
            query,
            deferred,
            discovered=discovered,
            limit=limit,
        )

    @staticmethod
    def merge_search_results(
        substring_matches: Sequence[SkillIndexEntry],
        semantic_matches: Sequence[tuple[float, SkillIndexEntry]],
        *,
        limit: int,
    ) -> list[SkillIndexEntry]:
        """Merge primary and secondary hits; primary order first, then by score."""
        out: list[SkillIndexEntry] = []
        seen: set[str] = set()
        for entry in substring_matches:
            if entry.name in seen:
                continue
            seen.add(entry.name)
            out.append(entry)
            if len(out) >= limit:
                return out
        ranked = sorted(semantic_matches, key=lambda item: (-item[0], item[1].name.lower()))
        for _score, entry in ranked:
            if entry.name in seen:
                continue
            seen.add(entry.name)
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def latest_human_text(state: dict) -> str | None:
        """Return text from the most recent human message in agent state."""
        messages = state.get("messages") or []
        for msg in reversed(messages):
            if not isinstance(msg, HumanMessage):
                continue
            content = msg.content
            if isinstance(content, str):
                text = content.strip()
                if text:
                    return text
            elif isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                    elif isinstance(block, str):
                        parts.append(block)
                text = " ".join(parts).strip()
                if text:
                    return text
        return None
