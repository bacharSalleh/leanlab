"""Coding lab M4 — the PLAYBOOK: engineer reads it, tech-lead refreshes it after merge."""

import contextlib
from pathlib import Path

from leanlab.core.coding.playbook import Playbook, TechLead
from leanlab.core.coding.engineer import Engineer


class FakeUI:
    @contextlib.contextmanager
    def status(self, _m):
        yield


def test_engineer_prompt_includes_playbook():
    p = Engineer._prompt("# spec", "coding", None, "ALWAYS use repository.py for DB access")
    assert "ALWAYS use repository.py" in p
    assert "Project playbook" in p


def test_engineer_prompt_without_playbook():
    assert "Project playbook" not in Engineer._prompt("# spec", "coding", None, "")


def test_read_playbook_missing_then_present(tmp_path):
    assert Playbook(tmp_path).read() == ""
    pb = Playbook(tmp_path).path
    pb.parent.mkdir(parents=True)
    pb.write_text("hello")
    assert Playbook(tmp_path).read() == "hello"


class FakeTechLead:
    def __init__(self, repo):
        self.repo = Path(repo)
        self.called = False

    def run_plain(self, _prompt):
        self.called = True
        pb = Playbook(self.repo).path
        pb.parent.mkdir(parents=True, exist_ok=True)
        pb.write_text("# Playbook\n\n- convention X")


def test_update_playbook_writes_file(tmp_path):
    tl = FakeTechLead(tmp_path)
    TechLead(runner=tl, ui=FakeUI()).refresh(tmp_path)
    assert tl.called
    assert "convention X" in Playbook(tmp_path).read()


def test_update_playbook_with_slug_logs_event(tmp_path):
    # the tech-lead's refresh shows on the task timeline as its step in the loop
    from leanlab.core.coding.events import EventLog
    TechLead(runner=FakeTechLead(tmp_path), ui=FakeUI()).refresh(tmp_path, "demo")
    assert [e["event"] for e in EventLog(tmp_path).read("demo")] == ["playbook"]


def test_update_playbook_without_slug_logs_nothing(tmp_path):
    from leanlab.core.coding.events import EventLog
    TechLead(runner=FakeTechLead(tmp_path), ui=FakeUI()).refresh(tmp_path)
    assert EventLog(tmp_path).read("demo") == []
