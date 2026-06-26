# leanlab as a tool — design

**Date:** 2026-06-21
**Status:** approved (design); to be modelled in archik before code.
**Scope:** turn leanlab from a monorepo into an installable research tool (like archik),
used inside other projects, with an AI-driven interactive `init`.

## The shift

Today leanlab is a monorepo: labs live in `labs/`, and `init` copies *every* file
(including fixed agent specs) into each lab. We want leanlab to be a **tool used inside
other projects** — the engine stays in the installed package; only task-specific files
live in the user's project.

## 1. Distribution

- leanlab becomes a pip package with a CLI entry point, run via **`uvx leanlab ...`**
  (no global install — same feel as `npx archik`).
- Fixed files ship as **package data** inside the wheel and are resolved at runtime
  (e.g. `importlib.resources`), never copied into the user's project.

## 2. File ownership

| In the **library** (fixed, resolved from the package) | In the **project** under `.leanlab/<lab>/` (user-owned) |
|---|---|
| `loop.py`, `monitor.py` (engine) | `task.md` — the goal + experiment contract |
| agent specs: `CLAUDE.md`, `director.md`, `critic.md` | `lab.json` — objective + config |
| the `init` architect logic | `evaluation.py` — the frozen judge |
| ports & adapters (`agents/`) | `validate.py` — the cheap structural check |
| | `results.jsonl`, `Director_Notes.md`, `Critic_Feedback.md` (run output) |

A consuming project only ever sees a small `.leanlab/` folder, like `.archik/`.

## 3. The new interactive `init`

`leanlab init <name>` becomes a human-in-the-loop, Claude-driven flow:

1. Create `.leanlab/<name>/` skeleton (dirs + empty `results.jsonl`).
2. CLI prompts the user to **describe the task** (free text).
3. leanlab calls **Claude** (an "architect" role) → drafts `task.md` (proper goal +
   experiment contract) and infers `lab.json`'s objective (`metric`, `direction`).
4. Claude **interviews** about evaluation data: if the task needs data it asks the user
   to point to it; if not (speed/benchmark/self-contained metric) it writes a standalone
   evaluator.
5. Claude **proposes an evaluation approach** (plain-English) → shown to the user.
6. **Approval gate:** user approves → write `evaluation.py` (+ `validate.py`).
   User gives feedback → Claude revises → re-propose. Loop until approved.
7. Remind the user to review + `lock` the evaluator, then `run`.

All four task files (`task.md`, `lab.json`, `validate.py`, `evaluation.py`) are produced;
`evaluation.py` is the gated one.

## 4. Reuse of the agent abstraction

`init` talks to Claude through the **existing `AgentRunner`** (`StructuredRunner` +
`ClaudeAgent`). Only a new "architect" agent role/prompt is added — no new transport.
This proves ports & adapters works beyond the worker/director/critic loop.

## 5. Agent specs stay fixed (v1)

`CLAUDE.md` / `director.md` / `critic.md` live in the package and are read from there by
the engine. Per-project override (`.leanlab/<lab>/agents/`) is **future**, not v1.

## Build order — two milestones

- **M1 — Repackage:** leanlab as a `uvx` tool; `.leanlab/` convention; engine resolves
  fixed files from the package and user files from the project. No change to the loop's
  behavior — only where files live. Existing tests stay green; `init` keeps its current
  (stub) behavior but writes into `.leanlab/`.
- **M2 — Interactive init:** the Claude-driven `init` (describe → draft → propose eval →
  approve loop). Builds on M1's file layout.

This spec covers the whole vision; **M1 is the immediate scope**.

## Archik model (to be staged for M1, then M2)

- New use case `init-lab` (primary actor: `operator`).
- New **control** node `init-architect`; reuses `leanlab-cli` (boundary) and `agent-port`.
- The `.leanlab/<lab>/` store as the **entity** (extends `results-store` / a new lab-store).
- One seq diagram for the M2 approve-loop.

## Out of scope (FUTURE.md)
- Per-project override of agent specs.
- Publishing to PyPI (we can run via `uvx --from <path>` / `uv tool install .` locally first).
- Migrating the existing `labs/` examples into the new layout (kept as in-repo examples).
