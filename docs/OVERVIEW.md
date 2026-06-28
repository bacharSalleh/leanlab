# How leanlab works

This is the deeper tour — the idea, the loop, and the project structure. For
installation and day-to-day commands, see the [README](../README.md) and
[USAGE.md](USAGE.md).

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

## The team

One loop, three Claude agents, each with a job:

| Agent | Job |
|-------|-----|
| Worker (experimenter) | makes the attempt — writes one new experiment |
| Director (chief scientist) | steers + maintains the notes |
| Critic (red-team) | finds what's wrong |

And `init` drafts the lab itself (task + objective + evaluator) before the loop
ever runs.

**Core concepts**

| Concept | What it is |
|---------|-----------|
| Experiment | one file in `experiments/` |
| Frozen evaluator | `evaluation.py` → JSON metric |
| Objective metric | min rmse / max acc |
| Memory | top-N best experiments, injected |
| `Director_Notes.md` | the Director's running plan |
| `Critic_Feedback.md` | the Critic's red-team notes |
| `results.jsonl` | one row per experiment |
| best-so-far | kept by ranking |

The whole thing is one idea: **make an attempt → judge it → keep the best →
learn for next time.**

## Structure

```
leanlab/                     # the installable tool (engine — never copied into your project)
├── cli.py                   # commands: init · check · fix · run · serve · list · lock · unlock
├── core/
│   ├── loop.py              # run N experiments, score, log, wake Director/Critic
│   ├── monitor.py           # the live dashboard
│   ├── init.py              # interactive `init` — Claude drafts task + evaluator
│   ├── doctor.py            # preflight checks + Claude-powered `fix`
│   └── agents/              # ports & adapters — the backend-agnostic agent layer
└── templates/agents/        # the agent personas (injected into prompts, not copied)

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
- The evaluator and agent personas live in the package and are injected into
  prompts — nothing framework-level is copied into your project.
