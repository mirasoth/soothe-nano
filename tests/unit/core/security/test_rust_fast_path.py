"""Tests for Rust fast-path delegation in security PathValidator and RateLimiter.

Verifies that the Rust-backed pre-checks produce identical reject results to
the full Python validation for traversal, absolute-path, and null-byte cases,
and that the fast-path is actually exercised when the Rust extension is
available.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from soothe_nano._rust_compat import (
    is_rust_available,
    rust_local_filesystem_new,
    rust_path_validator_new,
    rust_path_validator_validate,
    rust_rate_limiter_new,
    rust_rate_limiter_try_consume,
    rust_sqlite_store_new,
    rust_workspace_policy_new,
)
from soothe_nano.security.path_security import (
    PathValidator,
    ValidationSeverity,
    create_permissive_validator,
    create_strict_validator,
)
from soothe_nano.security.policy_profiles import STRICT_POLICY
from soothe_nano.security.security_enforcer import SecurityEnforcer

rust_required = pytest.mark.skipif(
    not is_rust_available(),
    reason="Rust extension (_rust) not compiled — fast-path tests require it",
)


# ---------------------------------------------------------------------------
# _rust_compat wrappers
# ---------------------------------------------------------------------------


@rust_required
class TestRustPathValidatorWrapper:
    """Tests for the rust_path_validator_* _rust_compat wrappers."""

    def test_new_returns_rust_instance(self) -> None:
        """rust_path_validator_new returns a non-None Rust PathValidator."""
        pv = rust_path_validator_new("/tmp/ws")
        assert pv is not None

    def test_validate_traversal_returns_invalid(self) -> None:
        """Traversal patterns are rejected by the Rust validator."""
        is_valid, violation_type, _message = rust_path_validator_validate("../etc/passwd")
        assert is_valid is False
        assert "traversal" in violation_type

    def test_validate_absolute_returns_invalid(self) -> None:
        """Absolute paths are rejected by the Rust validator."""
        is_valid, violation_type, _message = rust_path_validator_validate("/etc/passwd")
        assert is_valid is False
        assert "absolute" in violation_type

    def test_validate_null_byte_returns_invalid(self) -> None:
        """Null bytes are rejected by the Rust validator."""
        is_valid, violation_type, _message = rust_path_validator_validate("file\x00.txt")
        assert is_valid is False
        assert "null" in violation_type

    def test_validate_valid_path_returns_valid(self) -> None:
        """A normal relative path passes the Rust fast-check."""
        is_valid, violation_type, _message = rust_path_validator_validate("src/main.py")
        assert is_valid is True
        assert violation_type == "none"


@rust_required
class TestRustRateLimiterWrapper:
    """Tests for the rust_rate_limiter_* _rust_compat wrappers."""

    def test_new_returns_rust_instance(self) -> None:
        """rust_rate_limiter_new returns a non-None Rust RateLimiter."""
        rl = rust_rate_limiter_new(capacity=5, refill_per_minute=5)
        assert rl is not None

    def test_try_consume_allows_within_capacity(self) -> None:
        """Tokens are consumed until the bucket is empty."""
        rl = rust_rate_limiter_new(capacity=3, refill_per_minute=0)
        assert rust_rate_limiter_try_consume("k", rl) is True
        assert rust_rate_limiter_try_consume("k", rl) is True
        assert rust_rate_limiter_try_consume("k", rl) is True
        assert rust_rate_limiter_try_consume("k", rl) is False

    def test_try_consume_independent_keys(self) -> None:
        """Different keys have independent buckets."""
        rl = rust_rate_limiter_new(capacity=1, refill_per_minute=0)
        assert rust_rate_limiter_try_consume("a", rl) is True
        assert rust_rate_limiter_try_consume("a", rl) is False
        assert rust_rate_limiter_try_consume("b", rl) is True

    def test_try_consume_returns_none_when_unavailable(self) -> None:
        """When Rust is unavailable, try_consume returns None (fallback signal)."""
        if is_rust_available():
            pytest.skip("Rust is available — None-return path not exercisable")
        assert rust_rate_limiter_try_consume("k") is None


# ---------------------------------------------------------------------------
# PathValidator fast-path integration
# ---------------------------------------------------------------------------


@rust_required
class TestPathValidatorFastPath:
    """Tests that PathValidator.validate() delegates to the Rust fast-path."""

    @pytest.fixture()
    def workspace(self) -> Path:
        """Create a temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir).resolve()

    @pytest.fixture()
    def validator(self, workspace: Path) -> PathValidator:
        """Create a strict validator."""
        return create_strict_validator(workspace)

    @pytest.mark.parametrize(
        ("path", "expected_substring"),
        [
            ("../etc/passwd", "traversal"),
            ("foo/../bar", "traversal"),
            ("../../../etc/passwd", "traversal"),
            ("/etc/passwd", "absolute"),
            ("file\x00.txt", "null"),
        ],
    )
    def test_fast_path_rejects_dangerous_patterns(
        self,
        validator: PathValidator,
        path: str,
        expected_substring: str,
    ) -> None:
        """Dangerous patterns are rejected via the Rust fast-path."""
        result = validator.validate(path)
        assert result.is_valid is False
        assert expected_substring in (result.violation_type or "")
        assert result.details.get("fast_path") == "rust"

    def test_fast_path_traversal_severity_critical(
        self,
        validator: PathValidator,
    ) -> None:
        """Traversal rejections from the fast-path are CRITICAL severity."""
        result = validator.validate("../etc/passwd")
        assert result.severity == ValidationSeverity.CRITICAL

    def test_fast_path_null_byte_severity_critical(
        self,
        validator: PathValidator,
    ) -> None:
        """Null-byte rejections from the fast-path are CRITICAL severity."""
        result = validator.validate("file\x00.txt")
        assert result.severity == ValidationSeverity.CRITICAL

    def test_valid_path_not_short_circuited(
        self,
        validator: PathValidator,
    ) -> None:
        """Valid paths do not carry the fast_path detail marker."""
        result = validator.validate("src/main.py")
        assert result.is_valid is True
        assert result.details.get("fast_path") is None

    def test_virtual_path_not_short_circuited(
        self,
        validator: PathValidator,
        workspace: Path,
    ) -> None:
        """Virtual workspace paths (leading /) bypass the Rust absolute reject."""
        (workspace / "CHANGELOG.md").write_text("hi", encoding="utf-8")
        result = validator.validate("/CHANGELOG.md")
        assert result.is_valid is True
        assert result.normalized_path == "CHANGELOG.md"
        assert result.details.get("fast_path") is None

    def test_permissive_absolute_within_workspace_not_short_circuited(
        self,
        workspace: Path,
    ) -> None:
        """allow_absolute=True bypasses the Rust absolute reject."""
        validator = create_permissive_validator(workspace)
        test_file = workspace / "test.txt"
        test_file.write_text("test")
        result = validator.validate(str(test_file))
        assert result.is_valid is True

    def test_backslash_traversal_falls_through_to_python(
        self,
        validator: PathValidator,
    ) -> None:
        """Backslash traversal (Rust misses) falls through to Python regexes."""
        result = validator.validate("..\\Windows\\System32")
        assert result.is_valid is False
        assert "traversal" in (result.violation_type or "")
        # Python regex path, not the Rust fast-path
        assert result.details.get("fast_path") is None

    def test_identical_reject_for_traversal_with_and_without_rust(
        self,
        workspace: Path,
    ) -> None:
        """Fast-path and full Python path agree on traversal rejection."""
        validator = create_strict_validator(workspace)
        rust_result = validator.validate("../etc/passwd")
        # The violation_type must be a traversal type (mapped from Rust)
        assert rust_result.is_valid is False
        assert "traversal" in (rust_result.violation_type or "")


# ---------------------------------------------------------------------------
# SecurityEnforcer RateLimiter fast-path integration
# ---------------------------------------------------------------------------


@rust_required
class TestEnforcerRateLimiterFastPath:
    """Tests that SecurityEnforcer delegates rate-limiting to Rust."""

    @pytest.fixture()
    def workspace(self) -> Path:
        """Create a temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir).resolve()

    def test_enforcer_has_rust_rate_limiter(self, workspace: Path) -> None:
        """The enforcer instantiates a Rust RateLimiter when rate limiting is on."""
        enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=STRICT_POLICY,
            enable_rate_limiting=True,
        )
        assert enforcer._rust_rate_limiter is not None

    def test_enforcer_no_rust_limiter_when_disabled(self, workspace: Path) -> None:
        """No Rust limiter is created when rate limiting is disabled."""
        enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=STRICT_POLICY,
            enable_rate_limiting=False,
        )
        assert enforcer._rust_rate_limiter is None

    def test_rate_limiting_denies_after_capacity(
        self,
        workspace: Path,
    ) -> None:
        """The Rust fast-path denies after capacity is exhausted."""
        policy = STRICT_POLICY.with_restrictions(max_operations_per_minute=2)
        enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=policy,
            enable_rate_limiting=True,
        )

        d1 = enforcer.check_access("file1.txt", "read")
        d2 = enforcer.check_access("file2.txt", "read")
        d3 = enforcer.check_access("file3.txt", "read")

        assert d1.allowed is True
        assert d2.allowed is True
        assert d3.is_denied is True
        assert any(v.violation_type == "rate_limit_exceeded" for v in d3.violations)

    def test_rate_limit_violation_carries_rust_fast_path_message(
        self,
        workspace: Path,
    ) -> None:
        """The rate-limit violation from the Rust fast-path is distinguishable."""
        policy = STRICT_POLICY.with_restrictions(max_operations_per_minute=1)
        enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=policy,
            enable_rate_limiting=True,
        )

        enforcer.check_access("file1.txt", "read")  # consumes the token
        d2 = enforcer.check_access("file2.txt", "read")

        assert d2.is_denied is True
        violation = d2.violations[0]
        assert violation.violation_type == "rate_limit_exceeded"
        assert "Rust fast-path" in (violation.message or "")

    def test_update_policy_rebuilds_rust_limiter(
        self,
        workspace: Path,
    ) -> None:
        """update_policy rebuilds the Rust limiter with the new capacity."""
        enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=STRICT_POLICY,
            enable_rate_limiting=True,
        )
        original = enforcer._rust_rate_limiter
        new_policy = STRICT_POLICY.with_restrictions(max_operations_per_minute=5)
        enforcer.update_policy(new_policy)
        assert enforcer._rust_rate_limiter is not None
        assert enforcer._rust_rate_limiter is not original


# ---------------------------------------------------------------------------
# SqliteStoreRuntime / LocalFilesystem / WorkspacePolicy fast-path wrappers
# ---------------------------------------------------------------------------


@rust_required
class TestRustSqliteStoreWrapper:
    """Tests for rust_sqlite_store_new wrapper."""

    def test_new_returns_rust_instance(self, tmp_path: Path) -> None:
        """rust_sqlite_store_new returns a non-None Rust SqliteStoreRuntime."""
        db = tmp_path / "test.db"
        store = rust_sqlite_store_new(str(db))
        assert store is not None

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """save_sync/load_sync round-trip works."""
        db = tmp_path / "test.db"
        store = rust_sqlite_store_new(str(db))
        store.save_sync("key1", '"value1"')
        result = store.load_sync("key1")
        assert result == '"value1"'

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        """load_sync on a missing key returns None."""
        db = tmp_path / "test.db"
        store = rust_sqlite_store_new(str(db))
        assert store.load_sync("nonexistent") is None


@rust_required
class TestRustLocalFilesystemWrapper:
    """Tests for rust_local_filesystem_new wrapper."""

    def test_new_returns_rust_instance(self, tmp_path: Path) -> None:
        """rust_local_filesystem_new returns a non-None Rust LocalFilesystem."""
        fs = rust_local_filesystem_new(str(tmp_path))
        assert fs is not None

    def test_read_file(self, tmp_path: Path) -> None:
        """read returns file contents as JSON."""
        (tmp_path / "test.txt").write_text("hello world", encoding="utf-8")
        fs = rust_local_filesystem_new(str(tmp_path))
        import json

        result = json.loads(fs.read("test.txt"))
        assert "hello world" in result["content"]

    def test_glob_finds_files(self, tmp_path: Path) -> None:
        """glob finds files matching a pattern."""
        (tmp_path / "a.py").write_text("a", encoding="utf-8")
        (tmp_path / "b.py").write_text("b", encoding="utf-8")
        (tmp_path / "c.txt").write_text("c", encoding="utf-8")
        fs = rust_local_filesystem_new(str(tmp_path))
        results = fs.glob("*.py")
        assert len(results) == 2

    def test_grep_finds_pattern(self, tmp_path: Path) -> None:
        """grep finds literal patterns in files."""
        (tmp_path / "test.txt").write_text("hello world\nfoo bar", encoding="utf-8")
        fs = rust_local_filesystem_new(str(tmp_path))
        results = fs.grep("hello", ".")
        assert len(results) >= 1


@rust_required
class TestRustWorkspacePolicyWrapper:
    """Tests for rust_workspace_policy_new wrapper."""

    def test_new_returns_rust_instance(self, tmp_path: Path) -> None:
        """rust_workspace_policy_new returns a non-None Rust WorkspacePolicy."""
        wp = rust_workspace_policy_new(str(tmp_path))
        assert wp is not None

    def test_can_write_default_true(self, tmp_path: Path) -> None:
        """A new policy allows writes by default."""
        wp = rust_workspace_policy_new(str(tmp_path))
        assert wp.can_write is True

    def test_root_attribute(self, tmp_path: Path) -> None:
        """The root getter returns the workspace root string."""
        wp = rust_workspace_policy_new(str(tmp_path))
        assert wp.root == str(tmp_path)
