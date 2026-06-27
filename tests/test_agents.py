"""The agent port — structured-output extraction (the JSON contract)."""

from leanlab.core.agents.protocol import extract_json


def test_extract_bare_json():
    assert extract_json('{"a": 1, "b": 2}', ["a", "b"]) == {"a": 1, "b": 2}


def test_extract_nested_json_wrapped_in_prose():
    # spec/init replies are NESTED; a flat {[^{}]*} regex could not match this.
    reply = ('Here is the spec:\n```json\n'
             '{"spec_md": "# Spec", "tests": [{"path": "t.py", "content": "x"}]}\n```\nDone.')
    out = extract_json(reply, ["spec_md", "tests"])
    assert out is not None
    assert out["tests"][0]["path"] == "t.py"


def test_extract_picks_last_matching_object():
    reply = '{"a": 1} then later {"a": 2, "b": 3}'
    assert extract_json(reply, ["a", "b"]) == {"a": 2, "b": 3}


def test_extract_returns_none_when_keys_missing():
    assert extract_json('{"a": 1}', ["a", "b"]) is None
    assert extract_json("", ["a"]) is None
    assert extract_json("no json here", ["a"]) is None


def test_extract_ignores_braces_inside_strings():
    # a brace inside a string value must not confuse the balancer
    assert extract_json('{"a": "} not the end {", "b": 2}', ["a", "b"]) == {"a": "} not the end {", "b": 2}
