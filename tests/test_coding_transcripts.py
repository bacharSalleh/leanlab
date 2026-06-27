"""Transcripts — merge a task's Claude sessions into events + total usage."""

import os

from leanlab.core.monitor import Dashboard
from leanlab.core.coding.transcripts import Transcripts


def test_events_merge_all_sessions_and_usage(tmp_path, monkeypatch):
    # the chat must show EVERY agent session (all attempts + reviews), oldest first
    d = tmp_path / "tx"
    d.mkdir()
    (d / "a.jsonl").write_text("x")
    (d / "b.jsonl").write_text("x")
    os.utime(d / "a.jsonl", (1, 1))                      # a is older than b
    os.utime(d / "b.jsonl", (2, 2))
    canned = {"a.jsonl": [{"kind": "text", "text": "attempt 1", "in_tok": 10, "out_tok": 5}],
              "b.jsonl": [{"kind": "text", "text": "attempt 2", "in_tok": 20, "out_tok": 7}]}
    t = Transcripts(tmp_path)
    monkeypatch.setattr(t, "_dir", lambda slug: d)
    monkeypatch.setattr(Dashboard, "parse_session", staticmethod(lambda p: ({}, canned[p.name])))

    evs = t.events("demo")
    assert [e["kind"] for e in evs] == ["divider", "text", "divider", "text"]
    assert [e["text"] for e in evs if e["kind"] == "text"] == ["attempt 1", "attempt 2"]  # oldest first
    assert evs[0]["text"] == "session 1/2" and evs[0]["tokens"] == 15
    assert evs[2]["text"] == "session 2/2" and evs[2]["tokens"] == 27
    # usage shares the same cached parse: total = sum of every session
    assert t.usage("demo") == {"tokens": 42, "cost": 0.0}


def test_usage_zero_when_no_transcripts(tmp_path, monkeypatch):
    t = Transcripts(tmp_path)
    monkeypatch.setattr(t, "_dir", lambda slug: None)
    assert t.usage("demo") == {"tokens": 0, "cost": 0.0}
    assert t.events("demo") == []
