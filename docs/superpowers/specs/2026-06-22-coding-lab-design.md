# Coding lab — design

**Date:** 2026-06-22
**Status:** approved (design); to be modelled in archik, built in milestones.
**Goal:** a new leanlab *lab type* that lives inside a code project, takes coding tasks
("create an endpoint"), and runs the Worker/Director/Critic loop where the evaluator is
**tests + spec adherence + code quality**. Over time the lab gets better at *this* project.

## The shift from a metric lab to a coding lab

| | Metric lab (today) | Coding lab |
|--|--------------------|-----------|
| An experiment is | a throwaway file in `experiments/` | a **change to the real repo** (a diff on a branch) |
| Evaluation is | one frozen number | a **gate** (tests/lint/typecheck pass) + a **quality score** |
| Director / Critic | ML researcher personas | **tech-lead** + **code-reviewer** personas |
| The "learning" | best results in memory | a growing **PLAYBOOK** of project conventions/pitfalls |
| Shape | evolve a number forever | per-task: iterate to "done"; across tasks: accumulate skill |

## The team (coding personas)

- **Spec-writer** (new) — turns the task into a spec + **acceptance tests**, which the
  operator approves and which are then **locked**. A different role than the engineer.
- **Worker = Engineer** — implements the change in an isolated worktree to pass the gate,
  following the PLAYBOOK.
- **Critic = Code reviewer** — reviews the diff: correctness, security, style, conventions,
  and specifically whether the engineer gamed/weakened the tests.
- **Director = Tech lead** — decides accept/iterate, maintains the PLAYBOOK and picks next steps.

## Evaluation — gate + score (the honesty model)

The operator's worry was "the evaluator should be smart and evolve." It does, *safely*:

- **Frozen per task** — a task's acceptance tests are written and locked before the
  engineer codes; the engineer cannot touch them.
- **Ratchet, never loosen** — the test suite only grows across tasks; old tests are never
  weakened. The bar climbs; that is the safe kind of "evolving".
- **Separation of duties** — the spec-writer (not the engineer) authors acceptance tests;
  the Critic polices test-gaming.

Per task, evaluation =
- **Gate (objective, binary):** project test suite + this task's locked acceptance tests +
  lint + typecheck must all pass.
- **Score (for ranking/feedback):** the Critic's quality rating (0–100) of the diff,
  optionally plus a coverage delta.
- **Done** = gate green AND quality ≥ threshold.

## Isolation

Each engineer attempt runs in its **own git worktree/branch**. Tests run there. Only a
passing, approved change merges to the main branch; failed attempts are discarded. This
keeps the working tree clean and allows parallel attempts. Requires the project to be a git repo.

## Two loops

- **Inner (one task):** spec → engineer attempt(s) in worktrees → gate + review →
  revise → merge the winning attempt.
- **Outer (across tasks):** each merged task **adds tests** (ratchet) and **updates the
  PLAYBOOK** → the next task starts smarter. This is "getting better at the project."

## Memory becomes a PLAYBOOK

`PLAYBOOK.md` — conventions, architecture map, past pitfalls, "how to add an endpoint
here." The Director maintains it; it is injected into every engineer prompt (the same
learning-by-text the metric lab uses, aimed at the codebase).

## Reuse vs new

- **Reused:** the Worker/Director/Critic loop, the claude agent layer (ports & adapters),
  rich CLI/UX, the doctor (check/fix), the dashboard, memory-as-injected-text.
- **New:** `type: coding` labs; the spec-writer + lock-tests step; **git-worktree**
  isolation + merge; the composite gate+score evaluator; the PLAYBOOK; per-task framing.

## Milestones

- **M1 — Spec a task:** a coding lab points at a repo; the spec-writer turns a task into a
  spec + acceptance tests in an isolated worktree, the operator approves, and they are
  **locked**. (The honesty anchor; reuses the init-architect pattern.)
- **M2 — Gate runner:** run the gate (project tests + locked acceptance tests + lint) in
  the worktree and report pass/fail; the composite score.
- **M3 — Engineer loop:** the engineer implements to pass the gate, iterating on
  Critic/Director feedback; merge the winner.
- **M4 — PLAYBOOK + ratchet:** Director maintains the PLAYBOOK; merged tasks add tests.
- **M5 — Dashboard + polish:** coding-lab view (tasks, gate status, diffs, playbook).

This spec covers the whole vision; **M1 is the immediate scope.**

## Open decisions (don't block M1)
- Quality threshold value and whether it's per-lab.
- Whether engineer attempts run in parallel (worktrees allow it).
- How often / by whom the PLAYBOOK is updated.

## Out of scope (FUTURE.md)
- Adversarial stress-testing of changes (sequoia-style worst-case windows).
- Multi-repo / monorepo task routing.
