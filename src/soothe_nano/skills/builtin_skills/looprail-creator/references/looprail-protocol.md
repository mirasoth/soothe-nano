# LoopRail protocol reference

Canonical design: `docs/drafts/2026-07-11-loop-rail-design.md` (host monorepo).
Runtime loader: `soothe.rails.catalog` / `soothe.rails.LoopRailCatalog`.

## Document schema

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | Must match filename stem `<id>.yml` |
| `version` | yes | Semver string |
| `summary` | yes | NL overview; auto-pick + docs |
| `applies_when` | yes | NL rail-selection condition |
| `conditions` | no | Named NL guards (`str → str`) |
| `flow` | no* | NL-first hooks |
| `rules` | no* | Explicit rules (*need `flow` and/or `rules`) |
| `flow[].event` | yes | Trigger name (canonical; not `on`) |
| `flow[].when` | no | Condition name, NL string, or structured when |
| `flow[].then` | yes | CE builtin name |
| `rules[].id` | no | Stable rule id for traces |
| `rules[].priority` | no | Lower first; default 100 (explicit rules prefer ~99) |
| `rules[].allow_multiple` | no | If true, do not stop after first match |

### Legacy `on`

YAML 1.1 parses bare `on:` as boolean `True`. New rails **must** use `event:`.
Loaders rewrite legacy `on` / boolean `True` keys to `event`.

## Evaluation order

1. Normalize `flow` → synthetic rules (`flow[i]`).
2. Merge with explicit `rules`; sort by `priority` ascending.
3. On each event, walk sorted list; evaluate `when`.
4. First matching rule invokes `then` and **stops** unless `allow_multiple: true`.

## Structured `when` (optional)

```yaml
when:
  nl: $conditions.branch_is_stuck
# or
when:
  all:
    - nl: $conditions.branch_is_stuck
    - check: goal.retry_count >= 2
```

Guards default to structured LLM output `{ matched, confidence, reasoning }`.
Prefer checkable stop conditions for `job_complete` (suite green, path removed).

## Events

| Event | Typical source |
|-------|----------------|
| `job_start` | Job submit / rail bind |
| `goal_completed` | ContextEngine |
| `goal_failed` | ContextEngine |
| `goal_blocked` | ContextEngine |
| `goal_send_back` | Consensus / checker |
| `dag_idle` | No runnable goals; job incomplete |
| `worker_timeout` | AutopilotService |
| `user_intervention` | CLI / TUI / human ack |

## CE builtins

`decompose_parallel` · `plan_and_implement` · `review` · `qa_verify` ·
`retry_branch` · `merge_branches` · `pause_for_user` · `complete_job`

Unknown `then:` → load-time validation error.

## Catalog tiers

1. `soothe/rails/builtin_rails/` (lowest)
2. `$SOOTHE_HOME/rails/` (usually `~/.soothe/rails/`)
3. `<workspace>/.soothe/rails/` (highest)

`drafts/` under a rails root is not loaded until promoted.

## Validity rule

A rail is valid **iff removing it changes job outcomes** for the same submit
text versus AutopilotMonitor / ContextEngine opportunistic behavior (no rail).
