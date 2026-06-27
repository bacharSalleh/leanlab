"""Coding lab M3 — the engineer loop: implement to green + review, then merge.

Realizes build-task/implement-to-green. Fake dev (writes files + returns review verdicts),
real gate (pytest), real git (tmp).
"""

import contextlib
import subprocess
import sys
from pathlib import Path

from leanlab.core.coding.engineer import build_task
from leanlab.core.coding.spec import _create_worktree
from leanlab.core.agents.port import AgentResult

PYTEST = f"{sys.executable} -m pytest -q"
ACC_TEST = "from pathlib import Path\ndef test_impl():\n    assert Path('impl.py').exists()\n"


class FakeDev:
    """run_plain = the engineer editing files; run_structured = the reviewer's verdict."""

    def __init__(self, wt, impls, reviews):
        self.wt = Path(wt)
        self.impls = list(impls)
        self.reviews = list(reviews)

    def run_plain(self, _prompt):
        self.impls.pop(0)(self.wt)

    def run_structured(self, _prompt, _keys, session=None):
        return AgentResult(data=self.reviews.pop(0), session_id="s")


class FakeUI:
    @contextlib.contextmanager
    def status(self, _m):
        yield

    def attempt(self, *_a): pass
    def gate(self, _r): pass
    def note(self, _m): pass
    def error(self, _m): pass
    def success(self, *_a): pass


def _spec_wt(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()

    def g(*a):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "tester")
    (repo / "README.md").write_text("hi")
    g("add", "-A")
    g("commit", "-q", "-m", "init")

    wt, _branch = _create_worktree(repo, "demo")
    (wt / "SPEC.md").write_text("# Spec\n\nmake impl.py exist")
    (wt / "tests").mkdir(exist_ok=True)
    t = wt / "tests" / "test_acc.py"
    t.write_text(ACC_TEST)
    t.chmod(0o444)                      # locked acceptance test
    return repo, wt


def _write_impl(w):
    (w / "impl.py").write_text("VALUE = 1\n")


def _noop(_w):
    pass


def test_builds_and_merges(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    dev = FakeDev(wt, [_write_impl], [{"approved": True, "feedback": ""}])
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=3, playbook=False)
    assert res["merged"] is True and res["attempts"] == 1
    assert (repo / "impl.py").exists()             # merged into the main worktree


def test_gate_fail_then_pass(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    dev = FakeDev(wt, [_noop, _write_impl], [{"approved": True, "feedback": ""}])
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=3, playbook=False)
    assert res["merged"] is True and res["attempts"] == 2


def test_review_reject_then_approve(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    dev = FakeDev(wt, [_write_impl, _write_impl],
                  [{"approved": False, "feedback": "rename it"}, {"approved": True, "feedback": ""}])
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=3, playbook=False)
    assert res["merged"] is True and res["attempts"] == 2


def test_gives_up_after_max_attempts(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    dev = FakeDev(wt, [_noop, _noop], [])          # never produces a passing impl
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=2, playbook=False)
    assert res["merged"] is False


import hashlib as _hl
import json as _json


def _write_lock(repo, content="from pathlib import Path\ndef test_impl():\n    assert Path('impl.py').exists()\n"):
    locks = repo / ".leanlab" / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "demo.json").write_text(_json.dumps({"tests": [
        {"path": "tests/test_acc.py", "content": content,
         "sha256": _hl.sha256(content.encode()).hexdigest()}]}))


def _weaken_test(w):
    t = w / "tests" / "test_acc.py"
    if t.exists():
        t.chmod(0o644)
    t.write_text("def test_impl():\n    assert True\n")


def test_pristine_restore_defeats_weakened_test(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    _write_lock(repo)
    dev = FakeDev(wt, [_weaken_test, _weaken_test],   # weaken the test, never write impl.py
                  [{"approved": True, "score": 100, "feedback": ""}] * 2)
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=2, playbook=False)
    assert res["merged"] is False                    # restore runs the REAL test, which fails (no impl)


def test_touching_locked_tests_is_rejected_even_when_correct(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    _write_lock(repo)

    def cheat_but_correct(w):
        _weaken_test(w)
        (w / "impl.py").write_text("x = 1\n")        # satisfies the real test too

    dev = FakeDev(wt, [cheat_but_correct, cheat_but_correct],
                  [{"approved": True, "score": 100, "feedback": ""}] * 2)
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=2, playbook=False)
    assert res["merged"] is False                    # gate passes on restored test, but touching → rejected


def test_clean_build_with_lock_merges(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    _write_lock(repo)                                # lock present; engineer never touches the test
    dev = FakeDev(wt, [_write_impl], [{"approved": True, "score": 100, "feedback": ""}])
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=2, playbook=False)
    assert res["merged"] is True


def test_quality_threshold_blocks_then_passes(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    dev = FakeDev(wt, [_write_impl, _write_impl],
                  [{"approved": True, "score": 40, "feedback": "too messy"},
                   {"approved": True, "score": 90, "feedback": ""}])
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=3,
                     playbook=False, min_quality=70)
    assert res["merged"] is True and res["attempts"] == 2 and res["quality"] == 90


def test_deleting_a_locked_test_is_restored(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    _write_lock(repo)

    def delete_locked(w):                          # delete the acceptance test (no impl)
        t = w / "tests" / "test_acc.py"
        if t.exists():
            t.chmod(0o644)
            t.unlink()

    dev = FakeDev(wt, [delete_locked, delete_locked],
                  [{"approved": True, "score": 100, "feedback": ""}] * 2)
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}], max_attempts=2, playbook=False)
    assert res["merged"] is False                  # restored test runs and fails (no impl)


def test_persona_resolver():
    from leanlab.core.coding.personas import PERSONAS, spec_text
    assert PERSONAS["coding"]["engineer"] == "engineer.md"
    assert PERSONAS["coding"]["reviewer"] == "reviewer.md"
    assert PERSONAS["metric"]["worker"] == "CLAUDE.md"
    assert "Engineer" in spec_text("engineer", "coding")
    assert "Reviewer" in spec_text("reviewer", "coding")


def test_isolation_passes_self_contained(tmp_path):
    from leanlab.core.coding import engineer
    (tmp_path / "test_acc.py").write_text("def test_x():\n    assert 1 + 1 == 2\n")
    ok, _ = engineer.Engineer._isolated_acceptance(
        tmp_path, {"tests": [{"path": "test_acc.py"}]}, f"{sys.executable} -m pytest --noconftest -q")
    assert ok is True


def test_isolation_catches_conftest_dependence(tmp_path):
    from leanlab.core.coding import engineer
    # passes normally (conftest provides the fixture), but fails with conftest disabled
    (tmp_path / "test_acc.py").write_text("def test_x(secret):\n    assert secret == 42\n")
    (tmp_path / "conftest.py").write_text("import pytest\n@pytest.fixture\ndef secret():\n    return 42\n")
    ok, _ = engineer.Engineer._isolated_acceptance(
        tmp_path, {"tests": [{"path": "test_acc.py"}]}, f"{sys.executable} -m pytest --noconftest -q")
    assert ok is False


def test_isolation_rejects_when_no_tests_collected(tmp_path):
    from leanlab.core.coding import engineer
    # The acceptance file collects zero tests (exit 5) — can't prove honesty, so reject.
    (tmp_path / "test_acc.py").write_text("x = 1  # no test functions here\n")
    ok, _ = engineer.Engineer._isolated_acceptance(
        tmp_path, {"tests": [{"path": "test_acc.py"}]}, f"{sys.executable} -m pytest --noconftest -q")
    assert ok is False


def test_clip_diff_marks_truncation():
    from leanlab.core.coding.engineer import ReviewPanel
    assert ReviewPanel._clip_diff("abc") == "abc"          # short diffs untouched
    out = ReviewPanel._clip_diff("x" * (ReviewPanel.DIFF_LIMIT + 500))
    assert "truncated" in out and "do NOT approve" in out
    assert len(out) < ReviewPanel.DIFF_LIMIT + 500         # the tail was dropped


class PanelRunner:
    """run_structured pops the next canned verdict — one per reviewer in the panel."""

    def __init__(self, reviews):
        self.reviews = list(reviews)

    def run_structured(self, *_a, **_k):
        return AgentResult(data=self.reviews.pop(0), session_id="s")


def test_panel_rejects_if_any_reviewer_rejects():
    from leanlab.core.coding.engineer import ReviewPanel
    r = PanelRunner([{"approved": True, "score": 90, "feedback": ""},
                     {"approved": False, "score": 40, "feedback": "SQL injection in query()"}])
    approved, score, fb, verdicts = ReviewPanel(r, "coding", 2).review("spec", "diff")
    assert approved is False
    assert score == 40                                          # harshest score governs
    assert "SQL injection" in fb and "[spec-conformance]" in fb  # blocker labelled by its lens
    assert len(verdicts) == 2


def test_panel_approves_only_when_all_approve():
    from leanlab.core.coding.engineer import ReviewPanel
    r = PanelRunner([{"approved": True, "score": 90, "feedback": ""},
                     {"approved": True, "score": 80, "feedback": ""}])
    approved, score, fb, _v = ReviewPanel(r, "coding", 2).review("spec", "diff")
    assert approved is True and score == 80 and fb == ""


def test_lenses_distinct_then_general():
    from leanlab.core.coding.engineer import ReviewPanel
    assert ReviewPanel(None, "coding", 1)._lenses() == [None]   # single = general reviewer
    names = [lens["name"] for lens in ReviewPanel(None, "coding", 3)._lenses()]
    assert names == ["correctness", "spec-conformance", "security"]


def test_panel_quorum_blocks_merge(tmp_path):
    repo, wt = _spec_wt(tmp_path)
    # gate passes, but one of two reviewers rejects → not merged
    dev = FakeDev(wt, [_write_impl],
                  [{"approved": True, "score": 95, "feedback": ""},
                   {"approved": False, "score": 30, "feedback": "missing empty-input case"}])
    res = build_task(repo, "demo", runner=dev, ui=FakeUI(),
                     gate_cmds=[{"name": "tests", "cmd": PYTEST}],
                     max_attempts=1, playbook=False, reviewers=2)
    assert res["merged"] is False
