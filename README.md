# leanlab

[![PyPI](https://img.shields.io/pypi/v/leanlab.svg)](https://pypi.org/project/leanlab/)
[![CI](https://github.com/bacharSalleh/leanlab/actions/workflows/ci.yml/badge.svg)](https://github.com/bacharSalleh/leanlab/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/leanlab.svg)](https://pypi.org/project/leanlab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

```bash
pipx install leanlab     # or: pip install leanlab  ·  uvx leanlab
```

A small **tool for self-improving experiment labs**. A team of agents —
**Workers** (experimenters), a **Director**, and **HyperCritics** — evolve
solutions against a **frozen evaluator**, one experiment at a time. The same loop
drives any task: you just describe the *lab* and Claude builds the scorer.

It is the trading "selflearn" idea, generalized: **strategy → Experiment**,
**Manager → Director**, `results.csv → results.jsonl`, and the objective (what to
maximize or minimize) is configuration, not code.

leanlab is used **inside your own project** (like archik): each lab lives in a
`.leanlab/<name>/` folder; the engine stays in the installed tool.

## Quick start

```bash
uv tool install --force --editable /path/to/leanlab   # install the `leanlab` tool
cd ~/my-project && uv init                            # your project (a uv project)

leanlab init iris        # describe the task; Claude drafts the lab
leanlab check iris       # verify it's wired correctly (free)
leanlab lock iris        # freeze the scorer
leanlab run iris --n 5   # the agents evolve experiments (costs Claude)
leanlab serve iris       # watch the live dashboard
```

**Full command guide:** [docs/USAGE.md](docs/USAGE.md) — the flow and what each
command does exactly.

## Anatomy

```
leanlab/                     # the installable tool (engine — never copied into your project)
├── cli.py                   # commands: init · check · fix · run · serve · list · lock · unlock
├── core/
│   ├── loop.py              # run N experiments, score, log, wake Director/Critic
│   ├── monitor.py           # live dashboard: stat chips + progress chart + table + stream
│   ├── init.py              # interactive `init` — Claude drafts task + evaluator
│   ├── doctor.py            # preflight checks + Claude-powered `fix`
│   └── agents/              # ports & adapters — the backend-agnostic agent layer
└── templates/agents/        # CLAUDE.md (Worker) · director.md · critic.md  (injected, not copied)

<your project>/.leanlab/<name>/   # a lab — only YOUR files
├── task.md          goal + experiment contract
├── lab.json         objective {metric, direction}, commands, cadences
├── evaluation.py    the FROZEN evaluator → prints ONE line of JSON metrics
├── validate.py      structural check the Worker runs (no score)
├── experiments/     where the Worker writes one file per loop
└── results.jsonl    the book: one JSON record per experiment
```

**How a lab plugs in:** the engine never imports a lab. It runs the lab's
`validate_cmd` / `eval_cmd` (from `lab.json`) as subprocesses, reads the **JSON
metrics** the evaluator prints, and ranks by the configured **objective**. So a lab
can be ML, trading, graphics, optimization — anything that can print a metric.

## Make your own lab

`leanlab init <name>` is interactive: you describe the task in plain words, Claude
drafts `task.md` and picks the objective, then proposes an `evaluation.py` you
approve (or give feedback to revise). It installs the scorer's libraries and
self-checks the wiring before finishing. Then `leanlab lock <name>` and
`leanlab run <name>`.

If a lab is mis-wired, `leanlab check` tells you what's wrong and `leanlab fix`
has Claude repair it.

## The example lab: house-prices

This repo dogfoods itself — `.leanlab/house-prices` predicts California median
house value (**minimize RMSE**). Each experiment defines `build_estimator()` (any
scikit-learn-style model); the evaluator fits it on a fixed split and reports
`rmse / mae / r2 / overfit_gap / train_secs` on held-out data.

## Two lab types — naming map

leanlab runs the same loop two ways. A **metric lab** (ML/optimization — evolve a number)
and a **coding lab** (do coding tasks on a repo — pass tests). Same engine, different words:

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

**archik nodes**

| Metric lab | Coding lab |
|------------|-----------|
| `loop` | `engineer` |
| `evaluator` | `gate-runner` |
| `results-store` | `playbook` + `coding-results` |
| `dashboard` | `coding-board` |

Same idea both ways: **make an attempt → judge it → keep the best → learn for next time** —
just "experiment + metric + memory" swapped for "code change + tests + playbook."

## The coding lab flow

A coding lab is an **assembly line with quality gates**. Each step hands off to the next, and
any failed gate sends the work back to the engineer — up to `--max-attempts`. Nothing reaches
`main` until the tests pass, the work is proven honest, and every reviewer approves.

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

Watch all of it live with `leanlab board`: the four roles, a per-task timeline, the agent chat
(every session, with token cost), and the growing playbook.

**Why it compounds:** every merged task adds its locked tests to `main` (a ratchet that never
loosens), and the playbook accumulates — so the lab keeps getting better at *your* project.

## Develop / test

```bash
uv sync
uv run pytest                         # the test suite
uv run leanlab list                   # run the tool from the checkout, no install
```

### Board UI (React + Tailwind)

The `leanlab board` dashboard is a React + Tailwind app in [`frontend/`](frontend/), built
into `leanlab/core/coding/board_dist/` and served by the Python board server. The Python side
exposes the data as `/api/state`, `/api/task`, and `/api/stream` (SSE); React renders it.

```bash
cd frontend && npm install && npm run build   # compile the UI (re-run after editing src/)
```

For live UI work, run `leanlab board --no-open` (API on `:8766`) and `npm run dev` in `frontend/`
(Vite on `:5173`, proxying `/api`). The compiled `board_dist/` ships inside the wheel.

## Let Claude Code drive it

```bash
cd ~/my-project && leanlab init --for-agent   # installs .claude/skills/leanlab/SKILL.md
```
Then talk to Claude Code — *"use leanlab to add a /health endpoint"* — and it specs, builds, and
merges through the honest test gate (`spec --yes` / `build` run headless). See `docs/USAGE.md`.

## Notes

- Agents get full tools and are told to be proactive researchers (web, ML, `uv add`).
- The Worker never runs the evaluator, so scores stay honest; `lock` freezes it.
- The evaluator (and agent specs) live in the package and are injected into prompts —
  nothing framework-level is copied into your project.
