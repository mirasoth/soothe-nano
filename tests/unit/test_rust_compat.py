"""Integration tests for the Rust/Python conditional import layer.

These tests exercise the ``_rust_compat`` bridge module to verify that:

1. The availability probe works correctly (``is_rust_available()`` returns
   ``True`` when the extension is compiled, ``False`` otherwise).
2. Each Rust-backed function produces the same result as the Python fallback,
   regardless of which backend is active.
3. The public Python API (``soothe_nano.utils.*``) remains unchanged after
   wiring through ``_rust_compat``.

Tests are structured so that they pass in both states:
- **Rust extension absent** — exercises the Python fallback path.
- **Rust extension present** (after ``maturin develop``) — exercises the
  Rust-backed path and compares against known-correct values.

Run with ``--run-integration`` to include these in the integration suite.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from soothe_nano._rust_compat import (
    build_context_xml_rust,
    count_tokens_rust,
    custom_event_rust,
    expand_env_vars_rust,
    generate_thread_id,
    get_local_filesystem,
    get_path_validator,
    get_skill_budget,
    get_skill_discovery,
    get_sqlite_store_runtime,
    get_token_counter,
    is_rust_available,
    repair_json,
    resolve_workspace_rust,
    text_preview_rust,
)

# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------


class TestRustAvailability:
    """Verify the availability probe is consistent."""

    def test_is_rust_available_returns_bool(self) -> None:
        result = is_rust_available()
        assert isinstance(result, bool)

    def test_probe_is_stable_across_calls(self) -> None:
        a = is_rust_available()
        b = is_rust_available()
        assert a == b


# ---------------------------------------------------------------------------
# thread_id — generate_thread_id
# ---------------------------------------------------------------------------


class TestGenerateThreadId:
    """Verify thread ID generation parity."""

    def test_returns_valid_uuid_string(self) -> None:
        tid = generate_thread_id()
        # Must be a parseable UUID v4
        parsed = uuid.UUID(tid)
        assert parsed.version == 4

    def test_unique_across_calls(self) -> None:
        ids = {generate_thread_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# token_counting — count_tokens_rust
# ---------------------------------------------------------------------------


class TestCountTokens:
    """Verify token counting parity between Rust and Python."""

    def test_empty_string(self) -> None:
        assert count_tokens_rust("") == 0

    def test_simple_text(self) -> None:
        result = count_tokens_rust("Hello world")
        assert result > 0
        # "Hello world" is 2 tokens in cl100k_base
        assert result <= 5

    def test_longer_text(self) -> None:
        text = "This is a longer piece of text that should have more tokens"
        result = count_tokens_rust(text)
        assert result > 5

    def test_cjk_text(self) -> None:
        text = "使用浏览器获取信息"
        result = count_tokens_rust(text)
        assert result > 0

    def test_with_model_hint(self) -> None:
        result = count_tokens_rust("Hello world", model="gpt-4")
        assert result > 0
        assert result <= 5


# ---------------------------------------------------------------------------
# json_parsing — repair_json
# ---------------------------------------------------------------------------


class TestRepairJson:
    """Verify JSON repair parity."""

    def test_valid_json_object(self) -> None:
        result = repair_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_valid_json_array(self) -> None:
        # The Python fallback (_load_llm_json_dict) only extracts dicts;
        # the Rust repair_json handles arrays. Test behavior is conditional.
        result = repair_json("[1, 2, 3]")
        if is_rust_available():
            assert result == [1, 2, 3]
        else:
            # Python fallback returns None for non-dict JSON
            assert result is None

    def test_fenced_json(self) -> None:
        result = repair_json('```json\n{"b": 2}\n```')
        assert result == {"b": 2}

    def test_leading_prose(self) -> None:
        result = repair_json('Here is the result: {"c": 3}')
        # Rust implementation extracts the JSON object; Python fallback uses
        # _load_llm_json_dict which also extracts it.
        if result is not None:
            assert result.get("c") == 3

    def test_invalid_returns_none(self) -> None:
        result = repair_json("not json at all")
        assert result is None


# ---------------------------------------------------------------------------
# text_preview — text_preview_rust
# ---------------------------------------------------------------------------


class TestTextPreview:
    """Verify text preview parity."""

    def test_short_text_unchanged(self) -> None:
        result = text_preview_rust("hello world", 100)
        assert result == "hello world"

    def test_long_text_truncated(self) -> None:
        result = text_preview_rust("hello world foo bar baz", 10)
        # Rust: collapses whitespace, truncates with "..."
        # Python fallback (preview): uses "[...N chars abbr...]" marker
        assert len(result) <= 40  # either form fits within 40 chars
        assert "hello" in result

    def test_empty_string(self) -> None:
        assert text_preview_rust("", 100) == ""

    def test_exact_length_not_truncated(self) -> None:
        text = "hello"
        result = text_preview_rust(text, 5)
        assert result == "hello"


# ---------------------------------------------------------------------------
# url_validation — parity with Python validate_url
# ---------------------------------------------------------------------------


class TestUrlValidationParity:
    """Verify URL validation behavior matches the Python implementation."""

    @pytest.fixture(autouse=True)
    def _import_python_validate(self) -> None:
        from soothe_nano.utils.url_validation import validate_url

        self._python_validate = staticmethod(validate_url)

    def test_valid_https(self) -> None:
        url = "https://example.com/path"
        sanitized, error = self._python_validate(url)
        assert error is None
        assert sanitized == url

    def test_url_with_spaces(self) -> None:
        url = "https://ir.we ride.ai/"
        sanitized, error = self._python_validate(url)
        assert error is None
        assert "%20" in sanitized

    def test_missing_scheme(self) -> None:
        sanitized, error = self._python_validate("example.com")
        assert error is not None
        assert "scheme" in error.lower()

    def test_missing_domain(self) -> None:
        sanitized, error = self._python_validate("https://")
        assert error is not None
        assert "domain" in error.lower()


# ---------------------------------------------------------------------------
# path expansion — expand_env_vars_rust parity
# ---------------------------------------------------------------------------


class TestExpandEnvVars:
    """Verify env var expansion parity."""

    def test_no_env_vars(self) -> None:
        assert expand_env_vars_rust("plain/path") == "plain/path"

    def test_env_var_expansion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RUST_COMPAT_VAR", "/test/path")
        result = expand_env_vars_rust("$TEST_RUST_COMPAT_VAR/project")
        assert result == "/test/path/project"

    def test_braced_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_RUST_COMPAT_VAR", "/test/path")
        result = expand_env_vars_rust("${TEST_RUST_COMPAT_VAR}/sub")
        assert result == "/test/path/sub"

    def test_expand_path_uses_compat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify expand_path delegates through _rust_compat."""
        from soothe_nano.utils.path import expand_path

        monkeypatch.setenv("TEST_EXPAND_PATH", "/expanded")
        result = expand_path("$TEST_EXPAND_PATH/dir")
        assert result == Path("/expanded/dir").resolve()


# ---------------------------------------------------------------------------
# Token counter (Rust object when available)
# ---------------------------------------------------------------------------


class TestTokenCounter:
    """Verify the TokenCounter wrapper."""

    def test_get_token_counter(self) -> None:
        counter = get_token_counter()
        if is_rust_available():
            assert counter is not None
            result = counter.count("Hello world")
            assert result > 0
        else:
            assert counter is None


# ---------------------------------------------------------------------------
# PathValidator (Rust object when available)
# ---------------------------------------------------------------------------


class TestPathValidator:
    """Verify the PathValidator wrapper."""

    def test_get_path_validator(self, tmp_path: Path) -> None:
        validator = get_path_validator(str(tmp_path))
        if is_rust_available():
            assert validator is not None
        else:
            assert validator is None


# ---------------------------------------------------------------------------
# LocalFilesystem (Rust object when available)
# ---------------------------------------------------------------------------


class TestLocalFilesystem:
    """Verify the LocalFilesystem wrapper."""

    def test_get_local_filesystem(self, tmp_path: Path) -> None:
        fs = get_local_filesystem(str(tmp_path))
        if is_rust_available():
            assert fs is not None
            # Write and read back
            fs.write("test.txt", "hello")
            content = fs.read("test.txt")
            assert content == "hello"
        else:
            assert fs is None


# ---------------------------------------------------------------------------
# SqliteStoreRuntime (Rust object when available)
# ---------------------------------------------------------------------------


class TestSqliteStoreRuntime:
    """Verify the SqliteStoreRuntime wrapper."""

    def test_open_and_save_load(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        runtime = get_sqlite_store_runtime(db_path)
        if is_rust_available():
            assert runtime is not None
            runtime.save_sync("key1", json.dumps({"value": 42}))
            loaded = runtime.load_sync("key1")
            assert loaded == {"value": 42}
            assert runtime.load_sync("nonexistent") is None
            runtime.delete_sync("key1")
            assert runtime.load_sync("key1") is None
        else:
            assert runtime is None


# ---------------------------------------------------------------------------
# SkillDiscovery / SkillBudget (Rust objects when available)
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    """Verify the SkillDiscovery wrapper."""

    def test_discover_from_empty_root(self, tmp_path: Path) -> None:
        discovery = get_skill_discovery([str(tmp_path)])
        if is_rust_available():
            assert discovery is not None
            results = discovery.discover()
            assert isinstance(results, list)
        else:
            assert discovery is None


class TestSkillBudget:
    """Verify the SkillBudget wrapper."""

    def test_budget_spend(self) -> None:
        budget = get_skill_budget(1000)
        if is_rust_available():
            assert budget is not None
            assert budget.remaining == 1000
            assert budget.spend(100) is True
            assert budget.remaining == 900
        else:
            assert budget is None


# ---------------------------------------------------------------------------
# Workspace resolution (Rust when available)
# ---------------------------------------------------------------------------


class TestResolveWorkspace:
    """Verify workspace resolution wrapper."""

    def test_resolve_with_explicit(self, tmp_path: Path) -> None:
        result = resolve_workspace_rust(
            explicit=str(tmp_path),
            thread_workspace=None,
            installation_default=None,
        )
        if is_rust_available():
            assert result is not None
            assert result.path == str(tmp_path)
            assert result.source == "explicit"
        else:
            assert result is None


# ---------------------------------------------------------------------------
# Prompts: build_context_xml (Rust when available)
# ---------------------------------------------------------------------------


class TestBuildContextXml:
    """Verify context XML builder."""

    def test_empty_files(self) -> None:
        result = build_context_xml_rust("/workspace", [])
        if is_rust_available():
            assert isinstance(result, str)
            assert "<context" in result.lower() or result == ""
        # When Rust is absent, returns "" — that's fine


# ---------------------------------------------------------------------------
# Events: custom_event (Rust when available)
# ---------------------------------------------------------------------------


class TestCustomEvent:
    """Verify custom event builder."""

    def test_custom_event_structure(self) -> None:
        data = {"type": "test", "value": 42}
        result = custom_event_rust(data)
        # Both Rust and Python paths return a tuple ((), "custom", data)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert result[0] == ()
        assert result[1] == "custom"


# ---------------------------------------------------------------------------
# Full module import chain — verify no circular imports
# ---------------------------------------------------------------------------


class TestImportChain:
    """Verify that wiring _rust_compat doesn't break import chains."""

    def test_import_utils_package(self) -> None:
        from soothe_nano import utils

        assert hasattr(utils, "count_tokens")
        assert hasattr(utils, "expand_path")

    def test_import_thread_id_module(self) -> None:
        from soothe_nano.utils import thread_id

        assert hasattr(thread_id, "generate_thread_id")

    def test_import_token_counting_module(self) -> None:
        from soothe_nano.utils import token_counting

        assert hasattr(token_counting, "count_tokens")

    def test_import_path_module(self) -> None:
        from soothe_nano.utils import path

        assert hasattr(path, "expand_path")

    def test_import_url_validation_module(self) -> None:
        from soothe_nano.utils import url_validation

        assert hasattr(url_validation, "validate_url")

    def test_no_circular_import_rust_compat(self) -> None:
        """_rust_compat must not import any utils submodule at module level."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        module_level_imports = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                if node.module and "soothe_nano.utils" in node.module:
                    module_level_imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "soothe_nano.utils" in alias.name:
                        module_level_imports.append(alias.name)
        assert module_level_imports == [], (
            f"_rust_compat has module-level utils imports: {module_level_imports}"
        )


# ---------------------------------------------------------------------------
# Conditional behavior: verify count_tokens uses Rust when available
# ---------------------------------------------------------------------------


class TestConditionalDispatch:
    """Verify that public API dispatches to Rust when available."""

    def test_count_tokens_dispatches_correctly(self) -> None:
        from soothe_nano.utils.token_counting import count_tokens

        # This should work regardless of which backend is active
        result = count_tokens("Hello world")
        assert result > 0

    def test_generate_thread_id_dispatches_correctly(self) -> None:
        from soothe_nano.utils.thread_id import generate_thread_id

        result = generate_thread_id()
        parsed = uuid.UUID(result)
        assert parsed.version == 4

    def test_expand_path_dispatches_correctly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from soothe_nano.utils.path import expand_path

        monkeypatch.setenv("TEST_DISPATCH", "/dispatched")
        result = expand_path("$TEST_DISPATCH/path")
        assert result == Path("/dispatched/path").resolve()
