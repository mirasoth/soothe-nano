# Makefile for soothe-nano Package
#
# Manages the soothe-nano package independently (coding CoreAgent).
# In the monorepo, prefer root `make sync` / `uv sync --all-packages` and run
# format/lint/test targets here without sync (avoids pruning the workspace).
#
# Optional: set UV_RUN='uv run --no-sync' after a forced SDK override in CI.
UV_RUN ?= uv run

# Rust / cargo settings.  CARGO is the cargo binary; CRATES_DIR is the
# workspace root for all Rust crates.
CARGO ?= cargo
CRATES_DIR ?= crates
CARGO_FMT_FLAGS ?= --all
CARGO_CLIPPY_FLAGS ?= --workspace --all-targets -- -D warnings

.PHONY: sync format format-check lint lint-fix autofix \
	format-rust format-rust-check lint-rust \
	test test-unit test-integration test-coverage \
	test-rust \
	examples example-01 example-02 example-03 example-04 example-05 \
	example-06 example-07 \
	build build-dev publish publish-test clean help

# Default target
help:
	@echo "soothe-nano Package"
	@echo ""
	@echo "Development:"
	@echo "  make sync            - Sync dev dependencies with uv"
	@echo "  make format          - Format Python (ruff) + Rust (rustfmt) code"
	@echo "  make format-check    - Check formatting (for CI)"
	@echo "  make lint            - Lint Python (ruff) + Rust (clippy) code"
	@echo "  make lint-fix        - Auto-fix linting issues with ruff"
	@echo "  make autofix         - Format code and auto-fix linting issues"
	@echo "  make format-rust     - Format Rust crates with rustfmt"
	@echo "  make format-rust-check - Check Rust formatting (for CI)"
	@echo "  make lint-rust       - Lint Rust crates with clippy (-D warnings)"
	@echo ""
	@echo "Testing:"
	@echo "  make test            - Run unit + integration tests (Python + Rust)"
	@echo "  make test-unit       - Run Python unit tests + Rust tests"
	@echo "  make test-integration - Run integration tests (--run-integration)"
	@echo "  make test-coverage   - Run tests with coverage report"
	@echo "  make test-rust       - Run Rust crate tests only"
	@echo ""
	@echo "Examples:"
	@echo "  make examples        - Run all examples"
	@echo "  make example-01      - Pure model (no tools)"
	@echo "  make example-02      - With tools"
	@echo "  make example-03      - With memory"
	@echo "  make example-04      - With subagents"
	@echo "  make example-05      - Full composition"
	@echo "  make example-06      - Computer use (desktop GUI) subagent"
	@echo "  make example-07      - Computer use: WeChat Favorites link harvest"
	@echo ""
	@echo "Building & Publishing:"
	@echo "  make build           - Build wheel (maturin, Python + Rust)"
	@echo "  make build-dev       - Compile Rust extension in-place (maturin develop)"
	@echo "  make publish         - Publish wheel to PyPI (via release workflow)"
	@echo "  make publish-test    - Publish package to TestPyPI"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean           - Clean build artifacts"

# Sync dev dependencies (standalone package / CI)
sync:
	@echo "Syncing dev dependencies..."
	uv sync --extra dev
	@echo "✓ Dev dependencies synced"

# Format code. No --preview: match root `make format` and verify_finally.sh,
# which run stable ruff. docstring-code-format (set in [tool.ruff.format])
# is the stable knob for markdown code-block formatting in docstrings.
format: format-python format-rust
	@echo "✓ Code formatted (Python + Rust)"

format-python:
	@echo "Formatting Python code..."
	$(UV_RUN) ruff format src/ tests/ examples/
	@echo "✓ Python code formatted"

# Format Rust crates with rustfmt.
format-rust:
	@echo "Formatting Rust crates..."
	cd $(CRATES_DIR) && $(CARGO) fmt $(CARGO_FMT_FLAGS)
	@echo "✓ Rust crates formatted"

# Check formatting (for CI). Same stable-ruff semantics as `format`.
format-check: format-python-check format-rust-check
	@echo "✓ Format check passed (Python + Rust)"

format-python-check:
	@echo "Checking Python code formatting..."
	$(UV_RUN) ruff format --check src/ tests/ examples/
	@echo "✓ Python format check passed"

# Check Rust formatting (for CI).
format-rust-check:
	@echo "Checking Rust formatting..."
	cd $(CRATES_DIR) && $(CARGO) fmt $(CARGO_FMT_FLAGS) -- --check
	@echo "✓ Rust format check passed"

# Lint code
lint: lint-python lint-rust
	@echo "✓ Linting complete (Python + Rust)"

lint-python:
	@echo "Linting Python code..."
	$(UV_RUN) ruff check src/ tests/ examples/
	@echo "✓ Python linting complete"

# Lint Rust crates with clippy (warnings are errors).
lint-rust:
	@echo "Linting Rust crates with clippy..."
	cd $(CRATES_DIR) && $(CARGO) clippy $(CARGO_CLIPPY_FLAGS)
	@echo "✓ Rust linting complete"

# Auto-fix linting issues
lint-fix:
	@echo "Auto-fixing linting issues..."
	$(UV_RUN) ruff check --fix src/ tests/ examples/
	@echo "✓ Linting issues fixed"

# Format code then auto-fix linting issues
autofix: format lint-fix
	@echo "✓ Auto-fix complete"

# Run all tests
test: test-unit test-integration
	@echo "✓ All tests complete (Python + Rust)"

# Run unit tests only (Python + Rust)
test-unit: test-python-unit test-rust
	@echo "✓ Unit tests complete (Python + Rust)"

test-python-unit:
	@echo "Running Python unit tests..."
	$(UV_RUN) pytest tests/unit/ -v --tb=short
	@echo "✓ Python unit tests complete"

# Run Rust crate tests only.
test-rust:
	@echo "Running Rust crate tests..."
	cd $(CRATES_DIR) && $(CARGO) test --workspace
	@echo "✓ Rust tests complete"

# Run integration tests (requires --run-integration)
test-integration:
	@echo "Running integration tests..."
	$(UV_RUN) pytest tests/integration/ --run-integration -v --tb=short
	@echo "✓ Integration tests complete"

# Run tests with coverage
test-coverage:
	@echo "Running tests with coverage..."
	$(UV_RUN) pytest tests/unit/ --cov=soothe_nano --cov-report=term-missing --cov-report=html
	@echo "✓ Coverage report generated in htmlcov/"

# Examples
examples: example-01 example-02 example-03 example-04 example-05 example-06 example-07
	@echo "✓ All examples complete"

example-01:
	$(UV_RUN) python examples/01_pure_nano_example.py

example-02:
	$(UV_RUN) python examples/02_nano_with_tools_example.py

example-03:
	$(UV_RUN) python examples/03_nano_with_memory_example.py

example-04:
	$(UV_RUN) python examples/04_nano_with_subagents_example.py

example-05:
	$(UV_RUN) python examples/05_nano_full_composition_example.py

# Desktop GUI automation: requires a display server and (macOS) Accessibility +
# Screen Recording permissions for the terminal/IDE.
example-06:
	$(UV_RUN) python examples/06_nano_computer_use_example.py

example-07:
	$(UV_RUN) python examples/07_nano_computer_use_weixin_favorites.py

# Build package (Python + Rust extension via maturin)
build:
	@echo "Building package (maturin)..."
	maturin build --release --out dist --manifest-path crates/soothe-nano-sys/Cargo.toml
	@echo "✓ Package built"

# Build in-place (compile Rust extension into src/soothe_nano/ for development)
build-dev:
	@echo "Building Rust extension in-place (maturin develop)..."
	maturin develop --manifest-path crates/soothe-nano-sys/Cargo.toml
	@echo "✓ Rust extension compiled into src/soothe_nano/_rust"

# Publish package to PyPI
publish:
	@echo "Publishing package to PyPI..."
	uv publish dist/* --native-tls
	@echo "✓ Package published to PyPI"

# Publish package to TestPyPI
publish-test:
	@echo "Publishing package to TestPyPI..."
	uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "✓ Package published to TestPyPI"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf dist/ *.egg-info .pytest_cache .coverage .ruff_cache htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find src/soothe_nano -name "*.so" -delete 2>/dev/null || true
	cd $(CRATES_DIR) && $(CARGO) clean 2>/dev/null || true
	rm -rf $(CRATES_DIR)/target/
	@echo "✓ Build artifacts cleaned"
