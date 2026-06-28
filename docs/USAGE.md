# leanlab — commands & flow

leanlab is a tool you run **inside your own project** (like archik). It keeps each
research "lab" in a `.leanlab/<name>/` folder. You describe a task, Claude builds a
scorer, then a team of Claude agents evolves experiments to beat that score.

---

## The normal flow (top to bottom)

```
leanlab init <name>     ->  describe the task; Claude drafts the lab
leanlab check <name>    ->  make sure the lab is wired correctly
leanlab fix <name>      ->  (only if check failed) let Claude repair it
leanlab lock <name>     ->  freeze the scorer so agents can't cheat
leanlab run <name>      ->  the agents evolve experiments (costs Claude)
leanlab serve <name>    ->  open the live dashboard to watch
leanlab list            ->  see all labs in this project
```

You usually run `init` once, then `lock`, then `run` + `serve`. `check`/`fix` are
safety nets.

---

## What each command does — exactly

### `leanlab init <name>`
Builds a new lab in `.leanlab/<name>/`, with Claude's help.

1. Asks you to **describe the task** in plain words.
2. Claude drafts `task.md` (the goal) and picks the **objective** (the metric to
   beat, and whether higher or lower is better) into `lab.json`.
3. Claude **proposes a way to score** experiments; you **approve** it, ask to
   **view the code**, or give **feedback** to revise (it loops until you approve).
4. On approve it writes `evaluation.py` (the scorer) and `validate.py` (a quick check),
   installs any libraries the scorer needs, and **self-checks** the lab is wired right.

> Example: `leanlab init iris` → "classify iris flowers; maximize accuracy" → Claude
> writes a scorer that prints `{"accuracy": ...}`.

Files it creates (yours to edit): `task.md`, `lab.json`, `evaluation.py`,
`validate.py`, `results.jsonl`, `Director_Notes.md`, `Critic_Feedback.md`.

### `leanlab check <name>`
A **preflight** — verifies the lab is set up correctly, **without running anything
expensive**. It checks:

- `lab.json` is valid and names a metric + direction.
- `task.md`, `evaluation.py`, `validate.py`, `experiments/` exist.
- the `claude` CLI is installed.
- the worker / director / critic prompts can be built.
- **the scorer is wired right**: it reads the experiment file argument correctly, and
  prints the **same metric name** that `lab.json` expects.

Prints `✓ / ⚠ / ✗` per check. Exit code is non-zero if anything fails.

### `leanlab fix <name>`
Runs `check`, and if something failed, lets **Claude edit the lab to repair it**
(fix argument parsing, match the metric name, create missing files). It unlocks the
scorer if needed, fixes, re-locks, and re-checks — up to 3 rounds.

### `leanlab lock <name>` / `leanlab unlock <name>`
`lock` makes `evaluation.py` **read-only** so the experimenting agents can't change
how they're judged. `unlock` makes it writable again (to edit the scorer yourself).

> This is a guardrail, not a sandbox — an agent running as you could undo it.

### `leanlab run <name> [--n N] [--skip-checks] [--dry-run]`
Runs the experiment loop. **Costs Claude usage.**

1. First it runs the **preflight checks** and **stops if any fail** (telling you to
   `leanlab fix`). Use `--skip-checks` to bypass.
2. Then, `N` times (default 5):
   - a **Worker** (Claude) writes one new experiment and validates it,
   - the frozen `evaluation.py` **scores** it and appends a row to `results.jsonl`,
   - every 5 loops a **Director** rewrites the plan and a **Critic** red-teams the work.
- `--dry-run` prints the Worker prompt and does nothing (free).

### `leanlab serve <name>`
Opens the **live dashboard** in your browser — stat chips (best / latest / cost),
the session list + live agent stream, the progress chart, the results table, and the
Director/Critic notes. Read-only; safe to open during a run.

### `leanlab list`
Lists every lab in this project's `.leanlab/` with its objective.

---

## Install

```bash
uv tool install --force --editable /path/to/leanlab    # once
cd ~/my-project && uv init                              # your project must be a uv project
```

The lab's scorer runs with `uv run`, and Workers `uv add` libraries — so the project
needs its own `pyproject.toml`.

---

## Quick reference

| Command | What | Costs Claude? |
|---------|------|---------------|
| `init <name>` | build a lab with Claude | a little |
| `check <name>` | preflight wiring checks | no |
| `fix <name>` | Claude repairs wiring issues | a little |
| `lock` / `unlock <name>` | freeze / unfreeze the scorer | no |
| `run <name> --n N` | evolve N experiments | **yes** |
| `run <name> --dry-run` | print the prompt only | no |
| `serve <name>` | live dashboard | no |
| `list` | list labs | no |
