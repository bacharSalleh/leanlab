#!/usr/bin/env python3
"""Record CONCRETE run traces for every use-case slice.

A sequence diagram is the abstract flow; a concrete trace is one real run of a
slice with the actual values at each step (archik shows it on the canvas as a
dataflow timeline). archik ships a JS recorder — leanlab is Python, so this drives
each slice through its real code path with light fakes and captures what flowed.

    uv run python scripts/record_trace.py

Writes .archik/traces/<usecase>.<slice>.archik.trace.json for each slice, then validates.
build-task is bound to its seq; the rest are standalone traces.
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

from leanlab.core import doctor, init, loop
from leanlab.core.agents import StructuredRunner
from leanlab.core.agents.port import AgentResult, AgentTransport
from leanlab.core.coding import board
from leanlab.core.coding.engineer import build_task
from leanlab.core.coding.spec import _create_worktree, spec_task

ROOT = Path(__file__).resolve().parent.parent
TRACES = ROOT / ".archik" / "traces"
PY = sys.executable


# --- helpers ---------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc).isoformat()


def write_trace(use_case, slice_id, steps, seq_file=None):
    doc = {"version": "1.0", "useCase": use_case, "slice": slice_id, "recordedAt": _now()}
    if seq_file:
        doc["seqFile"] = seq_file
    doc["steps"] = steps
    TRACES.mkdir(parents=True, exist_ok=True)
    out = TRACES / f"{use_case}.{slice_id}.archik.trace.json"
    out.write_text(json.dumps(doc, indent=2) + "\n")
    return f"{use_case}/{slice_id} ({len(steps)} steps)"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "leanlab")
    (path / "README.md").write_text("demo\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")


class FakeTransport(AgentTransport):
    def __init__(self, replies):
        self._replies = list(replies)

    def send(self, prompt, *, session=None):
        return "sess-1", self._replies.pop(0)


class QuietUI:
    @contextlib.contextmanager
    def status(self, _m):
        yield

    def __getattr__(self, _n):
        return lambda *a, **k: None


# --- build-task (bound to its seq) -----------------------------------------
def rec_build_task():
    task, slug = "add a /health endpoint returning 200", "add-health-endpoint-returning-200"
    acc = "from pathlib import Path\n\n\ndef test_impl():\n    assert Path('impl.py').exists()\n"

    class Dev:
        def __init__(self, wt):
            self.wt = wt

        def run_plain(self, _p):
            (self.wt / "impl.py").write_text("def health():\n    return 200\n")

        def run_structured(self, _p, _k, session=None):
            return AgentResult(data={"approved": True, "score": 95, "feedback": "clean"}, session_id="s")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        git_repo(repo)
        wt, _b = _create_worktree(repo, slug)
        (wt / "SPEC.md").write_text(f"# Spec\n\n{task}\n")
        (wt / "tests").mkdir(exist_ok=True)
        (wt / "tests" / "test_acc.py").write_text(acc)
        (wt / "tests" / "test_acc.py").chmod(0o444)
        locks = repo / ".leanlab" / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / f"{slug}.json").write_text(json.dumps({"tests": [
            {"path": "tests/test_acc.py", "content": acc, "sha256": hashlib.sha256(acc.encode()).hexdigest()}]}))
        res = build_task(repo, slug, runner=Dev(wt), ui=QuietUI(),
                         gate_cmds=[{"name": "tests", "cmd": f"{PY} -m pytest -q"}],
                         accept_cmd=f"{PY} -m pytest --noconftest -q", max_attempts=3, reviewers=1, playbook=False)
        ev = board.read_events(repo, slug)
    a = next((e for e in ev if e["event"] == "attempt"), {})
    r = next((e for e in ev if e["event"] == "review"), {})
    steps = [
        {"id": "m-build", "from": "cli", "to": "eng", "label": "build(task)",
         "data": {"in": {"task": task, "slug": slug, "reviewers": 1, "max_attempts": 3}}},
        {"id": "m-gate-ret", "from": "gate", "to": "eng", "label": "pass | fail",
         "data": {"out": {"passed": a.get("gate_passed"), "failures": a.get("failures", [])}}},
        {"id": "m-honest-ret", "from": "gate", "to": "eng", "label": "honest | tampered / gamed",
         "data": {"out": "honest (tests untouched; pass without engineer fixtures)"}},
        {"id": "m-review-ret", "from": "rev", "to": "eng", "label": "quorum: all approved | changes requested",
         "data": {"out": {"approved": r.get("approved"), "score": r.get("score")}}},
        {"id": "m-merge", "from": "eng", "to": "eng", "label": "commit + merge branch into main",
         "data": {"out": {"branch": res["branch"]}}},
        {"id": "m-done", "from": "eng", "to": "cli", "label": "merged — task complete",
         "data": {"out": {"merged": res["merged"], "attempts": res["attempts"], "quality": res["quality"]}}},
    ]
    return write_trace("build-task", "implement-to-green", steps, ".archik/build-task.archik.seq.yaml")


# --- spec-task -------------------------------------------------------------
def rec_spec_task():
    task = "add a /health endpoint returning 200"
    spec_md = "# Spec\n\nAdd a `/health` route returning HTTP 200 with body `ok`."
    test_src = "def test_health(client):\n    assert client.get('/health').status_code == 200\n"

    class R:
        def run_structured(self, _p, _k, session=None):
            return AgentResult(data={"spec_md": spec_md,
                                     "tests": [{"path": "tests/test_health.py", "content": test_src}]},
                               session_id="s")

        def run_plain(self, _p):
            pass

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        git_repo(repo)
        res = spec_task(repo, task, runner=R(), ui=QuietUI(), yes=True)
    steps = [
        {"from": "developer", "to": "spec-writer", "label": "spec(task)", "data": {"in": {"task": task}}},
        {"from": "spec-writer", "to": "claude", "label": "draft spec + acceptance tests",
         "data": {"out": {"spec_md": spec_md, "tests": res["test_paths"]}}},
        {"from": "spec-writer", "to": "acceptance-tests", "label": "write + LOCK tests",
         "data": {"out": {"locked": res["test_paths"],
                          "sha256": hashlib.sha256(test_src.encode()).hexdigest()[:12] + "…"}}},
        {"from": "spec-writer", "to": "developer", "label": "worktree ready",
         "data": {"out": {"branch": res["branch"]}}},
    ]
    return write_trace("spec-task", "draft-and-lock-acceptance", steps)


# --- init-lab (two slices from one run) ------------------------------------
def rec_init_lab():
    draft = json.dumps({"task_md": "# Task\n\nPredict California median house value.",
                        "objective": {"metric": "rmse", "direction": "min"}})
    prop = json.dumps({"summary": "Hold out 20%, fit, score RMSE on the held-out split.",
                       "evaluation_py": "print('{\"rmse\": 0.0}')\n", "validate_py": "print('VALID')\n"})
    class InitUI(QuietUI):
        def decide(self, _evaluation_py):
            return ("approve", None)

    with tempfile.TemporaryDirectory() as tmp:
        lab = Path(tmp) / ".leanlab" / "house-prices"
        init.run_init(lab, "house-prices", "predict house value",
                      runner=StructuredRunner(FakeTransport([draft, prop])), ui=InitUI(), verify=False)
        objective = json.loads((lab / "lab.json").read_text())["objective"]
        eval_py = (lab / "evaluation.py").read_text().strip()

    write_trace("init-lab", "draft-task-and-objective", [
        {"from": "developer", "to": "init-architect", "label": "init(name, description)",
         "data": {"in": {"name": "house-prices", "description": "predict house value"}}},
        {"from": "init-architect", "to": "claude", "label": "draft task.md + objective",
         "data": {"out": {"objective": objective}}},
        {"from": "init-architect", "to": "lab-scaffold", "label": "write task.md + lab.json",
         "data": {"out": {"objective": objective}}},
    ])
    return write_trace("init-lab", "approve-eval-loop", [
        {"from": "init-architect", "to": "claude", "label": "propose evaluator",
         "data": {"out": {"summary": "Hold out 20%, fit, score RMSE on the held-out split."}}},
        {"from": "developer", "to": "init-architect", "label": "review + approve",
         "data": {"in": {"decision": "approve"}}},
        {"from": "init-architect", "to": "lab-scaffold", "label": "write evaluation.py + validate.py",
         "data": {"out": {"evaluation_py": eval_py}}},
    ])


# --- run-experiments (score-and-log, rank-by-objective, fix-on-error) -------
def _metric_lab(tmp, exps):
    """A tiny real metric lab; each exp file holds 'RMSE=<v>' which the evaluator reads."""
    lab = Path(tmp) / "lab"
    (lab / "experiments").mkdir(parents=True)
    (lab / "results.jsonl").write_text("")
    (lab / "evaluation.py").write_text(
        "import sys,json\n"
        "p=sys.argv[sys.argv.index('--experiment')+1]\n"
        "v=float(open(p).read().strip().split('=')[1])\n"
        "print(json.dumps({'rmse': v}))\n")
    paths = []
    for name, v in exps:
        f = lab / "experiments" / name
        f.write_text(f"RMSE={v}\n")
        paths.append(f)
    cfg = {"objective": {"metric": "rmse", "direction": "min"},
           "results_file": "results.jsonl", "experiments_dir": "experiments", "max_fix_calls": 3,
           "eval_cmd": f"{PY} evaluation.py --experiment {{file}}", "validate_cmd": f"{PY} -c pass"}
    return lab, cfg, paths


def rec_run_score():
    with tempfile.TemporaryDirectory() as tmp:
        lab, cfg, (exp,) = _metric_lab(tmp, [("hgb_01.py", 0.42)])
        loop.score_with_fixes(lab, cfg, "hgb", exp, "sess-1", StructuredRunner(FakeTransport([])))
        row = loop.read_results(lab, cfg)[0]
    return write_trace("run-experiments", "score-and-log", [
        {"from": "loop", "to": "evaluator", "label": "run frozen evaluator on the experiment",
         "data": {"in": {"experiment": "experiments/hgb_01.py"}}},
        {"from": "evaluator", "to": "loop", "label": "metrics (one JSON line)",
         "data": {"out": {"rmse": row["rmse"]}}},
        {"from": "loop", "to": "results-store", "label": "append result row",
         "data": {"out": {"rmse": row["rmse"], "best_so_far": row["best_so_far"]}}},
    ])


def rec_run_rank():
    with tempfile.TemporaryDirectory() as tmp:
        lab, cfg, (e1, e2) = _metric_lab(tmp, [("baseline_01.py", 0.42), ("tuned_02.py", 0.30)])
        loop.score_with_fixes(lab, cfg, "baseline", e1, "s1", StructuredRunner(FakeTransport([])))
        loop.score_with_fixes(lab, cfg, "tuned", e2, "s2", StructuredRunner(FakeTransport([])))
        rows = loop.read_results(lab, cfg)
    ranked = sorted(rows, key=lambda r: r["rmse"])
    return write_trace("run-experiments", "rank-by-objective", [
        {"from": "loop", "to": "results-store", "label": "read all results",
         "data": {"out": [{"rmse": r["rmse"]} for r in rows]}},
        {"from": "loop", "to": "loop", "label": "rank by objective (min rmse)",
         "data": {"out": {"best": {"rmse": ranked[0]["rmse"]}, "objective": "min rmse"}}},
        {"from": "loop", "to": "claude", "label": "inject top-N into the next Worker prompt",
         "data": {"out": {"best_so_far": ranked[0]["rmse"]}}},
    ])


def rec_run_fix():
    with tempfile.TemporaryDirectory() as tmp:
        lab, cfg, (exp,) = _metric_lab(tmp, [("idea_01.py", 0.33)])
        calls = {"n": 0}
        orig = loop.evaluate

        def flaky(lab_dir, c, rel):
            calls["n"] += 1
            return (None, "ValueError: NaN in predictions") if calls["n"] == 1 else ({"rmse": 0.33}, "ok")

        loop.evaluate = flaky
        try:
            loop.score_with_fixes(lab, cfg, "idea", exp, "sess-1", StructuredRunner(
                FakeTransport(['{"experiment_file": "experiments/idea_01.py", "valid": true}'])))
            row = loop.read_results(lab, cfg)[0]
        finally:
            loop.evaluate = orig
    return write_trace("run-experiments", "fix-on-error", [
        {"from": "loop", "to": "evaluator", "label": "run evaluator", "status": "error",
         "data": {"in": {"experiment": "experiments/idea_01.py"}, "out": "ValueError: NaN in predictions"}},
        {"from": "loop", "to": "claude", "label": "resume the Worker session to fix the error",
         "data": {"in": {"error": "ValueError: NaN in predictions"}}},
        {"from": "loop", "to": "evaluator", "label": "re-run evaluator", "data": {"out": {"rmse": row["rmse"]}}},
        {"from": "loop", "to": "results-store", "label": "append result row",
         "data": {"out": {"rmse": row["rmse"], "fixed_after": calls["n"] - 1}}},
    ])


# --- diagnose-lab (check-wiring, fix-wiring) -------------------------------
def _doctor_lab(tmp, metric="score"):
    good = ("import argparse, json, os, sys\n"
            "p = argparse.ArgumentParser(); p.add_argument('--experiment', required=True)\n"
            "a = p.parse_args()\n"
            "print(json.dumps({'score': 1.0, 'ok': True}))\n")
    lab = Path(tmp) / ".leanlab" / "demo"
    (lab / "experiments").mkdir(parents=True)
    (lab / "evaluation.py").write_text(good)
    (lab / "validate.py").write_text(good)
    (lab / "task.md").write_text("# task")
    (lab / "Director_Notes.md").write_text("x")
    (lab / "Critic_Feedback.md").write_text("x")
    (lab / "lab.json").write_text(json.dumps({
        "name": "demo", "objective": {"metric": metric, "direction": "max"},
        "experiments_dir": "experiments", "results_file": "results.jsonl",
        "eval_cmd": f"{PY} evaluation.py --experiment {{file}}",
        "validate_cmd": f"{PY} validate.py --experiment {{file}}"}))
    return lab


def rec_diagnose_check():
    with tempfile.TemporaryDirectory() as tmp:
        checks = doctor.check_lab(_doctor_lab(tmp))
    return write_trace("diagnose-lab", "check-wiring", [
        {"from": "developer", "to": "lab-doctor", "label": "check(lab)", "data": {"in": {"lab": "demo"}}},
        {"from": "lab-doctor", "to": "lab-scaffold", "label": "probe wiring (args, metric key, files)",
         "data": {"out": {c.name: c.status for c in checks if c.name != "claude CLI"}}},
    ])


def rec_diagnose_fix():
    doctor.shutil.which = lambda *_: "/usr/bin/claude"  # pretend claude is installed

    class Fixer:
        def __init__(self, lab):
            self.lab = lab

        def run_plain(self, _p):
            cfg = json.loads((self.lab / "lab.json").read_text())
            cfg["objective"]["metric"] = "score"
            (self.lab / "lab.json").write_text(json.dumps(cfg))

    with tempfile.TemporaryDirectory() as tmp:
        lab = _doctor_lab(tmp, metric="FPS")  # broken: eval prints 'score', objective says 'FPS'
        before = next(c.status for c in doctor.check_lab(lab) if c.name == "eval metric")
        ok = doctor.fix_lab(lab, runner=Fixer(lab), ui=QuietUI())
        after = next(c.status for c in doctor.check_lab(lab) if c.name == "eval metric")
    return write_trace("diagnose-lab", "fix-wiring", [
        {"from": "lab-doctor", "to": "lab-scaffold", "label": "metric-key mismatch detected", "status": "error",
         "data": {"out": {"eval metric": before, "objective": "FPS", "evaluator prints": "score"}}},
        {"from": "lab-doctor", "to": "claude", "label": "ask Claude to repair the wiring",
         "data": {"in": {"problem": "objective metric 'FPS' not in evaluator output"}}},
        {"from": "lab-doctor", "to": "lab-scaffold", "label": "re-check after fix",
         "data": {"out": {"eval metric": after, "resolved": ok}}},
    ])


# --- watch-progress (coding-board, metric-dashboard) -----------------------
def rec_coding_board():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / ".leanlab" / "worktrees" / "add-health").mkdir(parents=True)
        (repo / ".leanlab" / "worktrees" / "add-health" / "SPEC.md").write_text("# Spec\n\nAdd /health.")
        (repo / ".leanlab" / "coding-results.jsonl").write_text(
            json.dumps({"slug": "add-health", "merged": True, "attempts": 2}) + "\n"
            + json.dumps({"slug": "fix-bug", "merged": False, "attempts": 4}) + "\n")
        st = board.coding_state(repo)
    return write_trace("watch-progress", "coding-board", [
        {"from": "developer", "to": "coding-board", "label": "open the board (GET /api/state)",
         "data": {"in": {"repo": "my-repo"}}},
        {"from": "coding-board", "to": "results-store", "label": "read worktrees + results + events",
         "data": {"out": {"tasks": [{"slug": t["slug"], "status": t["status"]} for t in st["tasks"]]}}},
        {"from": "coding-board", "to": "developer", "label": "render the board",
         "data": {"out": {"totals": st["totals"]}}},
    ])


def rec_metric_dashboard():
    with tempfile.TemporaryDirectory() as tmp:
        lab, cfg, (e1, e2) = _metric_lab(tmp, [("a_01.py", 0.42), ("b_02.py", 0.30)])
        loop.score_with_fixes(lab, cfg, "a", e1, "s1", StructuredRunner(FakeTransport([])))
        loop.score_with_fixes(lab, cfg, "b", e2, "s2", StructuredRunner(FakeTransport([])))
        rows = loop.read_results(lab, cfg)
    best = min(rows, key=lambda r: r["rmse"])
    return write_trace("watch-progress", "metric-dashboard", [
        {"from": "developer", "to": "dashboard", "label": "open the dashboard",
         "data": {"in": {"lab": "house-prices"}}},
        {"from": "dashboard", "to": "results-store", "label": "read results.jsonl",
         "data": {"out": {"experiments": len(rows)}}},
        {"from": "dashboard", "to": "developer", "label": "render stats + progress chart + table",
         "data": {"out": {"experiments": len(rows), "best_rmse": best["rmse"]}}},
    ])


RECORDERS = [
    rec_build_task, rec_spec_task, rec_init_lab,
    rec_run_score, rec_run_rank, rec_run_fix,
    rec_diagnose_check, rec_diagnose_fix,
    rec_coding_board, rec_metric_dashboard,
]


def main():
    ok, failed = [], []
    for rec in RECORDERS:
        try:
            ok.append(rec())
        except Exception as e:  # noqa: BLE001 — one slice failing shouldn't block the rest
            failed.append(f"{rec.__name__}: {type(e).__name__}: {e}")
    print(f"recorded {len(ok)} trace(s):")
    for line in ok:
        print(f"  ✓ {line}")
    for line in failed:
        print(f"  ✗ {line}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
