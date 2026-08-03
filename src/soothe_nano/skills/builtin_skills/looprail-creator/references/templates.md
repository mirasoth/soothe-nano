# LoopRail starter templates

Copy, rename `id` / filename, and edit NL conditions. Always use `event:` (not `on:`).

## Scout → implement → review → QA

Same shape as builtin `feature-dev`.

```yaml
id: feature-dev-custom
version: "1.0"
summary: |
  Parallel exploration, then plan/implement, independent review, and QA.
applies_when: |
  Build or change application functionality (not a one-line fix or spike).
conditions:
  ready_to_plan: |
    All exploration scouts finished with enough findings to plan.
  needs_review: |
    Implementation finished; changes should be reviewed.
  needs_qa: |
    Review passed; automated verification should run.
  branch_is_stuck: |
    Review or execution failed twice, or approach conflicts with architecture.
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

## Review-only

```yaml
id: pr-review-custom
version: "1.0"
summary: |
  Review an existing diff; optional QA; no implementation branch.
applies_when: |
  Review a PR, patch, or diff the user already produced.
conditions:
  needs_qa: |
    Review found issues tests can catch, or user asked for verification.
  needs_human: |
    Blocking design or security concern needs an owner decision.
  job_complete: |
    Review (and optional QA / human ack) finished; no pending children.
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
