# Future work (out of scope, parked)

## Coding lab (new direction — design: docs/superpowers/specs/2026-06-22-coding-lab-design.md)
- **Configurable agent personas** (requested): pick which template set the loop uses —
  metric set (Worker / Director / Critic) vs coding set (Engineer / Tech-lead / Reviewer) —
  via a `lab.json` `personas` field **and** a CLI override flag. Lands in **M3** (the engineer
  loop, where Director/Critic/Tech-lead actually run). M1 (spec-writer) shipped 2026-06-22.
- ✅ M1–M5 all shipped (2026-06-22): spec · gate · build (engineer/reviewer + personas) ·
  PLAYBOOK/ratchet (tech-lead) · board. Configurable personas done (`--persona-set`).
  Open polish: lock+hash already covers multi-file; remaining ideas → live end-to-end run,
  parallel attempts, worktree cleanup (`leanlab clean`), per-lab quality threshold.
- Adversarial stress-testing of changes (sequoia-style worst-case selection).

## leanlab as a tool
- **Publish to PyPI** so `uvx leanlab` works without `--from <path>`. For now run via
  the local checkout (`uv run leanlab …` / `uvx --from <path> leanlab …`).
- **Per-project agent-spec override** — let a project drop `.leanlab/<lab>/agents/*.md`
  to override the packaged CLAUDE.md / director.md / critic.md. v1 keeps them fixed.

## Dashboard
- **Drag-to-rearrange / drag-to-resize panels** — a full Grafana grid where you
  drag panels to reorder or resize them. Deferred from the 2026-06-21 dashboard
  overhaul (which gave each panel its own full-width row + fold/unfold instead).
  See `docs/superpowers/specs/2026-06-21-dashboard-overhaul-design.md`.
- **Per-panel time ranges / zoom** on the Progress chart.
