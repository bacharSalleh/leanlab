#!/usr/bin/env python3
"""Record a CONCRETE run trace for the build-task happy slice.

archik's sequence diagram is the abstract flow (boxes + arrows). A concrete trace
is one real run with the actual values at each step — archik shows it on the canvas
as an expandable dataflow timeline. archik ships a JS recorder; leanlab is Python,
so this is the equivalent: it drives the slice for real (fake agent, real gate +
git) and writes the trace JSON bound to the build-task seq.

    uv run python scripts/record_trace.py

Writes .archik/traces/build-task.implement-to-green.archik.trace.json, then validates.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from leanlab.core.agents.port import AgentResult
from leanlab.core.coding import board
from leanlab.core.coding.engineer import build_task
from leanlab.core.coding.spec import _create_worktree

ROOT = Path(__file__).resolve().parent.parent
TASK = "add a /health endpoint returning 200"
SLUG = "add-health-endpoint-returning-200"
ACCEPTANCE = "from pathlib import Path\n\n\ndef test_impl():\n    assert Path('impl.py').exists()\n"


class FakeDev:
    """The engineer writes the impl; the reviewer approves — a real green run."""

    def __init__(self, wt):
        self.wt = wt

    def run_plain(self, _prompt):
        (self.wt / "impl.py").write_text("def health():\n    return 200\n")

    def run_structured(self, _prompt, _keys, session=None):
        return AgentResult(data={"approved": True, "score": 95, "feedback": "clean, well-named"},
                           session_id="s")


class QuietUI:
    @contextlib.contextmanager
    def status(self, _m):
        yield

    def __getattr__(self, _n):
        return lambda *a, **k: None


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _spec_worktree(repo):
    """Stand up a git repo with a spec'd, test-locked worktree (what `leanlab spec` produces)."""
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "leanlab")
    (repo / "README.md").write_text("demo\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    wt, _branch = _create_worktree(repo, SLUG)
    (wt / "SPEC.md").write_text(f"# Spec\n\n{TASK}\n")
    (wt / "tests").mkdir(exist_ok=True)
    test = wt / "tests" / "test_acc.py"
    test.write_text(ACCEPTANCE)
    test.chmod(0o444)
    locks = repo / ".leanlab" / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / f"{SLUG}.json").write_text(json.dumps({"tests": [
        {"path": "tests/test_acc.py", "content": ACCEPTANCE,
         "sha256": hashlib.sha256(ACCEPTANCE.encode()).hexdigest()}]}))
    return wt


def main():
    py = sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "demo-repo"
        repo.mkdir()
        _spec_worktree(repo)
        res = build_task(
            repo, SLUG, runner=FakeDev(repo / ".leanlab" / "worktrees" / SLUG), ui=QuietUI(),
            gate_cmds=[{"name": "tests", "cmd": f"{py} -m pytest -q"}],
            accept_cmd=f"{py} -m pytest --noconftest -q",
            max_attempts=3, reviewers=1, playbook=False)
        events = board.read_events(repo, SLUG)

    if not res or not res.get("merged"):
        sys.exit(f"record_trace: run did not merge — {res}")

    attempt = next((e for e in events if e["event"] == "attempt"), {})
    review = next((e for e in events if e["event"] == "review"), {})

    # Steps bound to .archik/build-task.archik.seq.yaml (ids + participants must match it).
    steps = [
        {"id": "m-build", "from": "cli", "to": "eng", "label": "build(task)",
         "data": {"in": {"task": TASK, "slug": SLUG, "reviewers": 1, "max_attempts": 3}}},
        {"id": "m-gate-ret", "from": "gate", "to": "eng", "label": "pass | fail",
         "data": {"out": {"passed": attempt.get("gate_passed"), "failures": attempt.get("failures", [])}}},
        {"id": "m-honest-ret", "from": "gate", "to": "eng", "label": "honest | tampered / gamed",
         "data": {"out": "honest (tests untouched; pass without engineer fixtures)"}},
        {"id": "m-review-ret", "from": "rev", "to": "eng", "label": "quorum: all approved | changes requested",
         "data": {"out": {"approved": review.get("approved"), "score": review.get("score"),
                          "feedback": review.get("feedback")}}},
        {"id": "m-merge", "from": "eng", "to": "eng", "label": "commit + merge branch into main",
         "data": {"out": {"branch": res["branch"]}}},
        {"id": "m-done", "from": "eng", "to": "cli", "label": "merged — task complete",
         "data": {"out": {"merged": res["merged"], "attempts": res["attempts"], "quality": res["quality"]}}},
    ]
    doc = {
        "version": "1.0",
        "useCase": "build-task",
        "slice": "implement-to-green",
        "seqFile": ".archik/build-task.archik.seq.yaml",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
    }
    out = ROOT / ".archik" / "traces" / "build-task.implement-to-green.archik.trace.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"record_trace: wrote {out.relative_to(ROOT)} ({len(steps)} steps, merged in {res['attempts']} attempt)")


if __name__ == "__main__":
    main()
