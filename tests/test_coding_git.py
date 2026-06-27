"""Git adapter — worktree / branch / merge plumbing for coding tasks."""

import subprocess

from leanlab.core.coding.git import Git


def _repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@e.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    (r / "README").write_text("x")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "init"], check=True, capture_output=True)
    return r


def test_is_repo(tmp_path):
    git = Git()
    assert git.is_repo(_repo(tmp_path)) is True
    assert git.is_repo(tmp_path / "nope") is False


def test_create_worktree_and_merge(tmp_path):
    git = Git()
    r = _repo(tmp_path)
    wt, branch = git.create_worktree(r, "demo")
    assert wt.is_dir() and branch == "leanlab/demo"
    (wt / "impl.py").write_text("VALUE = 1\n")
    ok, err = git.merge(r, wt, branch, "demo")
    assert ok is True and err == ""
    assert (r / "impl.py").exists()                      # merged into the main worktree


def test_merge_with_no_changes_is_not_success(tmp_path):
    # An engineer that changed nothing must NOT be reported as a successful merge.
    git = Git()
    r = _repo(tmp_path)
    wt, branch = git.create_worktree(r, "empty")         # branch has no commits over main
    ok, err = git.merge(r, wt, branch, "empty")
    assert ok is False and "nothing to merge" in err
