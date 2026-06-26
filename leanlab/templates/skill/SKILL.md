---
name: leanlab
description: >-
  Use when the developer wants a coding task (a feature, endpoint, fix, refactor) done on THIS
  repo through leanlab's honest, test-gated loop instead of editing files directly. Triggers on
  requests like "use leanlab to add X", "spec/build this with leanlab", or "have the lab implement
  X". leanlab writes locked acceptance tests first, then an engineer implements until the gate is
  green and a reviewer approves, then merges.
---

# Driving leanlab

leanlab is a CLI already installed in this project. You (Claude Code) orchestrate it: you turn the
developer's request into a leanlab task, run it, and report the outcome. leanlab enforces honesty —
it writes acceptance tests, **locks** them, and only merges a change that truly passes them.

## When to use it

- The developer asks to add/implement/fix something **and** wants it test-gated / done "properly".
- The developer explicitly says "use leanlab" / "spec this" / "build this".

Do NOT use it for: quick edits, questions, or when the developer wants to write the code themselves.

## Preconditions (check first)

- The repo is a **git** repo and a **uv** project (has `pyproject.toml`). If not, tell the developer.
- `leanlab` is on PATH (`leanlab --help`). `spec` and `build` **spend Claude usage** — for a large
  task, confirm with the developer before running `build`.

## The flow

1. **Spec the task** (headless — `--yes` auto-approves the drafted tests):
   ```bash
   leanlab spec "<clear one-line task>" --yes
   ```
   It prints a plain `slug: <slug>` line — capture `<slug>` from it (or `ls .leanlab/worktrees/`).
   This created **locked** acceptance tests in an isolated worktree.

   **You are the only reviewer of those tests** (`--yes` skipped the human approval). Read the
   spec + the test files in `.leanlab/worktrees/<slug>/` and sanity-check they actually capture
   the task. For anything non-trivial or risky, show them to the developer and get a thumbs-up
   before building. If they're wrong, refine the task wording and re-run `spec` (it overwrites).

2. **Build it** (the engineer implements → gate → reviewer → merge; non-interactive):
   ```bash
   leanlab build <slug>
   ```
   Exit 0 = merged. The change is now on the main branch.

3. **Report** to the developer: show `git log --oneline -1` (the merge), the new/changed files,
   and whether it merged. If it did NOT merge, read the build output for why (gate failures or
   review feedback) and tell the developer; offer to refine the task and re-run.

4. **Clean up** when done: `leanlab clean` (removes merged task worktrees).

## Flags — IMPORTANT (you run without a terminal)

You call leanlab through Bash, which is **not an interactive terminal**. Commands that would
otherwise stop and ask a human will **hang** unless you pass `--yes`:

- `leanlab spec "<task>" --yes` — **always pass `--yes`.** It auto-approves the drafted acceptance
  tests. Without it, the command hangs forever waiting for a person.
- `leanlab init <name> --yes` — (metric labs only) auto-approves the drafted evaluator.

`build`, `gate`, `board`, `check`, `fix`, `clean` need no `--yes` (they don't prompt).

Other flags worth knowing:

| Flag (on `build`) | Effect |
|-------------------|--------|
| `--max-attempts N` | cap engineer retries (default 5) |
| `--min-quality 80` | also require reviewer quality ≥ 80 to merge |
| `--reviewers 3` | adversarial review panel: 3 reviewers with different lenses (correctness/spec/security/robustness); merges only if all approve. Stricter, costs ~N× review tokens |
| `--no-playbook` | skip the tech-lead PLAYBOOK update (faster / cheaper) |
| `--persona-set coding\|metric` | which agent personas (default `coding`) |
| `--no-isolate` | skip the isolated acceptance re-run (rarely needed) |

`leanlab clean --all` removes ALL task worktrees (default removes only merged ones).
`leanlab init --for-agent` is the one-time setup that installed THIS skill — **don't** run it during a task.

## Useful commands

| Command | Use |
|---------|-----|
| `leanlab spec "<task>" --yes` | create locked acceptance tests for a task |
| `leanlab build <slug>` | implement to a green gate + review, then merge |
| `leanlab build <slug> --min-quality 80` | also require a reviewer quality ≥ 80 |
| `leanlab gate <slug>` | just run the pass/fail gate (free, no agents) |
| `leanlab check <lab>` / `leanlab fix <lab>` | (metric labs) verify / repair wiring |
| `leanlab board` | live dashboard of tasks + the PLAYBOOK |
| `leanlab clean [slug]` | remove task worktrees |

## Rules

- Keep each task **small and concrete** (one endpoint / one fix). Split big asks into several specs.
- Never hand-edit files inside `.leanlab/worktrees/` — let `build` drive the engineer.
- The acceptance tests are frozen; leanlab rejects any attempt that edits, deletes, or neuters them.
- After `build`, the tech-lead updates `.leanlab/PLAYBOOK.md` — the project's growing conventions.
  You may read it to understand how this repo is built.
