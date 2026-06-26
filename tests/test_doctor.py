"""Doctor preflight — catches lab wiring mismatches cheaply (no real run)."""

import contextlib
import json
import sys
import textwrap

from leanlab.core import doctor

# A correct evaluator: parses --experiment, emits JSON with the objective key.
GOOD_EVAL = textwrap.dedent('''
    import argparse, json, os, sys
    p = argparse.ArgumentParser(); p.add_argument("--experiment", required=True)
    a = p.parse_args()
    if not os.path.exists(a.experiment):
        print(json.dumps({"score": 0.0, "ok": False, "error": "file not found"})); sys.exit(0)
    print(json.dumps({"score": 1.0, "ok": True}))
''')

# Wrong arg parsing: reads a positional arg while the command passes --experiment.
BAD_ARG_EVAL = textwrap.dedent('''
    import json, os, sys
    f = sys.argv[1]
    print(json.dumps({"score": 0.0, "ok": False, "error": "file not found: " + f}))
''')


def _mklab(tmp_path, eval_src, *, metric="score"):
    lab = tmp_path / ".leanlab" / "demo"
    (lab / "experiments").mkdir(parents=True)
    (lab / "evaluation.py").write_text(eval_src)
    (lab / "validate.py").write_text(GOOD_EVAL)
    (lab / "task.md").write_text("# task")
    (lab / "Director_Notes.md").write_text("x")
    (lab / "Critic_Feedback.md").write_text("x")
    (lab / "lab.json").write_text(json.dumps({
        "name": "demo", "objective": {"metric": metric, "direction": "max"},
        "experiments_dir": "experiments", "results_file": "results.jsonl",
        "eval_cmd": f"{sys.executable} evaluation.py --experiment {{file}}",
        "validate_cmd": f"{sys.executable} validate.py --experiment {{file}}",
    }))
    return lab


def _status(checks, name):
    return next((c.status for c in checks if c.name == name), None)


def test_good_lab_passes_wiring(tmp_path):
    checks = doctor.check_lab(_mklab(tmp_path, GOOD_EVAL))
    assert _status(checks, "eval args") == "ok"
    assert _status(checks, "eval metric") == "ok"
    assert _status(checks, "validate args") == "ok"
    assert _status(checks, "agent prompts") == "ok"
    assert doctor.ok([c for c in checks if c.name != "claude CLI"])   # claude may be absent in CI


def test_arg_mismatch_detected(tmp_path):
    checks = doctor.check_lab(_mklab(tmp_path, BAD_ARG_EVAL))
    assert _status(checks, "eval args") == "fail"


def test_metric_mismatch_detected(tmp_path):
    checks = doctor.check_lab(_mklab(tmp_path, GOOD_EVAL, metric="FPS"))  # prints "score", not "FPS"
    assert _status(checks, "eval metric") == "fail"


def test_missing_lab_json(tmp_path):
    checks = doctor.check_lab(tmp_path / "nope")
    assert checks[0].status == "fail" and checks[0].name == "lab.json"


def test_missing_files_flagged(tmp_path):
    lab = tmp_path / ".leanlab" / "demo"
    lab.mkdir(parents=True)
    lab.joinpath("lab.json").write_text(json.dumps({
        "objective": {"metric": "score", "direction": "max"}, "experiments_dir": "experiments",
        "results_file": "r.jsonl", "eval_cmd": "x {file}", "validate_cmd": "x {file}"}))
    checks = doctor.check_lab(lab)
    assert _status(checks, "evaluation.py") == "fail"
    assert _status(checks, "experiments/") == "fail"


class _FakeUI:
    def report(self, _checks): pass
    def note(self, _m): pass

    @contextlib.contextmanager
    def status(self, _m):
        yield


class _FixingRunner:
    """Simulates a Claude fix agent: on run_plain it edits lab.json to fix the metric."""

    def __init__(self, lab):
        self.lab = lab
        self.calls = 0

    def run_plain(self, _prompt):
        self.calls += 1
        cfg = json.loads((self.lab / "lab.json").read_text())
        cfg["objective"]["metric"] = "score"
        (self.lab / "lab.json").write_text(json.dumps(cfg))


def test_fix_lab_resolves_metric_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("leanlab.core.doctor.shutil.which", lambda *_: "/usr/bin/claude")
    lab = _mklab(tmp_path, GOOD_EVAL, metric="FPS")     # broken: eval prints "score", not "FPS"
    runner = _FixingRunner(lab)
    assert doctor.fix_lab(lab, runner=runner, ui=_FakeUI()) is True
    assert runner.calls == 1                            # one fix round was enough


def test_fix_lab_true_when_already_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr("leanlab.core.doctor.shutil.which", lambda *_: "/usr/bin/claude")
    lab = _mklab(tmp_path, GOOD_EVAL)

    class _NoRunner:
        def run_plain(self, _p):
            raise AssertionError("must not try to fix a healthy lab")

    assert doctor.fix_lab(lab, runner=_NoRunner(), ui=_FakeUI()) is True
