# How leanlab works

This is the deeper tour — the idea, the two lab types, the coding-lab flow, and
the project structure. For installation and day-to-day commands, see the
[README](../README.md) and [USAGE.md](USAGE.md).

## The idea

leanlab runs a **self-improving loop**: make an attempt → judge it against a
frozen criterion → keep the best → learn for next time. A team of Claude agents
drives the loop; you only describe the *lab*.

It generalizes the trading "selflearn" idea: **strategy → Experiment**,
**Manager → Director**, `results.csv → results.jsonl`, and the objective (what to
maximize or minimize) is configuration, not code.

leanlab is used **inside your own project** (like archik): each lab lives in a
`.leanlab/<name>/` folder; the engine stays in the installed tool and is never
copied into your project.

## Two lab types

The same loop runs two ways. A **metric lab** (ML / optimization — evolve a
number) and a **coding lab** (do coding tasks on a repo — pass tests). Same
engine, different words:

**The team (agents)**

| Metric lab | Coding lab | Job |
|------------|-----------|-----|
| Worker (experimenter) | Engineer | makes the attempt |
| Director (chief scientist) | Tech-lead | steers + maintains the notes |
| Critic (red-team) | Reviewer | finds what's wrong |
| *(init drafts the lab)* | Spec-writer | turns a task into locked acceptance tests |

**Core concepts**

| Metric lab | Coding lab |
|------------|-----------|
| Experiment (one file in `experiments/`) | Change / diff (in a git worktree) |
| Frozen evaluator (`evaluation.py` → JSON metric) | Gate (locked acceptance tests + project tests) |
| Objective metric (min rmse / max acc) | pass/fail gate + quality score (0–100) |
| Memory (top-N best experiments, injected) | PLAYBOOK (project conventions, injected) |
| `Director_Notes.md` | `PLAYBOOK.md` |
| `Critic_Feedback.md` | reviewer feedback (inline, per build) |
| `results.jsonl` (one row per experiment) | `coding-results.jsonl` + git history |
| best-so-far (kept by ranking) | merged (kept by passing gate + review) |
| "lock the evaluator" | "lock the acceptance tests" (+ hash) |

**Commands**

| Metric lab | Coding lab |
|------------|-----------|
| `init` (scaffold a lab) | `spec` (define a task) |
| `run` (evolve experiments) | `build` (engineer a task) |
| `serve` (dashboard) | `board` (dashboard) |
| `lock` / `unlock` | (lock is automatic in `spec`) |

Same idea both ways: **make an attempt → judge it → keep the best → learn for
next time** — just "experiment + metric + memory" swapped for "code change +
tests + playbook."

## The coding lab flow

A coding lab is an **assembly line with quality gates**. Each step hands off to
the next, and any failed gate sends the work back to the engineer — up to
`--max-attempts`. Nothing reaches `main` until the tests pass, the work is proven
honest, and every reviewer approves.

```
        Developer
           │  leanlab spec "task"
           ▼
   ┌──────────────┐
   │ Spec-writer  │  drafts the spec + LOCKS the acceptance tests
   └──────────────┘  (sha256, stored outside the worktree)
           │  leanlab build <slug>
           ▼
   ┌──────────────┐ ◀──────────────────┐
   │   Engineer   │  implements in an   │
   └──────────────┘  isolated worktree  │
           │                            │
           ▼                            │
      [  Gate  ]   locked tests pass    │  fail →
           │                            │  fix & retry
           ▼                            │  (≤ max-attempts)
   [ Honesty checks ]  no tampering,    │
                       no gamed tests   │
           │                            │
           ▼                            │
   [ Reviewer panel ]  N lenses,        │
                       ALL must approve ┘
           │  all approve
           ▼
   ┌──────────────┐
   │    Merge     │  the change ships to main
   └──────────────┘
           │
           ▼
   ┌──────────────┐
   │  Tech-lead   │  rewrites PLAYBOOK.md → next task starts smarter
   └──────────────┘
```

| Step | Who | What happens |
|------|-----|--------------|
| `leanlab spec "task"` | **Spec-writer** | Reads the repo, writes a spec + acceptance tests, then **locks** the tests (sha256 stored outside the worktree, so they can't be quietly edited). |
| `leanlab build <slug>` | **Engineer** | Implements the change in its own git worktree. |
| Gate | *automated* | Restores the pristine tests and runs them. Fail → back to the engineer with the failure. |
| Honesty checks | *automated* | (a) Were the locked tests touched? (b) Do they still pass **without** the engineer's own fixtures/conftest? Either trick → rejected. |
| Reviewer panel | **Reviewer(s)** | 1–N adversarial reviewers, each with a different lens (correctness / spec-conformance / security / robustness). **All must approve**; any blocker returns a concrete counterexample. Size it with `--reviewers N`. |
| Merge | *automated* | The branch merges into `main` — the change ships. |
| Playbook | **Tech-lead** | Rewrites `PLAYBOOK.md` so the next task starts with the project's conventions and pitfalls. |

Watch it live with `leanlab board`: the four roles, a per-task round-by-round
timeline, the agent chat (every session, with token cost), and the playbook.

**Why it compounds:** every merged task adds its locked tests to `main` (a
ratchet that never loosens), and the playbook accumulates — so the lab keeps
getting better at *your* project.

## Structure

```
leanlab/                     # the installable tool (engine — never copied into your project)
├── cli.py                   # commands: init · check · fix · run · serve · spec · build · board · list · lock · unlock
├── core/
│   ├── loop.py              # run N experiments, score, log, wake Director/Critic
│   ├── monitor.py           # metric-lab live dashboard
│   ├── init.py              # interactive `init` — Claude drafts task + evaluator
│   ├── doctor.py            # preflight checks + Claude-powered `fix`
│   ├── coding/              # the coding lab: spec · engineer · gate · reviewer · tech-lead · board
│   └── agents/              # ports & adapters — the backend-agnostic agent layer
├── templates/agents/        # the agent personas (injected into prompts, not copied)
└── core/coding/board_dist/  # the React board UI, compiled (built from frontend/)

<your project>/.leanlab/<name>/   # a metric lab — only YOUR files
├── task.md          goal + experiment contract
├── lab.json         objective {metric, direction}, commands, cadences
├── evaluation.py    the FROZEN evaluator → prints ONE line of JSON metrics
├── validate.py      structural check the Worker runs (no score)
├── experiments/     where the Worker writes one file per loop
└── results.jsonl    the book: one JSON record per experiment
```

**How a lab plugs in:** the engine never imports a lab. It runs the lab's
`validate_cmd` / `eval_cmd` (from `lab.json`) as subprocesses, reads the **JSON
metrics** the evaluator prints, and ranks by the configured **objective**. So a
lab can be ML, trading, graphics, optimization — anything that can print a
metric.

## Making a metric lab

`leanlab init <name>` is interactive: you describe the task in plain words, Claude
drafts `task.md` and picks the objective, then proposes an `evaluation.py` you
approve (or give feedback to revise). It installs the scorer's libraries and
self-checks the wiring before finishing. Then `leanlab lock <name>` and
`leanlab run <name>`. If a lab is mis-wired, `leanlab check` says what's wrong and
`leanlab fix` has Claude repair it.

**Example — house-prices:** this repo dogfoods itself. `.leanlab/house-prices`
predicts California median house value (**minimize RMSE**). Each experiment
defines `build_estimator()` (any scikit-learn-style model); the evaluator fits it
on a fixed split and reports `rmse / mae / r2 / overfit_gap / train_secs` on
held-out data.

## Honesty model

- Agents get full tools and are told to be proactive researchers (web, ML, `uv add`).
- The Worker never runs the evaluator, so metric scores stay honest; `lock` freezes it.
- In coding labs, acceptance tests are locked (sha256, out of the worktree),
  restored before every gate, and re-run in isolation to catch fixture-gaming.
- The evaluator and agent personas live in the package and are injected into
  prompts — nothing framework-level is copied into your project.
