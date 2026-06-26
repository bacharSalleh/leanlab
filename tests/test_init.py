"""Interactive init — Claude drafts the task + evaluator, operator approves in a loop.

Realizes init-lab/draft-task-and-objective and init-lab/approve-eval-loop.
Uses a fake transport + a fake UI — no real Claude, no real terminal.
"""

import contextlib
import json

from leanlab.core import init
from leanlab.core.agents import StructuredRunner
from leanlab.core.agents.port import AgentTransport


class FakeTransport(AgentTransport):
    """Returns canned replies in order; records every prompt it was sent."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts = []

    def send(self, prompt, *, session=None):
        self.prompts.append(prompt)
        return "sess-1", self._replies.pop(0)


class FakeUI:
    """Scripted UI: returns the next decision on each decide() call; everything else is a no-op."""

    def __init__(self, decisions):
        self.decisions = list(decisions)

    @contextlib.contextmanager
    def status(self, _message):
        yield

    def note(self, _m): pass
    def error(self, _m): pass
    def objective(self, _o): pass
    def proposal(self, _summary): pass
    def success(self, _lab, _name): pass

    def decide(self, _evaluation_py):
        return self.decisions.pop(0)


DRAFT = json.dumps({"task_md": "# Task\n\nPredict the thing.",
                    "objective": {"metric": "rmse", "direction": "min"}})


def _prop(summary="Hold out 20%, score RMSE."):
    return json.dumps({"summary": summary,
                       "evaluation_py": "print('{\"rmse\": 0.1}')\n",
                       "validate_py": "print('VALID')\n"})


def test_draft_writes_task_and_objective(tmp_path):
    lab = tmp_path / ".leanlab" / "demo"
    init.run_init(lab, "demo", "predict house prices",
                  runner=StructuredRunner(FakeTransport([DRAFT, _prop()])),
                  ui=FakeUI([("approve", None)]), verify=False)
    assert (lab / "task.md").read_text().startswith("# Task")
    assert json.loads((lab / "lab.json").read_text())["objective"] == {"metric": "rmse", "direction": "min"}


def test_approve_writes_evaluator(tmp_path):
    lab = tmp_path / ".leanlab" / "demo"
    init.run_init(lab, "demo", "predict",
                  runner=StructuredRunner(FakeTransport([DRAFT, _prop()])),
                  ui=FakeUI([("approve", None)]), verify=False)
    assert "rmse" in (lab / "evaluation.py").read_text()
    assert "VALID" in (lab / "validate.py").read_text()


def test_feedback_then_approve_loops(tmp_path):
    lab = tmp_path / ".leanlab" / "demo"
    t = FakeTransport([DRAFT, _prop("v1"), _prop("v2")])
    init.run_init(lab, "demo", "predict", runner=StructuredRunner(t),
                  ui=FakeUI([("feedback", "use a proper train/test split"), ("approve", None)]), verify=False)
    assert (lab / "evaluation.py").exists()
    assert len(t.prompts) == 3                       # draft + 2 proposals
    assert "use a proper train/test split" in t.prompts[2]   # feedback fed into the re-propose


def test_cancel_writes_no_evaluator(tmp_path):
    lab = tmp_path / ".leanlab" / "demo"
    init.run_init(lab, "demo", "predict",
                  runner=StructuredRunner(FakeTransport([DRAFT, _prop()])),
                  ui=FakeUI([("cancel", None)]), verify=False)
    assert (lab / "task.md").exists()                # draft is kept
    assert not (lab / "evaluation.py").exists()      # but nothing written on cancel


def test_scaffold_creates_skeleton_without_specs(tmp_path):
    lab = tmp_path / ".leanlab" / "demo"
    init.scaffold(lab, "demo")
    for f in ("lab.json", "results.jsonl", "Director_Notes.md", "Critic_Feedback.md"):
        assert (lab / f).exists(), f
    assert (lab / "experiments").is_dir()
    for spec in ("CLAUDE.md", "director.md", "critic.md"):
        assert not (lab / spec).exists(), spec
