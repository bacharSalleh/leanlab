"""Happy path — structured output + a valid experiment scored and logged.

Realizes run-experiments/score-and-log.
"""

from pathlib import Path

from leanlab.core.loop import ExperimentLoop, Lab, ResultsStore
from leanlab.core.agents import StructuredRunner
from leanlab.core.agents.port import AgentTransport

LAB = Path(__file__).resolve().parents[1] / ".leanlab" / "house-prices"


class FakeTransport(AgentTransport):
    """Returns canned replies in order; records the prompts it was sent."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts = []

    def send(self, prompt, *, session=None):
        self.prompts.append(prompt)
        return "sess-1", self._replies.pop(0)


def test_structured_runner_parses_valid():
    t = FakeTransport(['{"experiment_file": "experiments/sample.py", "valid": true, "notes": "x"}'])
    res = StructuredRunner(t).run_structured("go", ["experiment_file"])
    assert res.ok
    assert res.data["experiment_file"] == "experiments/sample.py"
    assert res.session_id == "sess-1"


def test_structured_runner_retries_on_malformed():
    t = FakeTransport(["not json at all", '{"experiment_file": "experiments/sample.py"}'])
    res = StructuredRunner(t, max_retries=2).run_structured("go", ["experiment_file"])
    assert res.ok
    assert len(t.prompts) == 2                 # it retried once
    assert "valid JSON" in t.prompts[1]        # with a corrective re-prompt


def test_structured_runner_gives_up_after_max_retries():
    t = FakeTransport(["nope", "still nope", "nope again"])
    res = StructuredRunner(t, max_retries=2).run_structured("go", ["experiment_file"])
    assert not res.ok and res.data == {}
    assert len(t.prompts) == 3


def test_score_and_log_happy():
    lab = Lab.load(LAB)
    lab.cfg["results_file"] = "_t_happy.jsonl"      # don't touch the real book
    results = LAB / lab.cfg["results_file"]
    results.write_text("")
    try:
        exp = LAB / "experiments" / "sample.py"
        runner = StructuredRunner(FakeTransport([]))   # not used on the happy path
        ExperimentLoop(lab, runner=runner).score_with_fixes("test", exp, "sess-1")
        rows = ResultsStore(lab).read()
        assert len(rows) == 1
        assert "rmse" in rows[0]
        assert rows[0]["best_so_far"] is True
    finally:
        results.unlink(missing_ok=True)
