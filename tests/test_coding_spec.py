"""Coding lab M1 — spec-writer drafts + locks acceptance tests in a git worktree.

Realizes spec-task/draft-and-lock-acceptance. Fake transport + fake UI, real git (tmp).
"""

import contextlib
import json
import subprocess
from pathlib import Path

from leanlab.core.coding import spec
from leanlab.core.coding.spec import SpecWriter
from leanlab.core.coding.git import Git
from leanlab.core.agents import StructuredRunner
from leanlab.core.agents.port import AgentTransport


def test_slug_is_readable_and_word_bounded():
    s = spec.SpecWriter.slug
    # drops filler, first sentence only, no mid-word cut, no trailing dash
    assert s("Add a configurable CORS allowlist. Add logging too.") == "add-configurable-cors-allowlist"
    assert s("Add a /health endpoint returning 200") == "add-health-endpoint-returning-200"
    assert not s("Add a configurable cors allowlist for the whole api gateway").endswith("-")
    assert len(s("word " * 40)) <= 50
    assert s("") == "task" and s("!!!") == "task"


def test_slug_is_stable():
    assert spec.SpecWriter.slug("Harden the histogram") == spec.SpecWriter.slug("harden the histogram!")


class FakeTransport(AgentTransport):
    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts = []

    def send(self, prompt, *, session=None):
        self.prompts.append(prompt)
        return "sess-1", self._replies.pop(0)


class FakeUI:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    @contextlib.contextmanager
    def status(self, _m):
        yield

    def note(self, _m): pass
    def error(self, _m): pass
    def spec(self, _s): pass
    def success(self, *_a): pass

    def decide(self, _test_code):
        return self.decisions.pop(0)


DRAFT = json.dumps({"spec_md": "# Spec\n\nGET /health returns 200.",
                    "tests": [{"path": "tests/test_health.py",
                               "content": "def test_health():\n    assert True\n"}]})
DRAFT2 = json.dumps({"spec_md": "# Spec v2\n\nGET /health -> 200; unknown -> 404.",
                     "tests": [{"path": "tests/test_health.py",
                                "content": "def test_health():\n    assert True\n"},
                               {"path": "tests/test_404.py",
                                "content": "def test_404():\n    assert True\n"}]})


def _git_repo(tmp_path):
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
    return repo


def test_spec_drafts_and_locks(tmp_path):
    repo = _git_repo(tmp_path)
    res = SpecWriter(runner=StructuredRunner(FakeTransport([DRAFT])), ui=FakeUI([("approve", None)])).spec(repo, "create a health endpoint")
    assert res is not None
    wt = Path(res["worktree"])
    assert (wt / "SPEC.md").read_text().startswith("# Spec")
    tp = wt / res["test_paths"][0]
    assert tp.exists()
    assert not (tp.stat().st_mode & 0o200)            # locked read-only
    assert (repo / ".leanlab" / "locks" / f"{wt.name}.json").exists()   # out-of-tree pristine lock
    # a dedicated branch was created
    branches = subprocess.run(["git", "-C", str(repo), "branch"], capture_output=True, text=True).stdout
    assert "leanlab/create-health-endpoint" in branches


def test_spec_feedback_loops(tmp_path):
    repo = _git_repo(tmp_path)
    t = FakeTransport([DRAFT, DRAFT2])
    SpecWriter(runner=StructuredRunner(t), ui=FakeUI([("feedback", "also test a 404 case"), ("approve", None)])).spec(repo, "health")
    assert len(t.prompts) == 2
    assert "also test a 404 case" in t.prompts[1]      # feedback fed into the revise


def test_spec_cancel_does_not_lock(tmp_path):
    repo = _git_repo(tmp_path)
    res = SpecWriter(runner=StructuredRunner(FakeTransport([DRAFT])), ui=FakeUI([("cancel", None)])).spec(repo, "health")
    assert res is None


def test_respec_same_task_does_not_crash_on_locked_tests(tmp_path):
    repo = _git_repo(tmp_path)
    args = dict(ui=FakeUI([("approve", None)]))
    SpecWriter(runner=StructuredRunner(FakeTransport([DRAFT])), **args).spec(repo, "create a health endpoint")
    # second run reuses the worktree where the tests are now locked read-only
    res = SpecWriter(runner=StructuredRunner(FakeTransport([DRAFT])), ui=FakeUI([("approve", None)])).spec(repo, "create a health endpoint")
    assert res is not None
    tp = Path(res["worktree"]) / res["test_paths"][0]
    assert not (tp.stat().st_mode & 0o200)              # re-locked after rewrite


def test_non_git_repo_aborts(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    res = SpecWriter(runner=StructuredRunner(FakeTransport([])), ui=FakeUI([])).spec(plain, "health")
    assert res is None                                  # no git → aborts, runner never used


def _commit(wt, name):
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", name], check=True, capture_output=True)


def test_clean_removes_merged_only(tmp_path):
    from leanlab.core.coding.spec import clean_worktrees
    repo = _git_repo(tmp_path)
    wta, bra = Git().create_worktree(repo, "task-a")        # merged
    (wta / "a.txt").write_text("a"); _commit(wta, "a")
    subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "-m", "m", bra], check=True, capture_output=True)
    (wta / ".leanlab-lock.json").write_text("{}")      # untracked file must not block removal
    wtb, _ = Git().create_worktree(repo, "task-b")          # unmerged commit
    (wtb / "b.txt").write_text("b"); _commit(wtb, "b")

    removed = clean_worktrees(repo)                     # bulk: merged only
    assert removed == ["task-a"]
    assert not (repo / ".leanlab" / "worktrees" / "task-a").exists()
    assert (repo / ".leanlab" / "worktrees" / "task-b").exists()


def test_clean_specific_slug_forces(tmp_path):
    from leanlab.core.coding.spec import clean_worktrees
    repo = _git_repo(tmp_path)
    wtb, _ = Git().create_worktree(repo, "task-b")
    (wtb / "b.txt").write_text("b"); _commit(wtb, "b")  # unmerged
    assert clean_worktrees(repo, "task-b") == ["task-b"]
    assert not (repo / ".leanlab" / "worktrees" / "task-b").exists()


def test_spec_yes_is_headless(tmp_path):
    repo = _git_repo(tmp_path)
    # FakeUI([]) has no scripted decisions — if decide() were called it'd IndexError.
    res = SpecWriter(runner=StructuredRunner(FakeTransport([DRAFT])), ui=FakeUI([])).spec(repo, "health", yes=True)
    assert res is not None
    assert (repo / ".leanlab" / "locks" / f"{Path(res['worktree']).name}.json").exists()
