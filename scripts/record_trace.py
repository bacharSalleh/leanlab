#!/usr/bin/env python3
"""Record CONCRETE run traces for every use-case slice.

A sequence diagram is the abstract flow; a concrete trace is one real run of a
slice with the actual values at each step (archik shows it on the canvas as a
dataflow timeline). archik ships a JS recorder — leanlab is Python, so this drives
each slice through its real code path with light fakes and captures what flowed.

    uv run python scripts/record_trace.py

Writes .archik/traces/<usecase>.<slice>.archik.trace.json for each slice, then validates.
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from leanlab.core import doctor, loop
from leanlab.core.agents import StructuredRunner
from leanlab.core.agents.port import AgentTransport
from leanlab.core.doctor import LabDoctor
from leanlab.core.init import InitArchitect
from leanlab.core.loop import ExperimentLoop, Lab, ResultsStore

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
        InitArchitect(runner=StructuredRunner(FakeTransport([draft, prop])), ui=InitUI()).init(
            lab, "house-prices", "predict house value", verify=False)
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
        {"id": "m-init", "from": "cli", "to": "arch", "label": "init(name, description)",
         "data": {"in": {"name": "house-prices", "description": "predict house value"}}},
        {"id": "m-draft-ret", "from": "port", "to": "arch", "label": "task + objective",
         "data": {"out": {"objective": objective}}},
        {"id": "m-write-task", "from": "arch", "to": "scaffold", "label": "write task.md + lab.json (objective)",
         "data": {"out": {"objective": objective}}},
        {"id": "m-propose-ret", "from": "port", "to": "arch", "label": "evaluation proposal",
         "data": {"out": {"summary": "Hold out 20%, fit, score RMSE on the held-out split."}}},
        {"id": "m-decide", "from": "cli", "to": "arch", "label": "approve | feedback",
         "data": {"in": {"decision": "approve"}}},
        {"id": "m-write-eval", "from": "arch", "to": "scaffold", "label": "write evaluation.py + validate.py",
         "data": {"out": {"evaluation_py": eval_py}}},
        {"id": "m-done", "from": "arch", "to": "cli", "label": "lab ready — review, lock, run"},
    ], ".archik/init-lab.archik.seq.yaml")


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
        ExperimentLoop(Lab(lab, cfg), runner=StructuredRunner(FakeTransport([]))).score_with_fixes("hgb", exp, "sess-1")
        row = ResultsStore(Lab(lab, cfg)).read()[0]
    return write_trace("run-experiments", "score-and-log", [
        {"id": "m2", "from": "cli", "to": "loop", "label": "run(lab, n)", "data": {"in": {"n": 1}}},
        {"id": "m11", "from": "loop", "to": "evaluator", "label": "score(experiment_file)",
         "data": {"in": {"experiment_file": "experiments/hgb_01.py"}}},
        {"id": "m12", "from": "evaluator", "to": "loop", "label": "JSON metrics", "data": {"out": {"rmse": row["rmse"]}}},
        {"id": "m13", "from": "loop", "to": "store", "label": "append(record, best_so_far)",
         "data": {"out": {"rmse": row["rmse"], "best_so_far": row["best_so_far"]}}},
        {"id": "m15", "from": "loop", "to": "cli", "label": "done"},
    ], ".archik/run-experiments-happy.archik.seq.yaml")


def rec_run_rank():
    with tempfile.TemporaryDirectory() as tmp:
        lab, cfg, (e1, e2) = _metric_lab(tmp, [("baseline_01.py", 0.42), ("tuned_02.py", 0.30)])
        ExperimentLoop(Lab(lab, cfg), runner=StructuredRunner(FakeTransport([]))).score_with_fixes("baseline", e1, "s1")
        ExperimentLoop(Lab(lab, cfg), runner=StructuredRunner(FakeTransport([]))).score_with_fixes("tuned", e2, "s2")
        rows = ResultsStore(Lab(lab, cfg)).read()
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
        orig = loop.Evaluator.evaluate

        def flaky(self, rel):
            calls["n"] += 1
            return (None, "ValueError: NaN in predictions") if calls["n"] == 1 else ({"rmse": 0.33}, "ok")

        loop.Evaluator.evaluate = flaky
        try:
            ExperimentLoop(Lab(lab, cfg), runner=StructuredRunner(
                FakeTransport(['{"experiment_file": "experiments/idea_01.py", "valid": true}']))).score_with_fixes("idea", exp, "sess-1")
            row = ResultsStore(Lab(lab, cfg)).read()[0]
        finally:
            loop.Evaluator.evaluate = orig
    return write_trace("run-experiments", "fix-on-error", [
        {"id": "m1", "from": "loop", "to": "evaluator", "label": "score(experiment_file)", "status": "error",
         "data": {"in": {"experiment_file": "experiments/idea_01.py"}, "out": "ValueError: NaN in predictions"}},
        {"id": "m2", "from": "evaluator", "to": "loop", "label": "ERROR — no metrics", "status": "error"},
        {"id": "m3", "from": "loop", "to": "port", "label": "run(fixPrompt, schema, resume)",
         "data": {"in": {"error": "ValueError: NaN in predictions"}}},
        {"id": "m8", "from": "loop", "to": "evaluator", "label": "score(experiment_file)"},
        {"id": "m9", "from": "evaluator", "to": "loop", "label": "JSON metrics", "data": {"out": {"rmse": row["rmse"]}}},
        {"id": "m10", "from": "loop", "to": "store", "label": "append(record)",
         "data": {"out": {"rmse": row["rmse"], "fixed_after": calls["n"] - 1}}},
    ], ".archik/run-experiments-fix.archik.seq.yaml")


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
        checks = LabDoctor(_doctor_lab(tmp)).check()
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
        before = next(c.status for c in LabDoctor(lab).check() if c.name == "eval metric")
        ok = LabDoctor(lab).fix(runner=Fixer(lab), ui=QuietUI())
        after = next(c.status for c in LabDoctor(lab).check() if c.name == "eval metric")
    return write_trace("diagnose-lab", "fix-wiring", [
        {"from": "lab-doctor", "to": "lab-scaffold", "label": "metric-key mismatch detected", "status": "error",
         "data": {"out": {"eval metric": before, "objective": "FPS", "evaluator prints": "score"}}},
        {"from": "lab-doctor", "to": "claude", "label": "ask Claude to repair the wiring",
         "data": {"in": {"problem": "objective metric 'FPS' not in evaluator output"}}},
        {"from": "lab-doctor", "to": "lab-scaffold", "label": "re-check after fix",
         "data": {"out": {"eval metric": after, "resolved": ok}}},
    ])


# --- watch-progress (metric-dashboard) -------------------------------------
def rec_metric_dashboard():
    with tempfile.TemporaryDirectory() as tmp:
        lab, cfg, (e1, e2) = _metric_lab(tmp, [("a_01.py", 0.42), ("b_02.py", 0.30)])
        ExperimentLoop(Lab(lab, cfg), runner=StructuredRunner(FakeTransport([]))).score_with_fixes("a", e1, "s1")
        ExperimentLoop(Lab(lab, cfg), runner=StructuredRunner(FakeTransport([]))).score_with_fixes("b", e2, "s2")
        rows = ResultsStore(Lab(lab, cfg)).read()
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
    rec_init_lab,
    rec_run_score, rec_run_rank, rec_run_fix,
    rec_diagnose_check, rec_diagnose_fix,
    rec_metric_dashboard,
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
