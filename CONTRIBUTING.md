# Contributing to leanlab

Thanks for helping improve leanlab! This guide covers the local setup, the
checks that must pass, and how the project is modelled.

## Local setup

leanlab is a Python tool (managed with [uv](https://docs.astral.sh/uv/)) with a
React + Tailwind UI for the coding board (built with Node).

```bash
# Python engine
uv sync                      # install deps + dev tools into .venv
uv run pytest                # the test suite
uv run leanlab --version     # run the CLI from the checkout

# Board UI (only if you touch frontend/)
cd frontend
npm install
npm run build                # compiles into leanlab/core/coding/board_dist/
npm run dev                  # live dev server (proxies /api → leanlab board on :8766)
```

## Checks that must pass

Before opening a PR:

```bash
uv run pytest                                  # all tests green
npx archik validate                            # architecture model is consistent
npx archik drift                               # model matches the source tree
cd frontend && npm run build                   # the UI still compiles (if you touched it)
```

CI runs the same on Python 3.11–3.13.

## How the project is modelled

leanlab follows the **archik engineering loop** — model before code, respect the
HITL gates, fix the model before the code when they disagree. See
[`.archik/ENGINEERING_LOOP.md`](.archik/ENGINEERING_LOOP.md) and
[`.archik/PRINCIPLES.md`](.archik/PRINCIPLES.md).

- **Requirements → structure → behavior → code, in that order.**
- The architecture lives in `.archik/` and is edited only through `npx archik`
  (never by hand). Use cases, actors, and sequence diagrams are direct-write.
- New behavior, a new structural shape, a new external interaction, or a new
  actor → run the loop. Pure refactors / local bug fixes → just edit.

## Commit & PR conventions

- Small, reversible commits — one logical change each.
- Conventional-commit-ish prefixes are appreciated (`feat:`, `fix:`, `docs:`,
  `chore:`, `refactor:`).
- Describe what changed and why; link any issue.
- Add or update tests for behavior changes.

## Reporting bugs / requesting features

Open an issue using the templates under
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE). Security issues: see
[SECURITY.md](SECURITY.md) — please don't file them as public issues.
