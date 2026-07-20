# Makefile for soothe-nano Package
#
# Manages the soothe-nano package independently (coding CoreAgent).
# In the monorepo, prefer root `make sync` / `uv sync --all-packages` and run
# format/lint/test targets here without sync-dev (avoids pruning the workspace).
#
# Optional: set UV_RUN='uv run --no-sync' after a forced SDK override in CI.
UV_RUN ?= uv run

.PHONY: sync sync-dev format format-check lint lint-fix \
	test test-unit test-integration test-coverage \
	examples example-01 example-02 example-03 example-04 example-05 \
	build publish publish-test clean help

# Default target
help:
	@echo "soothe-nano Package"
	@echo ""
	@echo "Development:"
	@echo "  make sync            - Sync dependencies with uv"
	@echo "  make sync-dev        - Sync dev dependencies"
	@echo "  make format          - Format code with ruff"
	@echo "  make format-check    - Check code formatting (for CI)"
	@echo "  make lint            - Lint code with ruff"
	@echo "  make lint-fix        - Auto-fix linting issues with ruff"
	@echo ""
	@echo "Testing:"
	@echo "  make test            - Run unit + integration tests"
	@echo "  make test-unit       - Run unit tests only"
	@echo "  make test-integration - Run integration tests (--run-integration)"
	@echo "  make test-coverage   - Run tests with coverage report"
	@echo ""
	@echo "Examples:"
	@echo "  make examples        - Run all nano_agent examples"
	@echo "  make example-01      - Pure model (no tools)"
	@echo "  make example-02      - With tools"
	@echo "  make example-03      - With memory"
	@echo "  make example-04      - With subagents"
	@echo "  make example-05      - Full composition"
	@echo ""
	@echo "Building & Publishing:"
	@echo "  make build           - Build the package"
	@echo "  make publish         - Publish package to PyPI"
	@echo "  make publish-test    - Publish package to TestPyPI"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean           - Clean build artifacts"

# Sync dependencies (standalone package / CI)
sync:
	@echo "Syncing dependencies..."
	uv sync
	@echo "✓ Dependencies synced"

# Sync dev dependencies (standalone package / CI)
sync-dev:
	@echo "Syncing dev dependencies..."
	uv sync --extra dev
	@echo "✓ Dev dependencies synced"

# Format code
format:
	@echo "Formatting code..."
	$(UV_RUN) ruff format src/ tests/ examples/
	@echo "✓ Code formatted"

# Check formatting (for CI)
format-check:
	@echo "Checking code formatting..."
	$(UV_RUN) ruff format --check src/ tests/ examples/
	@echo "✓ Format check passed"

# Lint code
lint:
	@echo "Linting code..."
	$(UV_RUN) ruff check src/ tests/ examples/
	@echo "✓ Linting complete"

# Auto-fix linting issues
lint-fix:
	@echo "Auto-fixing linting issues..."
	$(UV_RUN) ruff check --fix src/ tests/ examples/
	@echo "✓ Linting issues fixed"

# Run all tests
test: test-unit test-integration
	@echo "✓ All tests complete"

# Run unit tests only
test-unit:
	@echo "Running unit tests..."
	$(UV_RUN) pytest tests/unit/ -v --tb=short
	@echo "✓ Unit tests complete"

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
examples: example-01 example-02 example-03 example-04 example-05
	@echo "✓ All examples complete"

example-01:
	$(UV_RUN) python examples/nano_agent/01_pure_nano_example.py

example-02:
	$(UV_RUN) python examples/nano_agent/02_nano_with_tools_example.py

example-03:
	$(UV_RUN) python examples/nano_agent/03_nano_with_memory_example.py

example-04:
	$(UV_RUN) python examples/nano_agent/04_nano_with_subagents_example.py

example-05:
	$(UV_RUN) python examples/nano_agent/05_nano_full_composition_example.py

# Build package
build:
	@echo "Building package..."
	uv build --out-dir dist
	@echo "✓ Package built"

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
	@echo "✓ Build artifacts cleaned"
