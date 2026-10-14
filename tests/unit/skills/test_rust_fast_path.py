"""Tests for Rust fast-path delegation in skills (CorpusMatcher, SkillDiscovery).

Verifies that the Rust-backed wrappers construct correctly and that the
fast-path delegation in ``corpus_match.py`` and ``discovery_tools.py``
produces correct results when the Rust extension is available.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from soothe_nano._rust_compat import (
    is_rust_available,
    rust_corpus_matcher_new,
    rust_local_filesystem_new,
    rust_skill_discovery_new,
    rust_sqlite_store_new,
    rust_workspace_policy_new,
)

rust_required = pytest.mark.skipif(
    not is_rust_available(),
    reason="Rust extension (_rust) not compiled — fast-path tests require it",
)


# ---------------------------------------------------------------------------
# _rust_compat wrapper construction tests
# ---------------------------------------------------------------------------


@rust_required
class TestRustCorpusMatcherWrapper:
    """Tests for rust_corpus_matcher_new."""

    def test_new_returns_rust_instance(self) -> None:
        """rust_corpus_matcher_new returns a non-None Rust CorpusMatcher."""
        cm = rust_corpus_matcher_new([1.0, 0.0, 0.0, 1.0], 2)
        assert cm is not None

    def test_len_reports_skill_count(self) -> None:
        """The len getter reports the correct number of skills."""
        cm = rust_corpus_matcher_new([1.0, 0.0, 0.0, 1.0, 1.0, 1.0], 2)
        assert cm.len == 3

    def test_cosine_search_finds_best_match(self) -> None:
        """cosine_search returns the most similar skill."""
        cm = rust_corpus_matcher_new([1.0, 0.0, 0.0, 1.0], 2)
        results = cm.cosine_search([1.0, 0.0], 1)
        assert len(results) == 1
        score, idx = results[0]
        assert idx == 0
        assert abs(score - 1.0) < 1e-6

    def test_cosine_search_top_k(self) -> None:
        """cosine_search respects the top_k limit."""
        cm = rust_corpus_matcher_new([1.0, 0.0, 0.0, 1.0, 1.0, 1.0], 2)
        results = cm.cosine_search([1.0, 0.0], 2)
        assert len(results) == 2
        assert results[0][1] == 0  # best match is skill 0

    def test_empty_corpus(self) -> None:
        """An empty corpus has zero skills."""
        cm = rust_corpus_matcher_new([], 2)
        assert cm.len == 0


@rust_required
class TestRustSkillDiscoveryWrapper:
    """Tests for rust_skill_discovery_new."""

    def test_new_returns_rust_instance(self) -> None:
        """rust_skill_discovery_new returns a non-None Rust SkillDiscovery."""
        sd = rust_skill_discovery_new("/tmp")
        assert sd is not None

    def test_discover_finds_md_files(self) -> None:
        """discover() finds .md files in a temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "skill-a").mkdir()
            (Path(tmpdir) / "skill-a" / "SKILL.md").write_text("# Skill A")
            (Path(tmpdir) / "skill-b").mkdir()
            (Path(tmpdir) / "skill-b" / "SKILL.md").write_text("# Skill B")
            (Path(tmpdir) / "readme.md").write_text("not a skill")

            sd = rust_skill_discovery_new(tmpdir)
            results = list(sd.discover())
            names = [entry[0] for entry in results]
            assert "SKILL" in names or "skill-a" in names or "readme" in names

    def test_discover_empty_dir(self) -> None:
        """discover() on an empty directory returns an empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = rust_skill_discovery_new(tmpdir)
            results = list(sd.discover())
            assert results == []

    def test_discover_nonexistent_dir(self) -> None:
        """discover() on a nonexistent directory returns an empty list."""
        sd = rust_skill_discovery_new("/nonexistent/path/that/does/not/exist")
        results = list(sd.discover())
        assert results == []


@rust_required
class TestRustSqliteStoreWrapper:
    """Tests for rust_sqlite_store_new."""

    def test_new_returns_rust_instance(self) -> None:
        """rust_sqlite_store_new returns a non-None Rust SqliteStoreRuntime."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            store = rust_sqlite_store_new(path)
            assert store is not None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_and_load(self) -> None:
        """save_sync/load_sync round-trip works."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            store = rust_sqlite_store_new(path)
            store.save_sync("key1", '"value1"')
            result = store.load_sync("key1")
            assert result == '"value1"'
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_missing_key_returns_none(self) -> None:
        """load_sync on a missing key returns None."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            store = rust_sqlite_store_new(path)
            result = store.load_sync("nonexistent")
            assert result is None
        finally:
            Path(path).unlink(missing_ok=True)


@rust_required
class TestRustLocalFilesystemWrapper:
    """Tests for rust_local_filesystem_new."""

    def test_new_returns_rust_instance(self) -> None:
        """rust_local_filesystem_new returns a non-None Rust LocalFilesystem."""
        fs = rust_local_filesystem_new("/tmp")
        assert fs is not None

    def test_read_file(self) -> None:
        """read returns file contents as JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello world")
            fs = rust_local_filesystem_new(tmpdir)
            import json

            result = json.loads(fs.read("test.txt"))
            assert "hello world" in result["content"]

    def test_glob_finds_files(self) -> None:
        """glob finds files matching a pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("a")
            (Path(tmpdir) / "b.py").write_text("b")
            (Path(tmpdir) / "c.txt").write_text("c")
            fs = rust_local_filesystem_new(tmpdir)
            results = fs.glob("*.py")
            assert len(results) == 2

    def test_grep_finds_pattern(self) -> None:
        """grep finds literal patterns in files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.txt").write_text("hello world\nfoo bar")
            fs = rust_local_filesystem_new(tmpdir)
            results = fs.grep("hello", ".")
            assert len(results) >= 1


@rust_required
class TestRustWorkspacePolicyWrapper:
    """Tests for rust_workspace_policy_new."""

    def test_new_returns_rust_instance(self) -> None:
        """rust_workspace_policy_new returns a non-None Rust WorkspacePolicy."""
        wp = rust_workspace_policy_new("/tmp")
        assert wp is not None

    def test_can_write_default_true(self) -> None:
        """A new policy allows writes by default."""
        wp = rust_workspace_policy_new("/tmp")
        assert wp.can_write is True

    def test_root_attribute(self) -> None:
        """The root getter returns the workspace root string."""
        wp = rust_workspace_policy_new("/tmp")
        assert wp.root == "/tmp"


# ---------------------------------------------------------------------------
# corpus_match.py fast-path integration
# ---------------------------------------------------------------------------


@rust_required
class TestCorpusMatchFastPath:
    """Tests that corpus_match.py delegates to the Rust fast-path."""

    def test_earliest_corpus_match_uses_rust(self) -> None:
        """earliest_corpus_match delegates to Rust and returns correct position."""
        from soothe_nano.skills.corpus_match import earliest_corpus_match

        corpus = "is there skill of drawio on claw hub"
        pos = earliest_corpus_match(corpus, "clawhub", skill_name="clawhub")
        assert pos is not None
        assert corpus[pos : pos + 8] == "claw hub"

    def test_match_variants_delegates_to_rust(self) -> None:
        """match_variants_for_token delegates to Rust."""
        from soothe_nano.skills.corpus_match import match_variants_for_token

        variants = match_variants_for_token("clawhub", skill_name="clawhub")
        assert "clawhub" in variants
        assert "claw hub" in variants

    def test_no_match_returns_none(self) -> None:
        """earliest_corpus_match returns None when no match exists."""
        from soothe_nano.skills.corpus_match import earliest_corpus_match

        pos = earliest_corpus_match("nothing relevant here", "clawhub", skill_name="clawhub")
        assert pos is None


# ---------------------------------------------------------------------------
# discovery_tools.py fast-path integration
# ---------------------------------------------------------------------------


@rust_required
class TestDiscoveryToolsFastPath:
    """Tests that discovery_tools.py delegates to the Rust fast-path."""

    def test_discover_skill_files_finds_md(self) -> None:
        """discover_skill_files uses Rust to find .md files."""
        from soothe_nano.skills.discovery_tools import discover_skill_files

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SKILL.md").write_text("# Test Skill")
            (Path(tmpdir) / "other.md").write_text("# Other")
            results = discover_skill_files([tmpdir])
            assert results is not None
            assert len(results) >= 1

    def test_discover_skill_files_empty_dir(self) -> None:
        """discover_skill_files returns empty list for empty dir."""
        from soothe_nano.skills.discovery_tools import discover_skill_files

        with tempfile.TemporaryDirectory() as tmpdir:
            results = discover_skill_files([tmpdir])
            assert results is not None
            assert results == []


# ---------------------------------------------------------------------------
# Unavailable-when-no-Rust tests
# ---------------------------------------------------------------------------


class TestRustUnavailableFallback:
    """Tests that wrappers return None when Rust is unavailable."""

    def test_corpus_matcher_new_returns_none_when_unavailable(self) -> None:
        """When Rust is unavailable, rust_corpus_matcher_new returns None."""
        if is_rust_available():
            pytest.skip("Rust is available — None-return path not exercisable")
        assert rust_corpus_matcher_new([1.0], 1) is None

    def test_skill_discovery_new_returns_none_when_unavailable(self) -> None:
        """When Rust is unavailable, rust_skill_discovery_new returns None."""
        if is_rust_available():
            pytest.skip("Rust is available — None-return path not exercisable")
        assert rust_skill_discovery_new("/tmp") is None

    def test_sqlite_store_new_returns_none_when_unavailable(self) -> None:
        """When Rust is unavailable, rust_sqlite_store_new returns None."""
        if is_rust_available():
            pytest.skip("Rust is available — None-return path not exercisable")
        assert rust_sqlite_store_new("/tmp/test.db") is None

    def test_local_filesystem_new_returns_none_when_unavailable(self) -> None:
        """When Rust is unavailable, rust_local_filesystem_new returns None."""
        if is_rust_available():
            pytest.skip("Rust is available — None-return path not exercisable")
        assert rust_local_filesystem_new("/tmp") is None

    def test_workspace_policy_new_returns_none_when_unavailable(self) -> None:
        """When Rust is unavailable, rust_workspace_policy_new returns None."""
        if is_rust_available():
            pytest.skip("Rust is available — None-return path not exercisable")
        assert rust_workspace_policy_new("/tmp") is None
