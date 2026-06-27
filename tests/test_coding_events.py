from leanlab.core.coding.events import EventLog


def test_log_appends_with_timestamp_and_reads_back(tmp_path):
    log = EventLog(tmp_path)
    log.log("demo", {"event": "attempt", "n": 1})
    log.log("demo", {"event": "merged", "merged": True})
    evs = log.read("demo")
    assert [e["event"] for e in evs] == ["attempt", "merged"]
    assert evs[0]["ts"]                       # ISO timestamp stamped on
    assert evs[0]["n"] == 1


def test_read_missing_is_empty(tmp_path):
    assert EventLog(tmp_path).read("nope") == []
