# leanlab — session handoff

Read this first in a new session. It's the short map so you don't re-derive context.

## What leanlab is

A **framework for self-improving experiment labs**. A team of agents — **Workers**
(experimenters), a **Director**, and **HyperCritics** — evolve solutions against a
**frozen evaluator**, one experiment at a time. The same loop drives any task; you
swap the *lab*. It generalizes the trading "selflearn" idea: strategy → **Experiment**,
Manager → **Director**, `results.csv` → `results.jsonl`, objective is config not code.

Status: **built, archik-modelled, tested (17 pass), evaluator locked, and PROVEN with a
live run.** First live Worker loop ran 2026-06-21 (`run house-prices --n 2`): both workers
researched, wrote + validated an experiment, the loop scored and logged them — exit 0, no
bugs. Results 6–7: rmse 0.4132 and 0.4069 (neither beat best 0.40291, but both followed the
Director's "honest self-excluded KNN" guidance — the self-improving loop works).

## ⚠️ This project uses the `archik` engineering loop — follow it

`CLAUDE.md` mandates archik (NOT ArchiMate — "archik" is the project's own modelling
tool with a CLI + skill). **Model before code.** Hard rules:
- Interact with `.archik/` ONLY via `npx archik` CLI. **Never Read/Write/Edit
  `.archik/*.yaml` or sidecars by hand** — EXCEPT the four direct-write file types:
  `*.archik.actors.yaml`, `*.archik.uc.yaml`, `*.archik.seq.yaml`, `*.archik.alphas.yaml`.
- Loop: DISCOVER → DESIGN (actors → use case → structure → seq) → DECIDE (`/archik:accept`)
  → BUILD (numbered plan → "approve") → VERIFY (`validate`/`trace`/`drift`).
- Structural changes go through `npx archik suggest set` (full doc, not a delta) →
  user `/archik:accept`. Actors/use-cases/seqs are direct-write + `npx archik validate`.
- Coding principles: `.archik/PRINCIPLES.md` (OOP / SOLID / ports & adapters).

## The archik model (already done)

- **Actors** (`.archik/actors.archik.actors.yaml`): `operator` (human), `claude` (external-system).
- **Use case** `run-experiments` (`.archik/usecases/`): 3 slices — `rank-by-objective`
  (active, test_core.py), `score-and-log` (active), `fix-on-error` (active). All test-backed.
- **Structure** (`.archik/main.archik.yaml`, 13 nodes): `leanlab-cli`[boundary] →
  `loop`[control] → `agent-port`[boundary, PORT] ← implemented by `claude-agent` (+ proposed
  `hermes-agent`/`custom-agent`) → `claude`[external]; `agent-protocol`[control] = structured
  output + retry; `loop` → `evaluator`[control, the frozen scorer] + `results-store`[entity].
  `dashboard`, `lab` also present.
- **Behavior**: `.archik/run-experiments-{happy,fix}.archik.seq.yaml`, realize the two slices,
  ECB-clean. Rendered to `docs/*.svg`. `npx archik validate` clean, `drift` clean.

## 🩺 System check (2026-06-22)

One source of truth: the **tool** (`leanlab/` package + repo-root `.leanlab/`). A separate
`monorepo/` copy was built then **removed** — duplicated engine code drifts, and the tool repo
already serves as the in-repo dev workspace (`uv run leanlab run house-prices` runs in place).

**CLI UX upgrade (2026-06-22):** `init` now uses **rich + questionary** (leanlab's first runtime
deps — CLI-only; engine stays dep-free). `leanlab/core/init.py` routes all I/O through an injected
`ui` (default `RichUI`: spinner while Claude thinks, bordered panels for the objective + proposal,
a "view generated code" syntax view, and an arrow-key Approve / Feedback / Cancel menu). Tests inject
a `FakeUI` — 27 tests pass. The **run loop** (`loop.py`) is also rich-styled: a module-level
`console`, a rule per experiment, spinners while the Worker / Critic / Director work, colored result
lines (`✓ … ⭐ new best`), and a clean KeyboardInterrupt + Done summary.

**Coding lab — new direction, M1 shipped (2026-06-22):** a new lab *type* that runs
Worker/Director/Critic over a real repo, judged by tests + quality (design:
`docs/superpowers/specs/2026-06-22-coding-lab-design.md`). **M1 = `leanlab spec "<task>"`**:
`leanlab/core/coding/spec.py` (`spec-writer` node) drafts a spec + acceptance tests in an
**isolated git worktree**, approve/feedback loop, then **locks** the tests read-only (the
frozen per-task criteria the engineer can't change). Honesty model = locked-per-task +
ratchet + separation of duties. Modelled: use case `spec-task`, seq `spec-task.archik.seq.yaml`,
nodes `coding`/`spec-writer`/`acceptance-tests`. Tests: `tests/test_coding_spec.py` (4).
**M2 shipped:** `leanlab gate <slug>` — `leanlab/core/coding/gate.py` (`gate-runner` node): runs the
deterministic pass/fail gate on a task worktree (locked acceptance tests + project tests + optional
`--lint-cmd`); every command must exit 0. `GateResult{passed, checks}` is what the engineer loop
will rank on. Tests: `tests/test_coding_gate.py` (4).
**M3 shipped:** `leanlab build <slug>` — `leanlab/core/coding/engineer.py` (`engineer` + `reviewer`
nodes): engineer implements in the worktree → `gate` → on green the reviewer judges the diff →
loops on gate-fail / review-changes → commits + **merges the branch into main**. Configurable
personas in `leanlab/core/coding/personas.py` (`--persona-set`; `coding`={engineer,reviewer,techlead},
`metric`={worker,director,critic}; templates in `templates/agents/`). Use case `build-task` + seq.
Anti-gaming: `spec` records a sha of **every** locked test file (`.leanlab-lock.json`, multi-file);
`build` rejects a green gate if any hash changed (the chmod-lock alone is bypassable). `_merge`
returns success so `merged` is honest; gate caches excluded from staging.
**M4 shipped:** PLAYBOOK — `leanlab/core/coding/playbook.py` (`techlead` node + `playbook` entity):
the engineer's prompt is seeded with `.leanlab/PLAYBOOK.md` (`read_playbook`), and after a
successful merge the tech-lead rewrites it (`update_playbook`; `--no-playbook` to skip). The test
"ratchet" is automatic — each merged task's locked tests join main and stay. This is the
"gets better at the project over time" piece. Tests: `tests/test_coding_engineer.py` (6) +
`tests/test_coding_playbook.py` (4). build-task seq extended with the playbook flow.
**M5 shipped:** `leanlab board` — `leanlab/core/coding/board.py` (`coding-board` node): a live
dashboard of task cards (spec'd / merged / failed + attempts) + stat chips + the PLAYBOOK, built
from `.leanlab/worktrees`, `coding-results.jsonl` (written by `build`), and `PLAYBOOK.md`. Pure
`coding_state` + `render_board` (tested), thin live server.
**Board traces (2026-06-26):** `build`/`spec` write a structured event log (`.leanlab/events/<slug>.jsonl`
via `board.log_event`: spec, attempt+gate result, review+score, tamper, isolation, merged, gaveup).
The board now has a per-task **detail view** (`/?task=<slug>`; overview cards link to it): left =
**timeline** (those events, color-coded), right = **agent chat** — the engineer/reviewer transcript
(tool calls, messages, tokens, cost) parsed by reusing `monitor.parse_session` on the worktree's
`~/.claude/projects/<mangled>` dir. `task_detail` tested. **Board v2 (2026-06-26):** rebuilt as an **SSE single-page app** (no refresh
flicker) — black theme, `/api/stream` emits `state` (overview) + `task` (selected detail) events, JS
renders. Independently **scrollable** panels. **Grafana-style v3 (2026-06-26):** stat row (tasks · merged ·
success% · open · tokens · cost), a **sortable tasks table** with status badges + per-task tokens/cost,
a **"tokens by task" bar chart**, timeline + agent-chat detail panels, and a proper full-width
**playbook panel**. Per-task tokens/cost come from `_task_usage` (sums all the task's transcript
sessions, mtime-cached in `_USAGE_CACHE`). Black theme, responsive, vanilla (no build step).
`task_detail`/`coding_state` report `tokens`/`cost`/`success`. **71 tests.**
Coding lab is feature-complete (M1–M5 + traces). archik: 25 nodes, 35 edges, 6 use cases.
**Polish (2026-06-26):** `leanlab clean [slug] [--all]` removes task worktrees+branches (merged-only
by default); `build --min-quality N` rejects merges below a reviewer 0-100 quality score. Bug-hunt
fixes: worktree branches are marked `+ ` not `* ` (merged-branch parse); always `--force` worktree
removal (untracked `.leanlab-lock.json` blocked it); re-running `spec` on a task now unlocks the
locked tests before rewriting (was a PermissionError crash); a **deleted** locked test is now
caught as tampering. **Hardened honesty (2026-06-26):** the lock + a PRISTINE copy of the
acceptance tests now live OUT of the worktree (`.leanlab/locks/<slug>.json`) — the engineer (which
works inside the worktree) can't rewrite the lock to whitewash itself. `build` **restores the
pristine tests before every gate run**, so the gate always executes the original tests (edits/deletes
are undone), and a detected tamper attempt is still rejected. `clean` removes the lock too.
**Conftest/neutering closed (2026-06-26):** after a green gate, `build` re-runs the pristine
acceptance tests with engineer fixtures disabled (`pytest --noconftest`, configurable via
`--accept-cmd`, off via `--no-isolate`). If they pass *with* the engineer's conftest but fail
*without* it (exit 1), the attempt is rejected as gamed; any other exit (can't collect) doesn't
block. **64 tests total.** The honesty model now resists edit / delete / lock-tamper / fixture-neuter.
**Agent integration (2026-06-26):** `leanlab init --for-agent` installs a Claude Code **skill**
into the project's `.claude/skills/leanlab/SKILL.md` (shipped as package data at
`leanlab/templates/skill/SKILL.md`) so Claude Code can drive leanlab (spec → build → merge).
Headless flags added so an agent can run it without a TTY: `spec --yes` and `init --yes`
auto-approve the drafted tests/evaluator (`build`/`gate`/`board` were already non-interactive).
`init --for-agent` also **appends** leanlab guidance to the project's `CLAUDE.md` (idempotent, via
a `<!-- leanlab:agent -->` marker) so coding tasks route through leanlab by default. `spec` prints a
plain `slug: <slug>` line for the agent to parse. **68 tests total.**
Next: M4 PLAYBOOK + test ratchet (techlead persona already shipped) → M5 coding dashboard.

**Doctor + fix + prevention bundle (2026-06-22):** new `leanlab/core/doctor.py` (`lab-doctor`
node). `check_lab()` runs structural + wiring checks — the key one cheaply probes the evaluator
with a sentinel missing file to verify (a) the file arg reaches the script and (b) the output JSON
contains the objective metric key (catches the two iris bugs without a real run). CLI: `leanlab
check`, `leanlab fix` (Claude edits the lab to resolve failures, unlock/relock evaluator, re-check
loop), and `leanlab run` now runs a **preflight** that aborts on failures (`--skip-checks` to
bypass). Prevention: init **self-verifies** after writing the evaluator (runs the doctor, loops back
to Claude to fix before finishing) and **auto-installs** the evaluator's declared `packages` via
`uv add`. Tests in `tests/test_doctor.py` (7). 34 tests total.

**Init contract-consistency fix (2026-06-22):** the propose prompt now forces the generated
`evaluation.py`/`validate.py` to (1) parse args matching `lab.json`'s `eval_cmd`/`validate_cmd`
(argparse `--experiment`, not positional) and (2) print the objective metric under its EXACT key
(not a generic `score`). Earlier inits drifted — e.g. iris had metric `FPS` but evaluation.py
printed `score`, and the scripts read `sys.argv[1]` while the command passed `--experiment` →
every score 0 ("file not found: --experiment"). Dashboard also hardened: results table now
stringifies non-scalar cell values (was rendering nested objects as `[object Object]`).

Full check: 27 tests pass, byte-compile clean, archik validate/trace/drift clean, CLI smoke-tested.
Dashboard role detection was untested → added tests. `init` prompts hardened: pick the metric that
fits the task type (no RMSE default), never write files before approval (approve-gate), ignore
sibling labs, guard bad objective shape, and print progress so it doesn't look frozen.

## ⚙️ Repackaged as a tool — M1 DONE 2026-06-21

leanlab is now an **installable `uvx` tool** (like archik), not a monorepo. Paths below
moved: the engine lives in the `leanlab/` package; labs live in the consuming project's
`.leanlab/<name>/`. Key facts:
- Package: `leanlab/cli.py` (entry point `leanlab`), `leanlab/core/{loop,monitor}.py`,
  `leanlab/core/agents/`, fixed specs as package data in `leanlab/templates/agents/`.
- Labs resolve to `.leanlab/<name>/` in **cwd** (the example is `.leanlab/house-prices` —
  the repo dogfoods itself). Only user files there; **no agent specs copied**.
- The loop **injects** the fixed specs into prompts (each starts `You are the WORKER/
  DIRECTOR/CRITIC …`); the dashboard's role detection was updated to match.
- leanlab core has **zero** third-party deps; ML libs (sklearn/lightgbm/catboost) are in
  the dev group (for the example + tests).
- **M2 DONE 2026-06-21** — interactive AI-driven `init`. `leanlab/core/init.py`
  (`init-architect` node): `run_init(lab, name, description, *, runner, ask, say)` scaffolds
  the lab, has Claude draft task.md + objective, then proposes an evaluator in a loop until
  the operator approves (writes evaluation.py + validate.py). `runner`/`ask`/`say` are
  injected so it's tested with a fake transport (`tests/test_init.py`, 4 tests) — **not yet
  run live** (costs Claude). Modelled: use case `init-lab` (2 active slices), seq
  `.archik/init-lab.archik.seq.yaml`, entity `lab-scaffold`. Design:
  `docs/superpowers/specs/2026-06-21-leanlab-as-a-tool-design.md`.

Paths in the section below are pre-M1; mentally map `core/`→`leanlab/core/`,
`leanlab.py`→`leanlab/cli.py`, `labs/`→`.leanlab/`.

## Built code

- `core/loop.py` — generic loop: reads `lab.json`, builds Worker prompt, drives the runner,
  runs the evaluator (parses ONE JSON metrics line), ranks by objective {metric, direction},
  appends to `results.jsonl`; wakes Director/Critic on cadence. `make_runner()` is the seam.
- `core/agents/` — **ports & adapters** (the Agent abstraction):
  - `port.py` — `AgentTransport` (send→(session,text)) + `AgentRunner`
    (`run_structured(prompt, required_keys)→AgentResult`, `run_plain`) + `AgentResult`.
  - `protocol.py` — `StructuredRunner(AgentRunner)`: validate JSON + **retry on malformed**
    (re-prompt "reply with ONLY that JSON object"). Wraps a transport.
  - `claude.py` — `ClaudeAgent(AgentTransport)`: `claude -p --output-format json [--resume]`.
  - To add Hermes/custom: new `AgentTransport`; swap `make_runner()`. Loop unchanged.
- `core/monitor.py` — schema-driven dashboard. **Grafana-style vertical board** (2026-06-21):
  full-width foldable cards — stat chips (best/latest/experiments/total cost) → "Sessions &
  live stream" (master-detail: vertical session list left, stream right) → Progress → Results
  → Critics + Director. Fold state persists in localStorage. Pure helpers
  `latest_value()` / `total_cost()` feed the chips; tested in `tests/test_monitor.py`.
  Progress chart uses **Chart.js 4.4.1 via cdnjs** (line + best-so-far, tooltips, axes,
  legend) — needs internet (graceful "offline?" fallback if the CDN is blocked).
- `core/agents/{CLAUDE.md,director.md,critic.md}` — generic agent-prompt TEMPLATES (copied
  into each lab by `init`). (These `.md` live beside the `.py` — that's fine.)
- `leanlab.py` — CLI: `init <name>`, `run <lab> --n N`, `serve <lab>`, `list`,
  `lock <lab>` / `unlock <lab>` (chmod 0444/0644 the evaluator).
- `labs/house-prices/` — example lab: predict CA housing value, **minimize rmse**; experiment
  defines `build_estimator()` (sklearn). `evaluation.py` (frozen, **locked read-only**),
  `validate.py`, `task.md`, `lab.json`, `experiments/sample.py`, `results.jsonl`.
- `tests/` — 26 pass: `test_core.py` (ranking), `test_run_experiments_happy.py`,
  `test_run_experiments_fix.py`, `test_monitor.py` (dashboard stat helpers + role detection),
  `test_tooling.py` (.leanlab resolution + spec injection), `test_init.py` (interactive init).

## How to run

> User-facing command guide: **`docs/USAGE.md`** (the flow + what each command does).


```bash
uv sync
uv run pytest                              # 21 pass
uv run leanlab list                        # labs in this project's .leanlab/
uv run leanlab run house-prices --n 3      # live Workers (costs Claude)
uv run leanlab serve house-prices          # dashboard
uv run leanlab lock|unlock house-prices
# used in another project once published: uvx leanlab init <name>
npx archik validate && npx archik trace && npx archik drift
```

## What's next (open, user-chosen earlier)

1. ~~**Dashboard overhaul**~~ ✅ **DONE 2026-06-21** — Grafana-style vertical board of
   foldable cards; right-column overflow fixed (Results is its own full-width row).
   Design: `docs/superpowers/specs/2026-06-21-dashboard-overhaul-design.md`.
2. **Wire a second backend** (HermesAgent) — proves the abstraction; flip `hermes-agent` active.
3. ~~**Live run** on house-prices~~ ✅ **first run DONE 2026-06-21** (--n 2, clean).
   Next: a longer run (`--n 5`+) to exercise the Director + Critic wake-ups (every 5 loops).
4. (Bigger, optional) Hard evaluator isolation via a separate OS user/sandbox — the `lock`
   command is only a guardrail (an agent as the same user could `chmod +w`).

See `FUTURE.md` for parked dashboard ideas (drag-to-rearrange grid, per-panel zoom).

## archik gotchas learned

- Use cases have NO `kind` field.
- Seq participants must be architecture node ids — **actors can't be participants**; start the
  seq at the boundary node and note the actor trigger.
- Renaming a node id = remove + add via a sidecar (did this for judge→evaluator).
- Quote YAML values containing colons.
- ECB allowed transitions: boundary→control, control→{boundary|control|entity}, entity→{control|entity};
  forbidden: boundary→boundary, boundary→entity, entity→boundary. Untagged nodes are skipped.

## Related (siblings, separate projects — usually not needed here)

`~/projects/selflearn-trader` (BTC 4h strategy lab) and `~/projects/selflearn-scalper`
(BTC 1m scalping) — the working instances leanlab was extracted from. Same agent-team pattern.
