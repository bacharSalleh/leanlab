"""The engineer loop — implement a spec'd task to a green gate + reviewer sign-off, then merge.

Realizes the build-task use case. The engineer edits the worktree; the gate checks it; on a
green gate the change is proven honest and an adversarial reviewer panel judges the diff. It
loops on gate failures / gaming / review feedback, then merges and the tech-lead refreshes the
playbook. Collaborators are injected for testing; the CLI is the composition root.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..loop import make_runner
from .events import EventLog
from .gate import Gate
from .git import Git
from .locks import LockStore
from .personas import Personas
from .playbook import Playbook, TechLead

_APPROVED = (True, "true", "yes", "True")


class ReviewPanel:
    """Adversarial review quorum: N reviewers, each a distinct lens; merge only if ALL approve.

    Score is the harshest (min); feedback aggregates every blocker, labelled by lens.
    """

    DIFF_LIMIT = 40000

    # Each panel reviewer attacks from a distinct angle — diversity catches what one lens misses.
    LENSES = [
        {"name": "correctness",
         "focus": "logic errors, off-by-one, wrong operators, integer division, edge cases, error paths"},
        {"name": "spec-conformance",
         "focus": "requirements stated in the spec that the locked tests do NOT check — find one the code gets wrong"},
        {"name": "security",
         "focus": "injection, path traversal, unsafe input handling, leaked secrets, resource exhaustion"},
        {"name": "robustness",
         "focus": "behaviour on bad/empty/huge input, concurrency, mutable shared state, failure recovery"},
    ]

    def __init__(self, runner, persona_set="coding", reviewers=1):
        self._runner = runner
        self._personas = Personas(persona_set)
        self._n = reviewers

    @staticmethod
    def _clip_diff(diff):
        if len(diff) <= ReviewPanel.DIFF_LIMIT:
            return diff
        return (diff[:ReviewPanel.DIFF_LIMIT]
                + f"\n…(diff truncated — {len(diff) - ReviewPanel.DIFF_LIMIT} more chars not shown; "
                  "do NOT approve code you could not see)")

    def _lenses(self):
        """Lenses for the panel. n<=1 → one general reviewer (no extra focus)."""
        if self._n <= 1:
            return [None]
        return [self.LENSES[i % len(self.LENSES)] for i in range(self._n)]

    def _prompt(self, spec_md, diff, lens):
        body = self._personas.text("reviewer")
        if lens:
            body += (f"\n\n## Your lens: {lens['name']}\nWeight your attack toward {lens['focus']}. "
                     "Still reject any blocking defect you find outside this lens.")
        return (body + "\n\n## Task spec\n" + spec_md
                + "\n\n## The diff to review\n```diff\n" + self._clip_diff(diff) + "\n```")

    def review(self, spec_md, diff):
        """Returns (approved, score, feedback, verdicts)."""
        verdicts = []
        for lens in self._lenses():
            res = self._runner.run_structured(self._prompt(spec_md, diff, lens), ["approved", "feedback"])
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


class Engineer:
    """Runs the build loop for a spec'd task: implement → gate → prove honest → review → merge."""

    def __init__(self, runner=None, ui=None, gate=None, tech_lead=None, git=None,
                 persona_set="coding", reviewers=1, max_attempts=5, min_quality=0,
                 playbook=True, isolate=True, accept_cmd="pytest --noconftest -q"):
        self._runner = runner
        self._ui = ui or BuildUI()
        self._gate = gate or Gate()
        self._tech_lead = tech_lead
        self._git = git or Git()
        self._persona_set = persona_set
        self._reviewers = reviewers
        self._max_attempts = max_attempts
        self._min_quality = min_quality
        self._playbook = playbook
        self._isolate = isolate
        self._accept_cmd = accept_cmd

    @staticmethod
    def _prompt(spec_md, persona_set, feedback, playbook=""):
        base = Personas(persona_set).text("engineer") + "\n\n## The task spec\n" + spec_md + "\n\n"
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

    @staticmethod
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

    def _record(self, repo, rec):
        """Append a build outcome so `leanlab board` can show it."""
        p = Path(repo) / ".leanlab" / "coding-results.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {**rec, "ts": datetime.now(timezone.utc).isoformat()}
        with p.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def build(self, repo, slug):
        """Run the engineer loop on a spec'd task. Returns a result dict or None."""
        repo = Path(repo).resolve()
        ui = self._ui
        wt = repo / ".leanlab" / "worktrees" / slug
        if not wt.is_dir():
            ui.error(f"no worktree at {wt} — run `leanlab spec` first.")
            return None
        branch = f"leanlab/{slug}"
        spec_md = (wt / "SPEC.md").read_text() if (wt / "SPEC.md").exists() else ""
        pb = Playbook(repo).read()
        locks, events = LockStore(repo), EventLog(repo)
        lock = locks.load(slug)
        runner = self._runner or make_runner(wt)
        tech_lead = self._tech_lead or TechLead(ui=ui, persona_set=self._persona_set)

        feedback = None
        for attempt in range(1, self._max_attempts + 1):
            ui.attempt(attempt, self._max_attempts)
            with ui.status("Engineer is implementing the change…"):
                runner.run_plain(self._prompt(spec_md, self._persona_set, feedback, pb))

            tampered = lock is not None and not locks.is_pristine(slug, wt)
            if lock is not None:
                locks.restore(slug, wt)          # the gate ALWAYS runs the pristine acceptance tests

            result = self._gate.run(wt)
            ui.gate(result)
            events.log(slug, {"event": "attempt", "n": attempt, "gate_passed": result.passed,
                              "failures": [c.name for c in result.failures()]})
            if not result.passed:
                feedback = "The gate failed:\n" + "\n".join(
                    f"[{c.name}]\n{c.output[-800:]}" for c in result.failures())
                continue

            if tampered:
                ui.error("⚠ locked acceptance tests were modified — restored; rejecting this attempt.")
                events.log(slug, {"event": "tamper", "n": attempt})
                feedback = ("You modified the locked acceptance tests (they were restored). They are "
                            "FROZEN — solve the task without touching them.")
                continue

            if lock is not None and self._isolate:
                ok_iso, _iso = self._isolated_acceptance(wt, lock, self._accept_cmd)
                if not ok_iso:
                    ui.error("⚠ acceptance tests fail without the engineer's fixtures — gamed.")
                    events.log(slug, {"event": "isolation", "n": attempt})
                    feedback = ("Your change passes only with extra fixtures/conftest. The acceptance "
                                "tests must pass on their own — implement the real behaviour.")
                    continue

            self._git.stage(wt)
            diff = self._git.run(wt, "diff", "--cached").stdout
            panel = ReviewPanel(runner, self._persona_set, self._reviewers)
            msg = ("Reviewer is checking the diff…" if self._reviewers <= 1
                   else f"{self._reviewers} reviewers are attacking the diff…")
            with ui.status(msg):
                approved, score, review_fb, verdicts = panel.review(spec_md, diff)
            events.log(slug, {"event": "review", "n": attempt, "approved": bool(approved),
                              "score": score, "feedback": review_fb[:200],
                              "reviewers": [{"lens": v["lens"], "approved": v["approved"],
                                             "score": v["score"]} for v in verdicts]})
            if approved and score >= self._min_quality:
                ok, err = self._git.merge(repo, wt, branch, slug)
                if not ok:
                    ui.error("merge failed (resolve by hand): " + err)
                events.log(slug, {"event": "merged", "branch": branch, "merged": ok})
                if ok:
                    ui.success(branch, attempt)
                    if self._playbook:
                        tech_lead.refresh(repo, slug)   # the tech-lead refreshes the PLAYBOOK
                self._record(repo, {"slug": slug, "branch": branch, "attempts": attempt,
                                    "merged": ok, "quality": score})
                return {"branch": branch, "attempts": attempt, "merged": ok, "quality": score}
            if approved:                                # passed review but below the quality bar
                feedback = (f"Quality {score:.0f} is below the required {self._min_quality:.0f} — improve it. "
                            + review_fb)
            else:
                feedback = "The reviewer(s) requested changes:\n" + (review_fb or "(no feedback)")

        ui.error(f"Gave up after {self._max_attempts} attempts — not merged.")
        events.log(slug, {"event": "gaveup", "attempts": self._max_attempts})
        self._record(repo, {"slug": slug, "branch": branch, "attempts": self._max_attempts, "merged": False})
        return {"branch": branch, "attempts": self._max_attempts, "merged": False}


def build_task(repo, slug, *, runner=None, ui=None, gate_cmds=None,
               persona_set="coding", max_attempts=5, playbook=True, min_quality=0,
               isolate=True, accept_cmd="pytest --noconftest -q", reviewers=1):
    eng = Engineer(runner=runner, ui=ui, gate=Gate(gate_cmds), persona_set=persona_set,
                   reviewers=reviewers, max_attempts=max_attempts, min_quality=min_quality,
                   playbook=playbook, isolate=isolate, accept_cmd=accept_cmd)
    return eng.build(repo, slug)


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
