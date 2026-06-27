"""The engineer loop — implement a spec'd task to a green gate + reviewer sign-off, then merge.

Realizes the build-task use case. The engineer edits the worktree; the gate checks it; on a
green gate the reviewer judges the diff. It loops on gate failures / review feedback, then
commits and merges the branch into main. `runner` / `ui` are injected for testing.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..loop import make_runner
from .board import log_event
from .gate import run_gate
from .locks import LockStore
from .personas import spec_text
from .playbook import read_playbook, update_playbook

_APPROVED = (True, "true", "yes", "True")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _record(repo, rec):
    """Append a build outcome so `leanlab board` can show it."""
    p = Path(repo) / ".leanlab" / "coding-results.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {**rec, "ts": datetime.now(timezone.utc).isoformat()}
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def _isolated_acceptance(wt, lock, accept_cmd):
    """Re-run the pristine acceptance tests with engineer conftest/fixtures DISABLED.

    If they passed the normal gate but fail here (exit 1), the pass relied on engineer-added
    test infrastructure (a conftest monkeypatch, a fixture) — i.e. gaming. Any other exit
    (can't collect / import) means we couldn't isolate cleanly, so we don't block on it.
    """
    paths = [it["path"] for it in lock.get("tests", [])]
    if not paths:
        return True, ""
    try:
        proc = subprocess.run(shlex.split(accept_cmd) + paths, cwd=Path(wt),
                              capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        return True, f"(isolation skipped: {e})"
    out = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return (proc.returncode != 1), out


def _stage(wt):
    """Stage all changes except gate caches and the lock file."""
    ep = _git(wt, "rev-parse", "--git-path", "info/exclude").stdout.strip()
    epath = Path(ep) if Path(ep).is_absolute() else Path(wt) / ep
    try:
        epath.parent.mkdir(parents=True, exist_ok=True)
        cur = epath.read_text() if epath.exists() else ""
        for pat in ("__pycache__/", ".pytest_cache/", ".leanlab-lock.json"):
            if pat not in cur:
                cur += pat + "\n"
        epath.write_text(cur)
    except Exception:  # noqa: BLE001
        pass
    _git(wt, "add", "-A")


def _engineer_prompt(spec_md, persona_set, feedback, playbook=""):
    base = spec_text("engineer", persona_set) + "\n\n## The task spec\n" + spec_md + "\n\n"
    if playbook:
        base += "## Project playbook (follow it)\n" + playbook + "\n\n"
    base += (
        "Implement the change in this worktree so the gate passes. Read the locked acceptance "
        "tests under the test directory and make them pass — do NOT modify them. Follow the "
        "repository's conventions. Edit files with your tools, then stop."
    )
    if feedback:
        base += "\n\n## Fix this (from the last attempt)\n" + feedback
    return base


_DIFF_LIMIT = 40000

# Each panel reviewer attacks from a distinct angle — diversity catches what one lens misses.
REVIEW_LENSES = [
    {"name": "correctness",
     "focus": "logic errors, off-by-one, wrong operators, integer division, edge cases, error paths"},
    {"name": "spec-conformance",
     "focus": "requirements stated in the spec that the locked tests do NOT check — find one the code gets wrong"},
    {"name": "security",
     "focus": "injection, path traversal, unsafe input handling, leaked secrets, resource exhaustion"},
    {"name": "robustness",
     "focus": "behaviour on bad/empty/huge input, concurrency, mutable shared state, failure recovery"},
]


def _clip_diff(diff):
    if len(diff) <= _DIFF_LIMIT:
        return diff
    return (diff[:_DIFF_LIMIT]
            + f"\n…(diff truncated — {len(diff) - _DIFF_LIMIT} more chars not shown; "
              "do NOT approve code you could not see)")


def _lenses_for(n):
    """Lenses for a panel of n reviewers. n<=1 → one general reviewer (no extra focus)."""
    if n <= 1:
        return [None]
    return [REVIEW_LENSES[i % len(REVIEW_LENSES)] for i in range(n)]


def _review_prompt(spec_md, diff, persona_set, lens=None):
    body = spec_text("reviewer", persona_set)
    if lens:
        body += (f"\n\n## Your lens: {lens['name']}\nWeight your attack toward {lens['focus']}. "
                 "Still reject any blocking defect you find outside this lens.")
    return (body + "\n\n## Task spec\n" + spec_md
            + "\n\n## The diff to review\n```diff\n" + _clip_diff(diff) + "\n```")


def _review_panel(runner, spec_md, diff, persona_set, lenses):
    """Adversarial quorum: run one reviewer per lens. Approved only if ALL approve; score is the
    harshest (min); feedback aggregates every blocker, labelled by lens. Returns
    (approved, score, feedback, verdicts)."""
    verdicts = []
    for lens in lenses:
        res = runner.run_structured(_review_prompt(spec_md, diff, persona_set, lens),
                                    ["approved", "feedback"])
        ok = res.ok and res.data.get("approved") in _APPROVED
        try:
            sc = float(res.data.get("score", 100)) if res.ok else 0.0
        except (TypeError, ValueError):
            sc = 0.0
        fb = str(res.data.get("feedback", "")) if res.ok else "(review call failed)"
        verdicts.append({"lens": lens["name"] if lens else "review",
                         "approved": ok, "score": sc, "feedback": fb})
    approved = bool(verdicts) and all(v["approved"] for v in verdicts)
    score = min((v["score"] for v in verdicts), default=0.0)
    feedback = "\n\n".join(f"[{v['lens']}] {v['feedback']}"
                           for v in verdicts if not v["approved"] and v["feedback"])
    return approved, score, feedback, verdicts


def build_task(repo, slug, *, runner=None, ui=None, gate_cmds=None,
               persona_set="coding", max_attempts=5, playbook=True, min_quality=0,
               isolate=True, accept_cmd="pytest --noconftest -q", reviewers=1):
    """Run the engineer loop on a spec'd task. Returns a result dict or None."""
    repo = Path(repo).resolve()
    ui = ui or BuildUI()
    wt = repo / ".leanlab" / "worktrees" / slug
    if not wt.is_dir():
        ui.error(f"no worktree at {wt} — run `leanlab spec` first.")
        return None
    branch = f"leanlab/{slug}"
    spec_md = (wt / "SPEC.md").read_text() if (wt / "SPEC.md").exists() else ""
    pb = read_playbook(repo)
    locks = LockStore(repo)
    lock = locks.load(slug)
    runner = runner or make_runner(wt)

    feedback = None
    for attempt in range(1, max_attempts + 1):
        ui.attempt(attempt, max_attempts)
        with ui.status("Engineer is implementing the change…"):
            runner.run_plain(_engineer_prompt(spec_md, persona_set, feedback, pb))

        tampered = lock is not None and not locks.is_pristine(slug, wt)
        if lock is not None:
            locks.restore(slug, wt)              # the gate ALWAYS runs the pristine acceptance tests

        result = run_gate(wt, gate_cmds)
        ui.gate(result)
        log_event(repo, slug, {"event": "attempt", "n": attempt, "gate_passed": result.passed,
                               "failures": [c.name for c in result.failures()]})
        if not result.passed:
            feedback = "The gate failed:\n" + "\n".join(
                f"[{c.name}]\n{c.output[-800:]}" for c in result.failures())
            continue

        if tampered:
            ui.error("⚠ locked acceptance tests were modified — restored; rejecting this attempt.")
            log_event(repo, slug, {"event": "tamper", "n": attempt})
            feedback = ("You modified the locked acceptance tests (they were restored). They are "
                        "FROZEN — solve the task without touching them.")
            continue

        if lock is not None and isolate:
            ok_iso, _iso = _isolated_acceptance(wt, lock, accept_cmd)
            if not ok_iso:
                ui.error("⚠ acceptance tests fail without the engineer's fixtures — gamed.")
                log_event(repo, slug, {"event": "isolation", "n": attempt})
                feedback = ("Your change passes only with extra fixtures/conftest. The acceptance "
                            "tests must pass on their own — implement the real behaviour.")
                continue

        _stage(wt)
        diff = _git(wt, "diff", "--cached").stdout
        lenses = _lenses_for(reviewers)
        msg = ("Reviewer is checking the diff…" if len(lenses) == 1
               else f"{len(lenses)} reviewers are attacking the diff…")
        with ui.status(msg):
            approved, score, review_fb, verdicts = _review_panel(
                runner, spec_md, diff, persona_set, lenses)
        log_event(repo, slug, {"event": "review", "n": attempt, "approved": bool(approved),
                               "score": score, "feedback": review_fb[:200],
                               "reviewers": [{"lens": v["lens"], "approved": v["approved"],
                                              "score": v["score"]} for v in verdicts]})
        if approved and score >= min_quality:
            merged = _merge(repo, wt, branch, slug, ui)
            log_event(repo, slug, {"event": "merged", "branch": branch, "merged": merged})
            if merged:
                ui.success(branch, attempt)
                if playbook:
                    update_playbook(repo, slug=slug, ui=ui)  # tech-lead refreshes the PLAYBOOK
            _record(repo, {"slug": slug, "branch": branch, "attempts": attempt,
                           "merged": merged, "quality": score})
            return {"branch": branch, "attempts": attempt, "merged": merged, "quality": score}
        if approved:                                    # passed review but below the quality bar
            feedback = (f"Quality {score:.0f} is below the required {min_quality:.0f} — improve it. "
                        + review_fb)
        else:
            feedback = "The reviewer(s) requested changes:\n" + (review_fb or "(no feedback)")

    ui.error(f"Gave up after {max_attempts} attempts — not merged.")
    log_event(repo, slug, {"event": "gaveup", "attempts": max_attempts})
    _record(repo, {"slug": slug, "branch": branch, "attempts": max_attempts, "merged": False})
    return {"branch": branch, "attempts": max_attempts, "merged": False}


def _merge(repo, wt, branch, slug, ui) -> bool:
    _stage(wt)
    _git(wt, "commit", "-m", f"leanlab: {slug}")
    r = _git(repo, "merge", "--no-ff", "-m", f"leanlab: merge {slug}", branch)
    if r.returncode != 0:
        ui.error("merge failed (resolve by hand): " + (r.stderr or r.stdout).strip())
        return False
    return True


class BuildUI:
    """Terminal UI for `leanlab build` — attempt rules, spinners, gate report, merge panel."""

    def __init__(self):
        from rich.console import Console
        self.console = Console()

    def attempt(self, n, total):
        self.console.rule(f"[bold cyan]Attempt {n}/{total}", style="cyan")

    def status(self, message):
        return self.console.status(f"[bold cyan]{message}", spinner="dots")

    def gate(self, result):
        from .gate import report
        report(result, self.console)

    def note(self, message):
        self.console.print(message)

    def error(self, message):
        self.console.print(f"[bold red]{message}[/bold red]")

    def success(self, branch, attempts):
        from rich.panel import Panel
        self.console.print(Panel(
            f"Merged [bold]{branch}[/bold] into main after {attempts} attempt(s).",
            title="✓ Task complete", border_style="green"))
