"""Tests for the dashboard's pure state helpers (stat-chip values) + role detection."""

import json

from leanlab.core import monitor


def _transcript(tmp_path, first_user_text):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": first_user_text},
                             "timestamp": "2026-06-22T00:00:00Z"}) + "\n")
    return p


def test_role_detection_from_injected_prompts(tmp_path):
    # the loop's new prompts start "You are the WORKER/DIRECTOR/CRITIC …"
    assert monitor.parse_session(_transcript(tmp_path, "You are the WORKER (experimenter) on this lab."))[0]["role"] == "worker"
    assert monitor.parse_session(_transcript(tmp_path, "You are the DIRECTOR (chief scientist) of this lab."))[0]["role"] == "director"
    assert monitor.parse_session(_transcript(tmp_path, "You are the CRITIC (hypercritical red-team) of this lab."))[0]["role"] == "critic"


def test_role_detection_legacy_and_unknown(tmp_path):
    # legacy "Read X.md" prompts still resolve; anything else is unknown
    assert monitor.parse_session(_transcript(tmp_path, "Read director.md and task.md"))[0]["role"] == "director"
    assert monitor.parse_session(_transcript(tmp_path, "hello there"))[0]["role"] == "unknown"


def test_latest_value_returns_last_row_metric():
    rows = [{"rmse": 0.7}, {"rmse": 0.5}, {"rmse": 0.62}]
    assert monitor.latest_value(rows, "rmse") == 0.62


def test_latest_value_none_for_empty():
    assert monitor.latest_value([], "rmse") is None


def test_latest_value_none_when_last_unparseable():
    assert monitor.latest_value([{"rmse": 0.5}, {"rmse": None}], "rmse") is None
    assert monitor.latest_value([{"notes": "x"}], "rmse") is None


def test_total_cost_sums_sessions():
    sessions = [{"cost": 0.21}, {"cost": 0.40}, {"cost": 0.33}]
    assert monitor.total_cost(sessions) == 0.94


def test_total_cost_zero_for_no_sessions():
    assert monitor.total_cost([]) == 0.0


def test_total_cost_ignores_missing_cost():
    assert monitor.total_cost([{"cost": 0.5}, {}, {"cost": None}]) == 0.5
