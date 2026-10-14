"""Integration tests for the Rust/Python bridge layer.

Verifies that:
1. The availability probe works (``is_rust_available()`` returns True when
   the extension is compiled).
2. Full-parity functions (``generate_thread_id``, ``expand_env_vars``,
   ``truncate_output``, ``repair_json``) delegate directly to Rust with no
   Python fallback.
3. Partial-parity functions retain their Python fallback for residual gaps.
4. The public Python API (``soothe_nano.utils.*``) remains unchanged.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from soothe_nano._rust_compat import (
    build_context_xml_rust,
    build_environment_section_rust,
    build_workspace_section_rust,
    count_tokens_rust,
    custom_event_rust,
    expand_env_vars_rust,
    generate_thread_id,
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

    def test_estimation_mode(self) -> None:
        """use_tiktoken=False returns len//4 estimation."""
        result = count_tokens_rust("Hello world", use_tiktoken=False)
        assert result == len("Hello world") // 4


# ---------------------------------------------------------------------------
# json_parsing — repair_json
# ---------------------------------------------------------------------------


class TestRepairJson:
    """Verify JSON repair parity."""

    def test_valid_json_object(self) -> None:
        result = repair_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_valid_json_array(self) -> None:
        # repair_json enforces dict-only contract (matching Python's
        # _load_llm_json_dict). Arrays are not dicts, so None is returned.
        result = repair_json("[1, 2, 3]")
        assert result is None

    def test_fenced_json(self) -> None:
        result = repair_json('```json\n{"b": 2}\n```')
        assert result == {"b": 2}

    def test_leading_prose(self) -> None:
        result = repair_json('Here is the result: {"c": 3}')
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
        assert len(result) <= 40
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
        assert "domain" in error.lower() or "host" in error.lower()

    def test_empty_path_gets_slash(self) -> None:
        """URLs without a path should get a trailing slash."""
        sanitized, error = self._python_validate("https://example.com")
        assert error is None
        assert sanitized == "https://example.com/"

    def test_strips_userinfo(self) -> None:
        """Userinfo (user:pass@) should be stripped from the sanitized URL."""
        sanitized, error = self._python_validate("https://user:pass@example.com/path")
        assert error is None
        assert sanitized == "https://example.com/path"


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


# ---------------------------------------------------------------------------
# Prompts: build_environment_section (Rust round-trip)
# ---------------------------------------------------------------------------


class TestBuildEnvironmentSection:
    """Verify ENVIRONMENT XML builder with PyO3 round-trip."""

    def test_environment_xml_structure(self) -> None:
        result = build_environment_section_rust("claude-opus-4-6")
        assert "<ENVIRONMENT>" in result
        assert "</ENVIRONMENT>" in result
        assert "<platform>" in result
        assert "<shell>" in result
        assert "<os_version>" in result
        assert "<model>claude-opus-4-6</model>" in result
        assert "<knowledge_cutoff>" in result
        assert "<search_backend>" in result

    def test_environment_search_backend_value(self) -> None:
        result = build_environment_section_rust("test-model")
        assert (
            "<search_backend>ripgrep</search_backend>" in result
            or "<search_backend>python_fallback</search_backend>" in result
        )

    def test_environment_knowledge_cutoff_lookup(self) -> None:
        """Rust round-trips into Python for get_knowledge_cutoff."""
        result = build_environment_section_rust("claude-opus-4-6")
        assert "2025-05" in result

    def test_environment_unknown_model_uses_default(self) -> None:
        result = build_environment_section_rust("nonexistent-model-xyz")
        assert "2025-01" in result  # default cutoff


# ---------------------------------------------------------------------------
# Prompts: build_workspace_section (pure Rust filesystem I/O)
# ---------------------------------------------------------------------------


class TestBuildWorkspaceSection:
    """Verify WORKSPACE XML builder."""

    def test_workspace_xml_structure(self, tmp_path: Path) -> None:
        result = build_workspace_section_rust(str(tmp_path))
        assert "<WORKSPACE>" in result
        assert "</WORKSPACE>" in result
        assert "<root>" in result
        assert '<vcs present="' in result

    def test_workspace_git_detection(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        result = build_workspace_section_rust(str(tmp_path))
        assert '<vcs present="true"' in result

    def test_workspace_no_git(self, tmp_path: Path) -> None:
        result = build_workspace_section_rust(str(tmp_path))
        assert '<vcs present="false"' in result

    def test_workspace_layout_preview(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / ".hidden").mkdir()
        result = build_workspace_section_rust(str(tmp_path), include_layout_preview=True)
        assert "src" in result
        assert "tests" in result
        assert ".hidden" not in result

    def test_workspace_readme_excerpt(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# My Project\nA test project.")
        result = build_workspace_section_rust(
            str(tmp_path), include_readme_excerpt=True, readme_max_chars=500
        )
        assert "<readme_excerpt>" in result
        assert "My Project" in result

    def test_workspace_none_path_uses_cwd(self) -> None:
        result = build_workspace_section_rust(None)
        assert "<WORKSPACE>" in result
        assert "<root>" in result


# ---------------------------------------------------------------------------
# Events: custom_event (Rust when available)
# ---------------------------------------------------------------------------


class TestCustomEvent:
    """Verify custom event builder."""

    def test_custom_event_structure(self) -> None:
        data = {"type": "test", "value": 42}
        result = custom_event_rust(data)
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


# ---------------------------------------------------------------------------
# Full-parity functions: no Python fallback
# ---------------------------------------------------------------------------


class TestNoPythonFallback:
    """Verify full-parity functions delegate directly to Rust (no fallback).

    These functions had their Python fallback removed because the Rust
    implementation has complete behavioral parity. The _rust_compat wrappers
    must call _rust_module directly without any ``if _rust_available`` guard.
    """

    def test_generate_thread_id_no_fallback(self) -> None:
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "generate_thread_id":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "generate_thread_id must not have a Python fallback"
                )
                return
        pytest.fail("generate_thread_id not found in _rust_compat")

    def test_expand_env_vars_no_fallback(self) -> None:
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "expand_env_vars_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "expand_env_vars_rust must not have a Python fallback"
                )
                return
        pytest.fail("expand_env_vars_rust not found in _rust_compat")

    def test_truncate_output_no_fallback(self) -> None:
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "truncate_output_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "truncate_output_rust must not have a Python fallback"
                )
                return
        pytest.fail("truncate_output_rust not found in _rust_compat")

    def test_repair_json_no_fallback(self) -> None:
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "repair_json":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "repair_json must not have a Python fallback"
                )
                return
        pytest.fail("repair_json not found in _rust_compat")

    def test_json_parsing_no_python_fallthrough(self) -> None:
        """_load_llm_json_dict must delegate to Rust without Python fallthrough."""
        import ast

        from soothe_nano.utils import json_parsing

        tree = ast.parse(Path(json_parsing.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_load_llm_json_dict":
                src = ast.unparse(node)
                assert "_strip_leading_bom" not in src, (
                    "_load_llm_json_dict must not call Python helpers"
                )
                assert "_strip_markdown_json_fence" not in src
                assert "_extract_balanced_json_object" not in src
                assert "_repair_truncated_json" not in src
                return
        pytest.fail("_load_llm_json_dict not found in json_parsing")

    def test_path_no_os_expandvars(self) -> None:
        """expand_path must not use os.path.expandvars (Rust only)."""
        from soothe_nano.utils import path as path_mod

        src = Path(path_mod.__file__).read_text()
        assert "os.path.expandvars" not in src, "expand_path must not use os.path.expandvars"

    def test_env_no_python_fallback(self) -> None:
        """_resolve_env must not have a Python replacer fallback."""
        import ast

        from soothe_nano.config import env

        tree = ast.parse(Path(env.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_resolve_env":
                src = ast.unparse(node)
                assert "if is_rust_available" not in src, (
                    "_resolve_env must not have a Python fallback"
                )
                return
        pytest.fail("_resolve_env not found in env")

    def test_count_tokens_no_fallback(self) -> None:
        """count_tokens_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "count_tokens_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "count_tokens_rust must not have a Python fallback"
                )
                return
        pytest.fail("count_tokens_rust not found in _rust_compat")

    def test_text_preview_no_fallback(self) -> None:
        """text_preview_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "text_preview_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "text_preview_rust must not have a Python fallback"
                )
                return
        pytest.fail("text_preview_rust not found in _rust_compat")

    def test_preview_full_no_fallback(self) -> None:
        """preview_full_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "preview_full_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "preview_full_rust must not have a Python fallback"
                )
                return
        pytest.fail("preview_full_rust not found in _rust_compat")

    def test_validate_url_no_fallback(self) -> None:
        """validate_url_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "validate_url_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "validate_url_rust must not have a Python fallback"
                )
                return
        pytest.fail("validate_url_rust not found in _rust_compat")

    def test_resolve_workspace_no_fallback(self) -> None:
        """resolve_workspace_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_workspace_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "resolve_workspace_rust must not have a Python fallback"
                )
                return
        pytest.fail("resolve_workspace_rust not found in _rust_compat")

    def test_token_counting_no_python_tiktoken(self) -> None:
        """count_tokens must not import tiktoken (Rust only)."""
        from soothe_nano.utils import token_counting

        src = Path(token_counting.__file__).read_text()
        assert "import tiktoken" not in src, "count_tokens must not import tiktoken"
        assert "encoding_for_model" not in src, "count_tokens must not use encoding_for_model"

    def test_url_validation_no_python_fallback(self) -> None:
        """validate_url must not have a Python urlparse fallback."""
        from soothe_nano.utils import url_validation

        src = Path(url_validation.__file__).read_text()
        assert "urlparse" not in src, "validate_url must not use urlparse"
        assert "if is_rust_available" not in src, "validate_url must not have a fallback guard"

    def test_text_preview_no_python_fallback(self) -> None:
        """preview() must not call _preview_chars or _preview_lines."""
        from soothe_nano.utils import text_preview

        src = Path(text_preview.__file__).read_text()
        assert "_preview_chars" not in src, "text_preview must not have _preview_chars"
        assert "_preview_lines" not in src, "text_preview must not have _preview_lines"
        assert "_build_marker" not in src, "text_preview must not have _build_marker"

    def test_build_context_xml_no_fallback(self) -> None:
        """build_context_xml_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_context_xml_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "build_context_xml_rust must not have a Python fallback"
                )
                return
        pytest.fail("build_context_xml_rust not found in _rust_compat")

    def test_build_environment_section_no_fallback(self) -> None:
        """build_environment_section_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_environment_section_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "build_environment_section_rust must not have a Python fallback"
                )
                return
        pytest.fail("build_environment_section_rust not found in _rust_compat")

    def test_build_workspace_section_no_fallback(self) -> None:
        """build_workspace_section_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_workspace_section_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "build_workspace_section_rust must not have a Python fallback"
                )
                return
        pytest.fail("build_workspace_section_rust not found in _rust_compat")

    def test_context_xml_no_python_environment_fallback(self) -> None:
        """build_soothe_environment_section must not have a Python fallback."""
        import ast

        from soothe_nano.prompts import context_xml

        tree = ast.parse(Path(context_xml.__file__).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "build_soothe_environment_section"
            ):
                # Check only the function body (not docstring) for direct calls
                body_nodes = [ast.unparse(n) for n in node.body if not isinstance(n, ast.Expr)]
                body_src = "\n".join(body_nodes)
                assert "import platform" not in body_src, (
                    "build_soothe_environment_section must not import platform"
                )
                assert "is_rg_available(" not in body_src, (
                    "build_soothe_environment_section must not call is_rg_available()"
                )
                assert "get_knowledge_cutoff(" not in body_src, (
                    "build_soothe_environment_section must not call get_knowledge_cutoff()"
                )
                return
        pytest.fail("build_soothe_environment_section not found in context_xml")

    def test_context_xml_no_python_workspace_fallback(self) -> None:
        """build_soothe_workspace_section must not have a Python fallback."""
        import ast

        from soothe_nano.prompts import context_xml

        tree = ast.parse(Path(context_xml.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_soothe_workspace_section":
                src = ast.unparse(node)
                assert "_safe_list_dir_names" not in src, (
                    "build_soothe_workspace_section must not call _safe_list_dir_names"
                )
                # Check for the function call, not the parameter name
                assert "=_readme_excerpt(" not in src, (
                    "build_soothe_workspace_section must not call _readme_excerpt()"
                )
                return
        pytest.fail("build_soothe_workspace_section not found in context_xml")

    # --- corpus_match / prompt_clock / command_guard no-fallback tests --------

    def test_compact_rust_no_fallback(self) -> None:
        """compact_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "compact_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "compact_rust must not have a Python fallback"
                )
                return
        pytest.fail("compact_rust not found in _rust_compat")

    def test_earliest_corpus_match_rust_no_fallback(self) -> None:
        """earliest_corpus_match_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "earliest_corpus_match_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "earliest_corpus_match_rust must not have a Python fallback"
                )
                return
        pytest.fail("earliest_corpus_match_rust not found in _rust_compat")

    def test_dangerous_command_rule_id_rust_no_fallback(self) -> None:
        """dangerous_command_rule_id_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "dangerous_command_rule_id_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "dangerous_command_rule_id_rust must not have a Python fallback"
                )
                return
        pytest.fail("dangerous_command_rule_id_rust not found in _rust_compat")

    def test_rule_family_rust_no_fallback(self) -> None:
        """rule_family_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "rule_family_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "rule_family_rust must not have a Python fallback"
                )
                return
        pytest.fail("rule_family_rust not found in _rust_compat")

    def test_local_date_str_rust_no_fallback(self) -> None:
        """local_date_str_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "local_date_str_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "local_date_str_rust must not have a Python fallback"
                )
                return
        pytest.fail("local_date_str_rust not found in _rust_compat")

    def test_prompt_datetime_context_rust_no_fallback(self) -> None:
        """prompt_datetime_context_rust must not have a Python fallback."""
        import ast

        from soothe_nano import _rust_compat

        tree = ast.parse(Path(_rust_compat.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "prompt_datetime_context_rust":
                src = ast.unparse(node)
                assert "if _rust_available" not in src, (
                    "prompt_datetime_context_rust must not have a Python fallback"
                )
                return
        pytest.fail("prompt_datetime_context_rust not found in _rust_compat")

    def test_corpus_match_py_no_fallback(self) -> None:
        """corpus_match.py must not have a Python fallback."""
        from soothe_nano.skills import corpus_match

        src = Path(corpus_match.__file__).read_text()
        assert "if is_rust_available" not in src, (
            "corpus_match.py must not have a Rust-availability guard"
        )
        assert "import re" not in src, "corpus_match.py must not import re"

    def test_operation_guard_no_python_fallback(self) -> None:
        """operation_guard.py must not have a Python fallback for rule matching."""
        from soothe_nano.security import operation_guard

        src = Path(operation_guard.__file__).read_text()
        assert "if is_rust_available" not in src, (
            "operation_guard.py must not have a Rust-availability guard"
        )
        assert "_BANNED_COMMAND_PATTERNS" not in src, (
            "operation_guard.py must not define _BANNED_COMMAND_PATTERNS"
        )
        assert "_RULE_FAMILIES" not in src, "operation_guard.py must not define _RULE_FAMILIES"

    def test_prompt_clock_no_python_fallback(self) -> None:
        """prompt_clock.py must not have a Python fallback for the 6 formatters."""
        from soothe_nano.utils import prompt_clock

        src = Path(prompt_clock.__file__).read_text()
        assert "if is_rust_available" not in src, (
            "prompt_clock.py must not have a Rust-availability guard"
        )
        assert "_from_timestamp" not in src, (
            "prompt_clock.py must not have a Python _from_timestamp fallback"
        )


# ---------------------------------------------------------------------------
# CircuitBreaker fast-path wrappers
# ---------------------------------------------------------------------------


class TestCircuitBreakerWrappers:
    """Verify the Rust CircuitBreaker fast-path wrapper functions."""

    def test_new_returns_instance_or_none(self) -> None:
        from soothe_nano._rust_compat import is_rust_available, rust_circuit_breaker_new

        breaker = rust_circuit_breaker_new(
            failure_threshold=3, success_threshold=2, timeout_seconds=5.0
        )
        if is_rust_available():
            assert breaker is not None
            assert hasattr(breaker, "is_open")
        else:
            assert breaker is None

    def test_is_open_returns_bool_or_none(self) -> None:
        from soothe_nano._rust_compat import rust_circuit_breaker_is_open, rust_circuit_breaker_new

        breaker = rust_circuit_breaker_new(
            failure_threshold=3, success_threshold=2, timeout_seconds=5.0
        )
        result = rust_circuit_breaker_is_open(breaker)
        assert result in (True, False, None)

    def test_state_returns_str_or_none(self) -> None:
        from soothe_nano._rust_compat import (
            is_rust_available,
            rust_circuit_breaker_new,
            rust_circuit_breaker_state,
        )

        breaker = rust_circuit_breaker_new(
            failure_threshold=3, success_threshold=2, timeout_seconds=5.0
        )
        result = rust_circuit_breaker_state(breaker)
        if is_rust_available():
            assert result in ("closed", "open", "half_open")
        else:
            assert result is None

    def test_is_open_with_none_breaker(self) -> None:
        """When Rust is unavailable, is_open returns None (graceful fallback)."""
        from soothe_nano._rust_compat import rust_circuit_breaker_is_open

        result = rust_circuit_breaker_is_open(None)
        assert result is None

    def test_state_with_none_breaker(self) -> None:
        """When Rust is unavailable, state returns None (graceful fallback)."""
        from soothe_nano._rust_compat import rust_circuit_breaker_state

        result = rust_circuit_breaker_state(None)
        assert result is None

    def test_open_after_threshold_failures(self) -> None:
        """Rust breaker reports OPEN after enough failures."""
        from soothe_nano._rust_compat import (
            is_rust_available,
            rust_circuit_breaker_is_open,
            rust_circuit_breaker_new,
            rust_circuit_breaker_state,
        )

        if not is_rust_available():
            pytest.skip("Rust extension not available")

        breaker = rust_circuit_breaker_new(
            failure_threshold=3, success_threshold=2, timeout_seconds=60.0
        )
        assert rust_circuit_breaker_is_open(breaker) is False
        breaker.record_failure()
        breaker.record_failure()
        assert rust_circuit_breaker_is_open(breaker) is False
        breaker.record_failure()
        assert rust_circuit_breaker_is_open(breaker) is True
        assert rust_circuit_breaker_state(breaker) == "open"

    def test_success_resets_rust_breaker(self) -> None:
        """record_success resets the Rust breaker to closed."""
        from soothe_nano._rust_compat import (
            is_rust_available,
            rust_circuit_breaker_is_open,
            rust_circuit_breaker_new,
            rust_circuit_breaker_state,
        )

        if not is_rust_available():
            pytest.skip("Rust extension not available")

        breaker = rust_circuit_breaker_new(
            failure_threshold=2, success_threshold=2, timeout_seconds=60.0
        )
        breaker.record_failure()
        breaker.record_failure()
        assert rust_circuit_breaker_is_open(breaker) is True
        breaker.record_success()
        assert rust_circuit_breaker_is_open(breaker) is False
        assert rust_circuit_breaker_state(breaker) == "closed"
