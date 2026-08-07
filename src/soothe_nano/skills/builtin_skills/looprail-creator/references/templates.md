# LoopRail starter templates

Copy, rename `id` / filename, and edit NL conditions. Always use `event:` (not `on:`).
Keep summary/applies_when self-contained (no cross-rail or host-internals prose).

Shipped builtins to mirror: `feature-dev`, `bugfix`, `maker-checker`,
`hotfix`, `spike`, `pr-review`, `migration`, `greenfield-system`.

## Scout → implement → review → QA

Same shape as builtin `feature-dev`.

```yaml
id: feature-dev-custom
version: "1.0"
summary: |
  Parallel exploration, then plan/implement, independent review, and QA.
applies_when: |
  Build or change functionality in an existing codebase.
conditions:
  ready_to_plan: |
    All exploration scouts finished with enough findings to plan.
  needs_review: |
    Implementation finished; changes should be reviewed.
  needs_qa: |
    Review passed; automated verification should run.
  branch_is_stuck: |
    A maker or implementation goal failed, or approach conflicts with architecture.
  job_complete: |
    Review and QA passed; no pending children.
flow:
  - event: job_start
    then: decompose_parallel
  - event: goal_completed
    when: ready_to_plan
    then: plan_and_implement
  - event: goal_completed
    when: needs_review
    then: review
  - event: goal_completed
    when: needs_qa
    then: qa_verify
  - event: goal_failed
    when: branch_is_stuck
    then: retry_branch
  - event: dag_idle
    when: job_complete
    then: complete_job
```

## Maker-checker (evaluator-optimizer)

```yaml
id: maker-checker-custom
version: "1.0"
summary: |
  Implement then independently review; replant on recoverable checker failure.
applies_when: |
  High-stakes change where the maker must not grade their own work.
conditions:
  needs_check: |
    Implementation completed; an independent review goal must run.
  checker_failed_recoverable: |
    Checker rejected the work but a new branch can fix it with salvaged context.
  needs_qa: |
    Checker passed; automated verification should run.
  job_complete: |
    Checker and QA passed; no pending children.
flow:
  - event: job_start
    then: plan_and_implement
  - event: goal_completed
    when: needs_check
    then: review
  - event: goal_send_back
    when: checker_failed_recoverable
    then: retry_branch
  - event: goal_completed
    when: needs_qa
    then: qa_verify
  - event: dag_idle
    when: job_complete
    then: complete_job
```

## Spike → human (no auto-implement)

```yaml
id: spike-custom
version: "1.0"
summary: |
  Parallel exploration then pause for a human decision; does not auto-implement.
applies_when: |
  Spike, PoC, or architecture choice needing an explicit human decision.
conditions:
  scouts_done: |
    Exploration goals finished with enough evidence to choose or ask for more.
  job_complete: |
    Human acknowledged the spike outcome; no pending goals.
flow:
  - event: job_start
    then: decompose_parallel
  - event: goal_completed
    when: scouts_done
    then: pause_for_user
  - event: user_intervention
    then: complete_job
  - event: dag_idle
    when: job_complete
    then: complete_job
```

## Review + QA

```yaml
id: pr-review-custom
version: "1.0"
summary: |
  Review an existing diff, then run QA; no implementation branch.
applies_when: |
  Review a PR, patch, or diff the user already produced.
conditions:
  needs_qa: |
    Review completed; automated verification should run after review.
  needs_human: |
    Blocking design or security concern needs an owner decision.
  job_complete: |
    Review, QA, and any human ack finished; no pending children.
flow:
  - event: job_start
    then: review
  - event: goal_completed
    when: needs_qa
    then: qa_verify
  - event: goal_completed
    when: needs_human
    then: pause_for_user
  - event: dag_idle
    when: job_complete
    then: complete_job
```

## Greenfield + feedback (find → optimize → verify)

Same shape as builtin `greenfield-system`. Commit gate before review; feedback
cycle until acceptance before next wave / complete.

```yaml
id: greenfield-custom
version: "1.0"
summary: |
  Architecture milestones, parallel makers, integrate, commit, review, QA,
  then find→optimize→verify until system acceptance.
applies_when: |
  Building a multi-slice system or large scaffold from scratch.
fanout:
  artifact: "{job_id}/wave-plan.json"
  require_plan: true
  max_waves: 3
verbs:
  plan_milestones:
    do:
      - spawn_goal:
          id: planner
          role: planner
          tags: [architecture, planning, milestones]
          priority: 80
          brief: |
            Architecture and milestone map for job {job_id}. Define Slice
            boundaries, wave-1 slices, acceptance criteria, and commit
            milestones. REQUIRED: one findings entry that is exactly a WavePlan
            JSON object. Do not write the plan into the project workspace tree.
          wire:
            root_waits_on: self
conditions:
  architecture_ready: |
    Architecture / milestone map finished; first maker wave not spawned yet.
  wave_makers_done: |
    All makers for the current wave completed.
  needs_commit: |
    Integrate finished (or makers finished when integrate skipped); commit gate
    should run before review.
  needs_review: |
    Commit milestone completed; independent diff-scoped review should run.
  needs_qa: |
    Review passed; wave acceptance tests should run.
  needs_feedback: |
    QA or prior feedback verify finished; acceptance not met; another
    find→optimize→verify round should close remaining gaps.
  ready_for_next_wave: |
    Feedback verify (or exhausted feedback) shows the wave is ready; more
    milestones remain.
  branch_is_stuck: |
    A maker or implementation goal failed.
  architecture_failed: |
    Architecture / WavePlan planner failed; replant.
  job_complete: |
    System acceptance holds; DAG idle with no pending children.
flow:
  - event: job_start
    then: plan_milestones
  - event: goal_completed
    when: architecture_ready
    then: spawn_wave_makers
  - event: dag_idle
    when: architecture_ready
    then: spawn_wave_makers
  - event: goal_completed
    when: wave_makers_done
    then: spawn_integrate
  - event: goal_completed
    when: needs_commit
    then: commit_milestone
  - event: dag_idle
    when: needs_commit
    then: commit_milestone
  - event: goal_completed
    when: needs_review
    then: review
  - event: dag_idle
    when: needs_review
    then: review
  - event: goal_completed
    when: needs_qa
    then: qa_verify
  - event: dag_idle
    when: needs_qa
    then: qa_verify
  - event: goal_completed
    when: needs_feedback
    then: spawn_feedback_cycle
  - event: goal_failed
    when: needs_feedback
    then: spawn_feedback_cycle
  - event: goal_completed
    when: ready_for_next_wave
    then: spawn_wave_makers
  - event: dag_idle
    when: ready_for_next_wave
    then: spawn_wave_makers
  - event: goal_failed
    when: branch_is_stuck
    then: retry_maker
  - event: goal_failed
    when: architecture_failed
    then: retry_architecture
  - event: dag_idle
    when: wave_makers_done
    then: spawn_integrate
  - event: dag_idle
    when: needs_feedback
    then: spawn_feedback_cycle
  - event: dag_idle
    when: job_complete
    then: complete_job
```

## Migration + cutover pause

Same fan-out shape as greenfield, plus human pause on irreversible cutover.

```yaml
id: migration-custom
version: "1.0"
summary: |
  Migration milestones with WavePlan slices, makers, integrate, commit,
  review, QA, feedback, and pause on irreversible cutover.
applies_when: |
  Framework upgrade, schema migration, or multi-file mechanical migration
  with a clear done condition.
fanout:
  artifact: "{job_id}/wave-plan.json"
  require_plan: true
  max_waves: 3
verbs:
  plan_milestones:
    do:
      - spawn_goal:
          id: planner
          role: planner
          tags: [architecture, planning, milestones]
          priority: 80
          brief: |
            Migration architecture for job {job_id}. Partition into independent
            WavePlan slices. REQUIRED: one WavePlan JSON findings entry.
          wire:
            root_waits_on: self
conditions:
  architecture_ready: |
    Migration milestone map finished; first maker wave not spawned yet.
  wave_makers_done: |
    All makers for the current wave completed.
  needs_commit: |
    Integrate finished; commit gate before review.
  needs_review: |
    Commit completed; independent review should run.
  needs_qa: |
    Review passed; migration invariant checks should run.
  needs_feedback: |
    QA finished; acceptance not met; another feedback round.
  ready_for_next_wave: |
    Wave ready; more migration slices remain.
  needs_human: |
    Next step is irreversible cutover (tag goals with needs_human or cutover).
  branch_is_stuck: |
    A maker or implementation goal failed.
  architecture_failed: |
    Migration planner failed; replant.
  job_complete: |
    Migration success condition holds; DAG idle.
flow:
  - event: job_start
    then: plan_milestones
  - event: goal_completed
    when: architecture_ready
    then: spawn_wave_makers
  - event: goal_completed
    when: wave_makers_done
    then: spawn_integrate
  - event: goal_completed
    when: needs_commit
    then: commit_milestone
  - event: goal_completed
    when: needs_review
    then: review
  - event: goal_completed
    when: needs_qa
    then: qa_verify
  - event: goal_completed
    when: needs_feedback
    then: spawn_feedback_cycle
  - event: goal_completed
    when: ready_for_next_wave
    then: spawn_wave_makers
  - event: goal_completed
    when: needs_human
    then: pause_for_user
  - event: dag_idle
    when: needs_human
    then: pause_for_user
  - event: goal_failed
    when: branch_is_stuck
    then: retry_maker
  - event: goal_failed
    when: architecture_failed
    then: retry_architecture
  - event: dag_idle
    when: job_complete
    then: complete_job
```
