# leanlab

[![PyPI](https://img.shields.io/pypi/v/leanlab.svg)](https://pypi.org/project/leanlab/)
[![CI](https://github.com/bacharSalleh/leanlab/actions/workflows/ci.yml/badge.svg)](https://github.com/bacharSalleh/leanlab/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/leanlab.svg)](https://pypi.org/project/leanlab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Self-improving labs for AI agents.** Point leanlab at a task and a team of
Claude agents iterates toward a goal — evolving ML / optimization experiments
against a frozen metric, or shipping coding tasks through a
spec → gate → review → merge loop with locked acceptance tests.

## Install

```bash
pipx install leanlab        # or:  pip install leanlab   ·   uvx leanlab
```

Requires **Python 3.11+** and the **`claude` CLI** (the agents run on Claude Code).

## Quick start

leanlab runs **inside your own project** — each lab lives in a `.leanlab/<name>/`
folder; the engine stays in the installed tool.

**Metric lab** — evolve a number (ML, optimization, anything that prints a score):

```bash
cd ~/my-project
leanlab init iris          # describe the task; Claude drafts the lab + scorer
leanlab check iris         # verify it's wired correctly (free)
leanlab lock iris          # freeze the scorer
leanlab run iris --n 5     # the agents evolve experiments (uses Claude)
leanlab serve iris         # watch the live dashboard
```

**Coding lab** — ship a coding task with locked acceptance tests:

```bash
cd ~/my-repo                              # a git repository
leanlab spec "add a /health endpoint"    # spec-writer drafts + locks the tests
leanlab build add-health                 # engineer → gate → reviewer → merge
leanlab board                            # live board: tasks, timeline, playbook
```

## Let Claude Code drive it

```bash
cd ~/my-project && leanlab init --for-agent   # installs a Claude Code skill
```

Then just ask Claude Code — *"use leanlab to add a /health endpoint"* — and it
specs, builds, and merges through the honest test gate for you.

## Docs

- **[docs/USAGE.md](docs/USAGE.md)** — every command, in order, with examples.
- **[docs/OVERVIEW.md](docs/OVERVIEW.md)** — how it works: the loop, the two lab
  types, the coding-lab flow, and the project structure.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — local development (uv, tests, the React board).

MIT licensed — see [LICENSE](LICENSE).
