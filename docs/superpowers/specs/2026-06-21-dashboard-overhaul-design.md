# Dashboard overhaul — design

**Date:** 2026-06-21
**Scope:** `core/monitor.py` (the `PAGE` HTML + the `build_state()` payload it feeds).
**Goal:** Replace the cramped 3-column fixed-height dashboard with a Grafana-style
vertical board of full-width, collapsible cards, and fix the right-column overflow.

## Why

Today the dashboard is a 3-column grid pinned to the viewport height:

| Column | Width | Holds |
|--------|-------|-------|
| left | 230px | sessions |
| middle | flexible | live stream |
| right | 380px | progress chart + results table + critics + director |

The right column crams four panels into 380px. The results table (one column per
metric) overflows that width. Nothing has room.

## New layout — a vertical board

Full-width cards stacked in rows. The whole page scrolls. Each card has a title bar
that folds (`▾` open / `▸` closed).

Rows, top to bottom:

1. **Header** — lab name, objective, streaming status, clock. (unchanged content)
2. **Stat chips** — a row of 4 metric cards: `best`, `latest`, `experiments`, `total cost`.
3. **Sessions** — a horizontal strip of session chips; click one to load it into the stream.
4. **Live stream** — its own full-width row, **fixed height (default 320px), scrolls inside**.
5. **Progress** — its own full-width row; the chart is now wide and tall.
6. **Results** — its own full-width row; big table, all metric columns visible.
   If still wider than the card, the table scrolls horizontally **inside** its card.
7. **Critics + Director** — two folded panels sharing the last row, side by side.

### Defaults
- Critics and Director start **folded**; every other panel starts open.
- Stream fixed height: **320px** (constant, easy to tweak).

### Collapse persistence
Which panels are folded is saved to `localStorage` so the board remembers your
layout across reloads. (Small, optional polish — drop it if it complicates the build.)

## Data changes (`build_state()`)

The stat chips need two values the payload does not expose yet. Both are pure,
testable functions over data already in memory:

| Chip | Source | New? |
|------|--------|------|
| best | `best_value(rows)` | exists |
| latest | metric value of the **last** row in `results` | **new** — `latest_value(rows)` |
| experiments | `len(rows)` | trivial (compute in JS) |
| total cost | sum of `cost` across all sessions | **new** — sum in `build_state()` |

`build_state()` gains two fields: `latest` and `total_cost`. Everything else in the
payload stays the same.

## What is NOT changing
- The SSE streaming protocol (`/api/stream`, `state` + `session` events).
- Session parsing, pricing math, transcript discovery.
- The server/handler classes.
- No new files, no new dependencies. One file touched: `core/monitor.py`.

## Architecture / archik note
This is a single-file UI refactor of the existing `dashboard` node. It adds no new
actor, no new structural node, and no new external interaction — it reshapes the
presentation of the already-modelled "watch the run" capability. Per the archik
"match ritual to scope" rule this qualifies for the lighter path (skip the modelling
gates, go straight to a BUILD plan). The two new payload fields are covered by unit
tests.

## Testing
- `latest_value(rows)` — returns the metric of the last row; `None` for empty / unparseable.
- `total_cost` aggregation in `build_state()` — sums session costs; `0.0` for no sessions.
- Existing 11 tests stay green.
- Manual eyeball: run `serve house-prices`, confirm rows stack, panels fold, stream
  scrolls at fixed height, results table no longer overflows.

## Out of scope (FUTURE.md)
- Drag-to-rearrange / drag-to-resize panels (full Grafana grid).
- Per-panel time ranges or zoom.
