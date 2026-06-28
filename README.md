# leanlab

[![PyPI](https://img.shields.io/pypi/v/leanlab.svg)](https://pypi.org/project/leanlab/)
[![CI](https://github.com/bacharSalleh/leanlab/actions/workflows/ci.yml/badge.svg)](https://github.com/bacharSalleh/leanlab/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/leanlab.svg)](https://pypi.org/project/leanlab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**A self-improving experiment lab for AI agents.** Point leanlab at a metric and
a team of Claude agents — a Worker, a Director, and a Critic — evolves ML /
optimization experiments against a frozen evaluator, while you watch on a live
dashboard.

## Install

```bash
pipx install leanlab        # or:  pip install leanlab   ·   uvx leanlab
```

📦 On PyPI: **[pypi.org/project/leanlab](https://pypi.org/project/leanlab/)**

Requires **Python 3.11+** and the **`claude` CLI** (the agents run on Claude Code).

## Quick start

leanlab runs **inside your own project** — each lab lives in a `.leanlab/<name>/`
folder; the engine stays in the installed tool.

Evolve a number (ML, optimization, anything that prints a score):

```bash
cd ~/my-project
leanlab init iris          # describe the task; Claude drafts the lab + scorer
leanlab check iris         # verify it's wired correctly (free)
leanlab lock iris          # freeze the scorer
leanlab run iris --n 5     # the agents evolve experiments (uses Claude)
leanlab serve iris         # watch the live dashboard
```

The Worker invents an experiment each round, the Critic red-teams it, and the
Director steers the next round — all scored by the frozen evaluator you locked.

## Docs

- **[docs/USAGE.md](docs/USAGE.md)** — every command, in order, with examples.
- **[docs/OVERVIEW.md](docs/OVERVIEW.md)** — how it works: the loop, the agents,
  and the project structure.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — local development (uv, tests).

MIT licensed — see [LICENSE](LICENSE).
