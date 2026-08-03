---
name: looprail-creator
description: >
  Author and validate Soothe LoopRail YAML workflow patterns for Autopilot.
  Use whenever the user wants to create, draft, distill, edit, review, or
  promote a LoopRail (rail), autopilot workflow pattern, job-scoped orchestration
  policy, feature-dev/bugfix/maker-checker style rail, or files under
  .soothe/rails/, ~/.soothe/rails/, or soothe/rails/builtin_rails/. Also use when
  converting a skill or multi-step SOP into a rail, or when checking that a rail
  matches the Soothe LoopRail protocol (event/when/then, CE builtins only).
tags: looprail, loop rail, rail, autopilot workflow, rail creator, looprail-creator, soothe rails, distill rail
---

# LoopRail Creator

Create **LoopRail** documents that match the Soothe protocol: users author
**when** orchestration should act; ContextEngine owns **what** via fixed CE
builtins.

## When to use

- New rail for a team workflow (feature, bugfix, hotfix, spike, review, …)
- Distill a skill / SOP into a rail draft
- Fix or review an existing `.yml` rail for protocol compliance
- Promote a draft from `rails/drafts/` into the active catalog

## Protocol invariants (do not violate)

1. **User defines *when*; framework defines *what*** — never invent custom
   `then:` verbs; only CE builtins listed below.
2. **Event-driven, no named phases** — no `intake → implement → review` enums.
3. **Soft state** — policy lives in `flow` / `rules` + live goal DAG + rail
   trace; do not store a phase counter in the YAML.
4. **A rail must differ from no-rail Monitor/CE behavior** — if the policy is
   only “maybe decompose, maybe retry, stop when idle”, tell the user to use
   **no `rail_id`** instead of shipping a `default` rail.
5. **StrangeLoop executes one goal; LoopRail shapes the DAG; AutopilotService
   schedules** — rails must not dispatch workers or drive StrangeLoop prompts.

Load details as needed: [references/looprail-protocol.md](references/looprail-protocol.md).

## Allowed `then:` builtins (only)

| Builtin | Purpose |
|---------|---------|
| `decompose_parallel` | Parallel exploration / scout goals |
| `plan_and_implement` | Plan then implement (often after scouts) |
| `review` | Independent review goal |
| `qa_verify` | Tests / verification goal |
| `retry_branch` | Prune stuck branch; salvage completed via `informs`; replant |
| `merge_branches` | Merge compatible parallel branches |
| `pause_for_user` | Human gate |
| `complete_job` | Mark job done; stop scheduling |

## Trigger field: `event` (not `on`)

Use **`event:`** for triggers. Do **not** use bare `on:` — YAML 1.1 treats
`on` as a boolean. Legacy `on` is accepted by the loader and rewritten to
`event`, but new rails must use `event`.

Allowed event names:

`job_start` · `goal_completed` · `goal_failed` · `goal_blocked` ·
`goal_send_back` · `dag_idle` · `worker_timeout` · `user_intervention`

## Output locations

| Intent | Path |
|--------|------|
| Project draft (preferred first) | `<workspace>/.soothe/rails/drafts/YYYY-MM-DD-<id>.yml` |
| Project active | `<workspace>/.soothe/rails/<id>.yml` |
| User / daemon-wide | `~/.soothe/rails/<id>.yml` |
| Built-in (host package only) | `packages/soothe/src/soothe/rails/builtin_rails/<id>.yml` |

- Filename stem **must** equal `id`.
- Do not load from `drafts/` until promoted.
- Precedence: built-in → `~/.soothe/rails/` → project (last wins).

## Authoring workflow

### 1. Clarify the *difference* from no-rail

Ask (or infer): what hard gate or topology does no-rail lack?

Examples that qualify: scout barrier before implement; repro gate before fix;
maker ≠ checker; explore-then-human-stop; review-only; wave migration until a
checkable condition; mandatory security review; human pause on irreversible ops.

If none — **do not create a rail**.

### 2. Draft NL-first YAML (Style A)

```yaml
id: my-workflow
version: "1.0"

summary: |
  One paragraph: what the rail does and how it differs from no-rail.

applies_when: |
  When auto-pick / humans should choose this rail.

conditions:
  ready_for_next: |
    Natural-language guard — structured yes/no at runtime (not keyword lists).
  job_complete: |
    Checkable done condition when possible (tests green, no pending children).

flow:
  - event: job_start
    then: decompose_parallel

  - event: goal_completed
    when: ready_for_next
    then: plan_and_implement

  - event: dag_idle
    when: job_complete
    then: complete_job
```

Optional Style B `rules:` for precise `priority`, `check:`, or `all:` — see
protocol reference.

### 3. Validate before handoff

Checklist:

- [ ] `id` matches filename stem
- [ ] `version`, `summary`, `applies_when` present and non-empty
- [ ] `flow` and/or `rules` present
- [ ] Every trigger uses `event:` (not bare `on:`)
- [ ] Every `then:` is in the allowed builtin set
- [ ] `when:` values are NL conditions or named `conditions.*` (no keyword
      heuristics in the rail body)
- [ ] Stop condition (`job_complete` / human pause) is explicit
- [ ] Rail is not a re-statement of default Monitor/CE opportunistic behavior

If the host package is available, prefer validating via:

```python
from soothe.rails import LoopRailCatalog, load_rail_file
load_rail_file(path)  # or LoopRailCatalog(workspace=...).resolve("<id>")
```

### 4. Promote

1. Write under `rails/drafts/` first when unsure.
2. After human review, copy/rename to `rails/<id>.yml` (or builtin path).
3. Tell the user how to run: `soothe autopilot run "…" --rail <id>` (or project
   `.rail-default`).

## Distill from a skill

When converting a skill / SOP:

1. Read `SKILL.md` + `references/` — extract triggers, gates, parallelism,
   failure recovery, human stops.
2. Map steps → `event` + `when` + `then` (builtins only).
3. Drop anything that would require custom CE verbs; note gaps for the user.
4. Emit draft YAML under `rails/drafts/`.

## Anti-patterns

- Shipping `default.yml` that mirrors no-rail
- Using `on:` instead of `event:`
- Custom `then:` verbs or StrangeLoop prompt injection from the rail
- Phase enums (`phase: implement`)
- Keyword/regex content judgment inside the rail (put judgment in NL
  `conditions` for structured guard evaluation)
- Operator knobs (`max_parallel_goals`, worktrees) inside rail YAML — those stay
  in config

## Quick templates

See [references/templates.md](references/templates.md) for starter rails
aligned with shipped builtins (`feature-dev`, `bugfix`, `maker-checker`,
`hotfix`, `spike`, `pr-review`, `migration`).
