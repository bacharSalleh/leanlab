"""Fix-on-error — the judge fails, the Worker is resumed to fix, else logged invalid.

Realizes run-experiments/fix-on-error.
"""

from leanlab.core import loop
from leanlab.core.agents import StructuredRunner
from leanlab.core.agents.port import AgentTransport


class FakeTransport(AgentTransport):
    """A worker that always replies with a valid (already-fixed) result."""

    def __init__(self):
        self.sessions = []

    def send(self, prompt, *, session=None):
        self.sessions.append(session)
        return "sess-1", '{"experiment_file": "experiments/x.py", "valid": true}'


def _lab(tmp_path):
    (tmp_path / "experiments").mkdir()
    exp = tmp_path / "experiments" / "x.py"
    exp.write_text('"""an idea."""\n')
    (tmp_path / "results.jsonl").write_text("")
    cfg = {"objective": {"metric": "rmse", "direction": "min"},
           "results_file": "results.jsonl", "experiments_dir": "experiments",
           "max_fix_calls": 3, "eval_cmd": "x", "validate_cmd": "x"}
    return cfg, exp


def test_fix_retries_then_logs(tmp_path, monkeypatch):
    cfg, exp = _lab(tmp_path)
    calls = {"n": 0}

    def fake_eval(self, rel):
        calls["n"] += 1
        if calls["n"] == 1:
            return None, "boom"          # judge errors first
        return {"rmse": 0.4}, "ok"       # then succeeds after the fix

    monkeypatch.setattr(loop.Evaluator, "evaluate", fake_eval)
    runner = StructuredRunner(FakeTransport())
    loop.score_with_fixes(tmp_path, cfg, "t", exp, "sess-1", runner)

    rows = loop.read_results(tmp_path, cfg)
    assert len(rows) == 1 and rows[0]["rmse"] == 0.4
    assert calls["n"] == 2               # failed once, retried once, then logged


def test_fix_exhausts_marks_invalid(tmp_path, monkeypatch):
    cfg, exp = _lab(tmp_path)
    monkeypatch.setattr(loop.Evaluator, "evaluate", lambda self, rel: (None, "boom"))  # always fails
    runner = StructuredRunner(FakeTransport())
    loop.score_with_fixes(tmp_path, cfg, "t", exp, "sess-1", runner)

    rows = loop.read_results(tmp_path, cfg)
    assert len(rows) == 1
    assert rows[0]["rmse"] is None
    assert "invalid" in rows[0]["notes"]
