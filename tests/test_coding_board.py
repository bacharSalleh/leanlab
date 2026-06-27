"""Coding lab M5 — the board: task state + HTML render."""

import json

import pytest

from leanlab.core.coding import board
from leanlab.core.coding.board import Board
from leanlab.core.coding.events import EventLog


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path_factory):
    # board usage/transcript lookups resolve ~/.claude/projects; pin HOME to an empty dir
    # so a real worktree transcript on the dev's machine can never leak into these tests.
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    board._TRANSCRIPTS.clear()


def _setup(tmp_path):
    base = tmp_path / ".leanlab"
    for slug, spec in [("add-health", "Add a /health endpoint returning 200."),
                       ("add-auth", "Add auth."),
                       ("fix-bug", "Fix the off-by-one.")]:
        wt = base / "worktrees" / slug
        wt.mkdir(parents=True)
        (wt / "SPEC.md").write_text(f"# Spec\n\n{spec}")
    res = base / "coding-results.jsonl"
    res.write_text(
        json.dumps({"slug": "add-health", "merged": True, "attempts": 2}) + "\n"
        + json.dumps({"slug": "fix-bug", "merged": False, "attempts": 3}) + "\n")
    (base / "PLAYBOOK.md").write_text("# Playbook\n\n- endpoints go in routes/")
    return tmp_path


def test_coding_state(tmp_path):
    st = Board(_setup(tmp_path)).state()
    by = {t["slug"]: t for t in st["tasks"]}
    assert by["add-health"]["status"] == "merged" and by["add-health"]["attempts"] == 2
    assert by["fix-bug"]["status"] == "failed"
    assert by["add-auth"]["status"] == "spec'd"          # no build result yet
    t = st["totals"]
    assert (t["tasks"], t["merged"], t["failed"], t["open"]) == (3, 1, 1, 1)
    assert t["success"] == 50                             # 1 merged of 2 decided
    assert "tokens" in t and "cost" in t                 # usage aggregated
    assert by["add-health"]["tokens"] == 0 and by["add-health"]["cost"] == 0.0  # no transcripts in tmp
    assert "endpoints go in routes/" in st["playbook"]


def test_overview_state(tmp_path):
    st = Board(_setup(tmp_path)).overview()
    assert st["lab"] == tmp_path.name
    assert {t["slug"] for t in st["tasks"]} == {"add-health", "add-auth", "fix-bug"}
    assert st["totals"]["merged"] == 1


def test_empty_state(tmp_path):
    st = Board(tmp_path).state()                    # no .leanlab at all
    assert st["totals"]["tasks"] == 0


def test_archived_task_shows_after_worktree_removed(tmp_path):
    # a merged task whose worktree was cleaned must still appear (from coding-results.jsonl)
    base = tmp_path / ".leanlab"
    base.mkdir()
    (base / "coding-results.jsonl").write_text(json.dumps({"slug": "done", "merged": True, "attempts": 2}) + "\n")
    st = Board(tmp_path).state()                    # note: no worktrees/ dir at all
    by = {t["slug"]: t for t in st["tasks"]}
    assert by["done"]["status"] == "merged" and by["done"]["archived"] is True
    assert by["done"]["attempts"] == 2 and st["totals"]["merged"] == 1


def test_task_status_helper(tmp_path):
    base = tmp_path / ".leanlab"
    base.mkdir()
    (base / "coding-results.jsonl").write_text(
        json.dumps({"slug": "m", "merged": True}) + "\n" + json.dumps({"slug": "f", "merged": False}) + "\n")
    assert Board(tmp_path)._status("m") == "merged"          # result row wins
    assert Board(tmp_path)._status("f") == "failed"
    EventLog(tmp_path).log("g", {"event": "gaveup", "attempts": 5})
    assert Board(tmp_path)._status("g") == "failed"          # inferred from events
    assert Board(tmp_path)._status("unknown") == "spec'd"


def test_task_detail_reports_status(tmp_path):
    (tmp_path / ".leanlab" / "worktrees" / "demo").mkdir(parents=True)
    EventLog(tmp_path).log("demo", {"event": "merged", "merged": True})
    assert Board(tmp_path).task("demo")["status"] == "merged"


def test_archived_status_inferred_from_events(tmp_path):
    # a task with only an event log (no result row) gets its status + attempts from events
    EventLog(tmp_path).log("ev", {"event": "attempt", "n": 1, "gate_passed": False, "failures": ["tests"]})
    EventLog(tmp_path).log("ev", {"event": "gaveup", "attempts": 5})
    by = {t["slug"]: t for t in Board(tmp_path).state()["tasks"]}
    assert by["ev"]["status"] == "failed"               # derived from the gaveup event
    assert by["ev"]["attempts"] == 1 and by["ev"]["archived"] is True


def test_asset_blocks_path_traversal():
    # the static server must never serve files outside the built UI directory
    assert board._asset("../../../etc/passwd") is None
    assert board._asset("/../board.py") is None


def test_asset_serves_built_index(tmp_path):
    # the React app is built into board_dist/ and served at '/'
    import pytest
    idx = board._DIST / "index.html"
    if not idx.exists():
        pytest.skip("frontend not built (run: cd frontend && npm run build)")
    assert board._asset("/") == idx.resolve()
    assert board._asset("index.html") == idx.resolve()


def test_log_and_read_events(tmp_path):
    EventLog(tmp_path).log("demo", {"event": "attempt", "n": 1, "gate_passed": False, "failures": ["tests"]})
    EventLog(tmp_path).log("demo", {"event": "merged", "branch": "leanlab/demo"})
    evs = EventLog(tmp_path).read("demo")
    assert [e["event"] for e in evs] == ["attempt", "merged"]
    assert evs[0]["ts"]                                  # timestamp stamped on


def test_task_detail_timeline_and_render(tmp_path):
    wt = tmp_path / ".leanlab" / "worktrees" / "demo"
    wt.mkdir(parents=True)
    (wt / "SPEC.md").write_text("# Spec\n\nAdd a /health endpoint.")
    EventLog(tmp_path).log("demo", {"event": "spec", "tests": ["tests/t.py"]})
    EventLog(tmp_path).log("demo", {"event": "attempt", "n": 1, "gate_passed": True, "failures": []})
    EventLog(tmp_path).log("demo", {"event": "review", "n": 1, "approved": True, "score": 88, "feedback": "clean"})
    EventLog(tmp_path).log("demo", {"event": "merged", "branch": "leanlab/demo", "merged": True})

    d = Board(tmp_path).task("demo")
    assert d["slug"] == "demo" and d["exists"] is True
    assert [e["event"] for e in d["timeline"]] == ["spec", "attempt", "review", "merged"]
    assert isinstance(d["stream"], list)                # no transcripts in a tmp dir
    assert "tokens" in d and "cost" in d                # usage is reported
