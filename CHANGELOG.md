# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.4] - 2026-06-27

### Changed
- Finished the OOP/DI migration: removed all module-level delegating shims
  (`spec_task`, `build_task`, `run_gate`, `coding_state`, `read_events`,
  `load_lab`, `score_with_fixes`, `check_lab`, `run_init`, `parse_session`, …).
  Tests and the trace recorder now construct the classes directly, so `cli.py`
  is the sole composition root and there is one obvious way to call each unit.
  Behaviour is unchanged. Kept genuine helpers (`make_runner` factory, `report`
  renderer, `ok`/`summarize` predicates, `clean_worktrees`, `serve_board`).

## [0.2.3] - 2026-06-27

### Changed
- Re-architected the Python codebase to OOP + dependency injection. Logic now
  lives in classes with constructor-injected collaborators (coding side:
  `EventLog`, `LockStore`, `Git`, `Transcripts`, `Gate`, `Personas`, `Playbook`,
  `TechLead`, `SpecWriter`, `Engineer`, `ReviewPanel`, `Board`; metric side:
  `Lab`, `ResultsStore`, `Evaluator`, `Prompts`, `ExperimentLoop`, `LabDoctor`,
  `LabScaffold`, `InitArchitect`, `Dashboard`). `cli.py` is the single
  composition root. Behavior is unchanged; thin module-level shims remain for
  the tests and the trace recorder.

### Fixed
- Honesty model: the isolated acceptance re-run now fails CLOSED on a timeout
  and on "no tests collected" (pytest exit 5) — previously a hung or
  uncollectable pristine run was treated as honest, letting gamed code through.
- `Git.merge` reports failure when the branch carried no changes ("Already up to
  date") instead of a false success.
- Structured-output parsing extracts NESTED JSON (spec/init replies) wrapped in
  prose or code fences via a brace-balanced, string-aware scan.
- The metric dashboard detects experiment filenames with hyphens/dots.

## [0.2.2] - 2026-06-26

### Added
- One-command release script (`scripts/release.py`) and a `ruff check` lint job in CI.

### Changed
- README is now user-facing (PyPI install + quick start for both lab types). The
  project concept, structure, two-lab mapping, and coding-lab flow moved to
  `docs/OVERVIEW.md`.

## [0.2.1] - 2026-06-26

### Fixed
- Board task list now includes completed/cleaned tasks (built from the union of
  worktrees + results + events), so merged tasks no longer vanish.
- Task slugs are readable and word-bounded (first sentence, filler dropped, cut
  on a word boundary) instead of a blind 40-character chop.

### Changed
- The board timeline is now loop-faithful: each round is one
  engineer → gate → review iteration, with an explicit loop-back and a
  partial-record flag when a merged task's events weren't fully logged.

## [0.2.0] - 2026-06-26

### Added
- React + Tailwind coding board (built into the wheel), with a full-screen
  per-task page (big timeline + agent chat).
- Adversarial reviewer panel: `leanlab build --reviewers N` runs N independent
  reviewers with distinct lenses and merges only if all approve.
- `leanlab --version`.

## [0.1.0]

### Added
- Initial release: metric labs (Worker/Director/Critic loop against a frozen
  evaluator) and coding labs (spec-writer → engineer → gate → reviewer →
  tech-lead), a live dashboard, and a Claude Code skill (`leanlab init --for-agent`).

[Unreleased]: https://github.com/bacharSalleh/leanlab/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/bacharSalleh/leanlab/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/bacharSalleh/leanlab/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/bacharSalleh/leanlab/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/bacharSalleh/leanlab/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/bacharSalleh/leanlab/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bacharSalleh/leanlab/releases/tag/v0.1.0
