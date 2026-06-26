"""Coding lab M4 — the PLAYBOOK: engineer reads it, tech-lead refreshes it after merge."""

import contextlib
from pathlib import Path

from leanlab.core.coding import playbook
from leanlab.core.coding.engineer import _engineer_prompt


class FakeUI:
    @contextlib.contextmanager
    def status(self, _m):
        yield


def test_engineer_prompt_includes_playbook():
    p = _engineer_prompt("# spec", "coding", None, "ALWAYS use repository.py for DB access")
    assert "ALWAYS use repository.py" in p
    assert "Project playbook" in p


def test_engineer_prompt_without_playbook():
    assert "Project playbook" not in _engineer_prompt("# spec", "coding", None, "")


def test_read_playbook_missing_then_present(tmp_path):
    assert playbook.read_playbook(tmp_path) == ""
    pb = playbook.playbook_path(tmp_path)
    pb.parent.mkdir(parents=True)
    pb.write_text("hello")
    assert playbook.read_playbook(tmp_path) == "hello"


class FakeTechLead:
    def __init__(self, repo):
        self.repo = Path(repo)
        self.called = False

    def run_plain(self, _prompt):
        self.called = True
        pb = playbook.playbook_path(self.repo)
        pb.parent.mkdir(parents=True, exist_ok=True)
        pb.write_text("# Playbook\n\n- convention X")


def test_update_playbook_writes_file(tmp_path):
    tl = FakeTechLead(tmp_path)
    playbook.update_playbook(tmp_path, runner=tl, ui=FakeUI())
    assert tl.called
    assert "convention X" in playbook.read_playbook(tmp_path)


def test_update_playbook_with_slug_logs_event(tmp_path):
    # the tech-lead's refresh shows on the task timeline as its step in the loop
    from leanlab.core.coding import board
    playbook.update_playbook(tmp_path, slug="demo", runner=FakeTechLead(tmp_path), ui=FakeUI())
    assert [e["event"] for e in board.read_events(tmp_path, "demo")] == ["playbook"]


def test_update_playbook_without_slug_logs_nothing(tmp_path):
    from leanlab.core.coding import board
    playbook.update_playbook(tmp_path, runner=FakeTechLead(tmp_path), ui=FakeUI())
    assert board.read_events(tmp_path, "demo") == []
