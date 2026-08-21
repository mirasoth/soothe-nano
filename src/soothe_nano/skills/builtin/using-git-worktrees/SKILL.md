---
name: using-git-worktrees
description: >
  Use when starting feature work that needs isolation from the current checkout.
  Creates a git worktree under .soothe/worktrees/.
tags: git, worktree, isolation, .soothe/worktrees
when_to_use: >
  Use when starting feature work that needs isolation from the current
  checkout — creates a git worktree under .soothe/worktrees/.
---

# Using Git Worktrees

Isolate work in a linked git worktree under **`.soothe/worktrees/<slug>`**,
alongside other workspace-local Soothe state under `.soothe/`.

**Core principle:** Detect existing isolation first. Reuse it. Only create a
new worktree from the primary checkout when isolation is needed.

## Step 0: Detect existing isolation

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
PWD_REAL=$(pwd -P)
REPO=$(git rev-parse --show-toplevel 2>/dev/null)
```

**Submodule guard:** `GIT_DIR != GIT_COMMON` is also true in submodules. If
`git rev-parse --show-superproject-working-tree` returns a path, treat as a
normal repo (not an isolated worktree).

**Already isolated** when either:

1. `GIT_DIR != GIT_COMMON` and not a submodule, or
2. `$PWD_REAL` is under `$REPO/.soothe/worktrees/`

→ Do **not** create another worktree. Continue in place.

Report:

- On a branch: `Already in isolated workspace at <path> on branch <name>.`
- Detached HEAD: `Already in isolated workspace at <path> (detached HEAD).`

**Primary checkout:** if the user has not already asked for isolation, confirm:

> Set up an isolated worktree under `.soothe/worktrees/`? It keeps the current
> branch clean.

If declined → work in place.

## Step 1: Create the worktree

### Location and naming

| Item | Convention |
|------|------------|
| Directory | `<repo>/.soothe/worktrees/<slug>` |
| Branch | short descriptive name (e.g. `feat/add-login`) |
| Slug | from the branch or task; alphanumeric, `-`, `_`; ~48 chars |

Explicit user path or branch always wins. Do not use `.worktrees/` or
`worktrees/` unless the user asks for that layout.

### Ensure `.soothe/` is ignored

```bash
git check-ignore -q .soothe || git check-ignore -q .soothe/worktrees
```

If not ignored, add `.soothe/` to `.gitignore` before creating the worktree so
worktree contents are not tracked.

### Create

```bash
REPO=$(git rev-parse --show-toplevel)
SLUG="<slug>"
BRANCH_NAME="<branch>"
PATH_WT="$REPO/.soothe/worktrees/$SLUG"

mkdir -p "$(dirname "$PATH_WT")"
git worktree add -b "$BRANCH_NAME" "$PATH_WT"
# If the branch already exists:
# git worktree add "$PATH_WT" "$BRANCH_NAME"

cd "$PATH_WT"
```

If creation fails (permissions, nested worktree, etc.): say so and continue in
the current directory. Never nest a worktree inside another.

## Step 2: Project setup

Run only what the repo needs:

```bash
[ -f package.json ] && npm install
[ -f Cargo.toml ] && cargo build
[ -f uv.lock ] && uv sync
[ -f pyproject.toml ] && [ ! -f uv.lock ] && pip install -e .
[ -f requirements.txt ] && pip install -r requirements.txt
[ -f go.mod ] && go mod download
```

## Step 3: Baseline check

Run the project’s usual test or lint command when known. If unknown, skip
rather than guessing a heavy suite.

- Failures → report and ask whether to proceed
- Pass / skipped → report ready

```
Worktree ready at <full-path>
Branch <branch>
Baseline: <passing | skipped | failing (awaiting decision)>
```

## Quick reference

| Situation | Action |
|-----------|--------|
| Under `.soothe/worktrees/` or linked WT | Reuse; do not nest |
| Submodule | Treat as primary checkout |
| Need isolation | `.soothe/worktrees/<slug>` |
| `.soothe/` not ignored | Add `.soothe/` to `.gitignore` |
| `git worktree add` fails | Work in place |

## Mistakes to avoid

- Defaulting to `.worktrees/` / `worktrees/` instead of `.soothe/worktrees/`
- Nesting worktrees
- Skipping the ignore check for `.soothe/`
- Creating a worktree when already isolated
