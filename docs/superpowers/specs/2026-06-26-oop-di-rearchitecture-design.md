# OOP + DI re-architecture of the Python codebase

**Date:** 2026-06-26
**Status:** approved (design)

## Goal

Bring the Python codebase in line with the project's own
[`.archik/PRINCIPLES.md`](../../../.archik/PRINCIPLES.md): object-oriented,
SOLID, composition over inheritance, and dependency injection. Today most
subsystems are free module-level functions that thread collaborators
(`runner=`, `ui=`, `gate_cmds=`) as parameters. We replace them with classes
that *hold* their collaborators, injected via the constructor.

This is a **behavior-preserving refactor**: no feature changes, no CLI changes,
no archik *use-case* changes. The 86 tests must stay green throughout.

## Principles (decided)

- **Constructor injection + a single composition root.** Each class receives its
  collaborators in `__init__`. The CLI command that runs a use case is the only
  place that builds the object graph and wires the real adapters. No DI
  framework, no container, no runtime dependency.
- **Pragmatic OOP.** Every stateful / collaborator-holding unit becomes a class.
  Value objects stay `@dataclass`. Genuinely pure, stateless helpers become
  `@staticmethod` on the relevant class. We do not create empty classes just to
  hold a one-line helper.
- **Incremental.** One subsystem at a time; tests green + archik updated +
  committed after each. No big-bang.
- **Follow the existing good example.** `core/agents/` is already ports +
  adapters (`AgentTransport`, `AgentRunner`, `AgentResult`, `StructuredRunner`,
  `ClaudeAgent`). It is the template; it does not change.

## The pattern

Before:

```python
def build_task(repo, slug, *, runner=None, ui=None, gate_cmds=None, reviewers=1, ...):
    ...
```

After:

```python
class Engineer:                        # control
    def __init__(self, runner, gate, reviewers, tech_lead, locks, events, git, ui):
        ...
    def build(self, slug, *, max_attempts=5, min_quality=0) -> BuildResult:
        ...
```

The DI seam already exists (functions take `runner`/`ui`); the change is to make
each subsystem an object that owns those collaborators instead of receiving them
per call.

## Class map — coding lab (first increments)

| Unit | Type | Injected collaborators |
|------|------|------------------------|
| `Gate` | control | `commands`, `timeout` |
| `ReviewPanel` | control | `runner`, `Personas`, `n` |
| `TechLead` | control | `runner`, `Personas`, `Playbook`, `EventLog` |
| `SpecWriter` | control | `runner`, `Git`, `LockStore`, `ui` |
| `Engineer` | control | `runner`, `Gate`, `ReviewPanel`, `TechLead`, `LockStore`, `EventLog`, `Git`, `ui` |
| `Board` | control | `EventLog`, `Transcripts`, `repo` |
| `Git` *(new)* | adapter | git CLI: worktree / branch / merge ops |
| `LockStore` *(new)* | entity | repo: lock read/write, restore-pristine, tamper check |
| `EventLog` *(new)* | entity | repo: events jsonl read/append |
| `Transcripts` *(new)* | entity | `~/.claude` session parse + usage (cached) |
| `Personas` | value | persona set |
| `GateResult`, `GateCheck`, `BuildResult`, `Verdict`, `SpecResult` | dataclass | — |

- The honesty logic (`_is_pristine`, `_restore_tests`, isolated-acceptance) moves
  onto `LockStore` + `Engineer`.
- `_slug`, `fmtK`, `evMeta` become `@staticmethod`.
- `SpecUI` / `BuildUI` stay as UI classes (boundary); the board's HTTP server
  becomes `BoardServer` (boundary).

## Class map — metric lab (later increments)

| Unit | Type | Injected collaborators |
|------|------|------------------------|
| `ExperimentLoop` | control | `runner`, `Evaluator`, `ResultsStore`, `Lab`, `Director`, `Critic` |
| `Evaluator` | control | `Lab` (runs `eval_cmd` as subprocess) |
| `ResultsStore` | entity | repo: results.jsonl read/append/rank |
| `Lab` | value | parsed `lab.json` (objective, commands, cadences) |
| `InitArchitect` | control | `runner`, `ui`, `LabScaffold` |
| `LabScaffold` | entity | writes/creates lab files |
| `LabDoctor` | control | probes wiring; `fix(runner)` |
| `Dashboard` / `BoardServer` | boundary | `ResultsStore`, `SessionParser` |

## Composition root

The CLI command is the only place that constructs the graph:

```python
def cmd_build(args):
    repo, wt = Path.cwd(), worktree_for(args.slug)
    runner = ClaudeRunner(wt)
    eng = Engineer(
        runner,
        Gate(cmds),
        ReviewPanel(runner, Personas(args.persona_set), args.reviewers),
        TechLead(runner, Personas(args.persona_set), Playbook(repo), EventLog(repo)),
        LockStore(repo), EventLog(repo), Git(), BuildUI(),
    )
    eng.build(args.slug, max_attempts=args.max_attempts, min_quality=args.min_quality)
```

Everything below the CLI receives ready-made objects; nothing reaches for a
global or builds its own dependencies.

## Testing strategy

Behavior is unchanged, so assertions stay the same. Tests construct the class
with fakes instead of calling a function with fakes:

```python
eng = Engineer(runner=FakeDev(wt), gate=Gate([{"name": "tests", "cmd": PYTEST}]),
               reviewers=ReviewPanel(FakeDev(wt), Personas("coding"), 1), ...)
res = eng.build("demo", max_attempts=3)
assert res.merged
```

The same fakes (`FakeTransport`, `FakeDev`, `FakeUI`) are reused; only the wiring
moves from call-site kwargs to constructor args. All 86 tests stay green after
every increment.

## archik reflection

The existing structural nodes (`engineer`, `gate-runner`, `reviewer`, `techlead`,
`playbook`, `spec-writer`, `coding-board`, `loop`, `evaluator`, `results-store`,
`init-architect`, `lab-scaffold`, `lab-doctor`, `dashboard`, `agent-port`,
`agent-protocol`, `claude-agent`) map 1:1 to these classes — so the use-case and
behavioral models do not change. Structurally the model **gains the extracted
collaborator nodes** (`Git`, `LockStore`, `EventLog`, `Transcripts`,
`ReviewPanel`) with ECB stereotypes + edges, staged via `suggest set` per
increment. `npx archik drift` stays clean (every node keeps a real `sourcePath`).

## Sequencing (each: tests green → archik sidecar → commit)

1. Shared entities/adapters: `EventLog`, `LockStore`, `Git`, `Transcripts`.
2. `Gate` + `Personas`.
3. `Playbook` / `TechLead`, `ReviewPanel`.
4. `SpecWriter`.
5. `Engineer` (ties the coding lab together).
6. `Board` / `BoardServer`.
7. Metric side: `ResultsStore`, `Evaluator`, `Lab`, `ExperimentLoop`;
   `InitArchitect` / `LabScaffold`; `LabDoctor`; `Dashboard`.
8. `cli.py` becomes the thin composition root.

## Non-goals

- No new features, no behavior changes, no CLI surface changes.
- No DI framework / container; no new runtime dependencies.
- `core/agents/` is unchanged.
- No archik *use-case* or *sequence* changes (only new structural collaborator
  nodes).

## Acceptance criteria

- Every listed subsystem is a class with constructor-injected collaborators; the
  CLI is the composition root.
- No free module-level functions remain except `main()`/`cmd_*` entry points and
  `@staticmethod` pure helpers.
- `uv run pytest` → 86 passed at every increment boundary.
- `npx archik validate` + `npx archik drift` clean; `npx archik trace` still
  11 full.
