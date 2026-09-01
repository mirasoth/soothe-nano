# soothe-nano Development Guide

> **Binding conduct for all agents and human contributors working in this repository.**

**What soothe-nano is** — a batteries-included coding agent (`SootheNanoAgent`) built on `soothe-deepagents`. Provides workspace safety, progressive tools/skills, research subagents, MCP, and a config-driven factory.

**What this guide governs** — code standards, verification gates, and the release process.

---

## ⚠️ CRITICAL RULES

### 1. Verification Required
Run `make lint` and `make test-unit` before ANY commit. Zero lint errors, all tests pass.

### 2. After Code Impl: Cleanse → Verify → Fix
Before marking work done (commit, PR, or handoff):
1. Remove superseded helpers, unused exports, compat shims, stale tests/docs. Deletion/consolidation only; **no behavior rewrites**.
2. `make lint && make test-unit`
3. Fix to green. Re-cleanse if fixes leave new dead code, then re-verify until green.

### 3. Terminology
- NEVER expose internal ticket IDs in user-facing text (logs, CLI, errors, config descriptions). Comments and internal docs are fine.

### 4. Docstring Standards
Brief and sharp. One-line module docstrings. No verbose prose. Function docstrings: one-line summary, then args/returns only if non-obvious.

### 5. Test Location
Tests go in `tests/unit/` or `tests/integration/`. Unit tests run by default; integration tests require `--run-integration`.

---

## Release Process (MUST)

A **release** = bumping the version, making CI green, pushing the tag, and creating a **GitHub Release object** that triggers the `release.yml` workflow to publish to PyPI. **Never publish to PyPI directly via `make publish`, `uv publish`, or `twine upload`.**

### Pre-release gates

1. **Verify upstream deps** — check that `soothe-sdk` and `soothe-deepagents` on PyPI are compatible with the version being released. If a floor bump is needed, release the upstream package first.
2. **Default to patch** — release a patch bump (e.g. `1.2.21 → 1.2.22`). Do not cut minor/major unless explicitly approved.
3. **Verify before release** — `make lint` and `make test-unit` MUST pass on the commit being tagged. CI MUST be green before creating the GitHub Release.

### Version bump + changelog

4. **Bump `version` in `pyproject.toml`** — e.g. `version = "1.2.22"`.
5. **Promote the `[Unreleased]` block** in `CHANGELOG.md` into a dated `## [X.Y.Z] - YYYY-MM-DD` entry with a `[Compare with previous version]` link. Reset `[Unreleased]` to empty. Follow [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format.
6. **Commit the bump** — e.g. `chore(release): bump to X.Y.Z` touching only `pyproject.toml` + `CHANGELOG.md`.

### Tag + GitHub Release (the trigger)

7. **Push to main** — `git push origin main`. Wait for CI to pass.
8. **Tag the release commit** — `git tag -a vX.Y.Z -m "vX.Y.Z"`.
9. **Push the tag** — `git push origin vX.Y.Z`.
10. **Create the GitHub Release object** — `gh release create vX.Y.Z --target main --title "vX.Y.Z" --notes-file <release-notes.md> --latest`. **This is the trigger.** A bare git tag does NOT fire the workflow — only the `release: published` event does.

### What the workflow does (do not replicate manually)

11. **`release.yml`** fires on `release: published` (or `workflow_dispatch`). It:
    - Checks if the version already exists on PyPI (idempotent — skips if present)
    - Runs `make format-check`, `make lint`, `make test-unit`
    - Builds the package (`make build`)
    - Publishes to PyPI via `pypa/gh-action-pypi-publish` (trusted publishing / `UV_PUBLISH_TOKEN`)

12. **Do not publish to PyPI by hand.** The only exception is recovering from a transient PyPI 500/timeout — in that case, `uv build` + `uv publish dist/*` for the affected version only, then verify.

### Verify the release landed

13. **Confirm on PyPI** — `curl -sL https://pypi.org/pypi/soothe-nano/json | grep version` shows the new version.
14. **Confirm the workflow ran green** — `gh run list --repo mirasoth/soothe-nano --limit 5`; the "Release" workflow must show `success`.
15. **Confirm the GitHub Release** — `gh release view vX.Y.Z --repo mirasoth/soothe-nano` shows `published` and `isLatest: true`.

---

## Development

### Sync dependencies
```bash
make sync
```

### Format / lint / test
```bash
make format          # ruff format
make lint            # ruff check
make test-unit       # pytest tests/unit/
make autofix         # format + auto-fix lint
```

### Build
```bash
make build           # uv build --out-dir dist
```

### Clean
```bash
make clean
```
