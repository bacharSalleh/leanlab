"""Coding lab M2 — the gate runner: every command must exit 0 for a change to pass."""

import sys

from leanlab.core.coding.gate import Gate


def _wt(tmp_path, test_body):
    wt = tmp_path / "wt"
    (wt / "tests").mkdir(parents=True)
    (wt / "tests" / "test_acceptance.py").write_text(test_body)
    return wt


PYTEST = f"{sys.executable} -m pytest -q"


def test_gate_passes_when_tests_pass(tmp_path):
    wt = _wt(tmp_path, "def test_ok():\n    assert 1 + 1 == 2\n")
    res = Gate([{"name": "tests", "cmd": PYTEST}]).run(wt)
    assert res.passed is True
    assert res.checks[0].ok and res.checks[0].code == 0


def test_gate_fails_when_tests_fail(tmp_path):
    wt = _wt(tmp_path, "def test_bad():\n    assert False\n")
    res = Gate([{"name": "tests", "cmd": PYTEST}]).run(wt)
    assert res.passed is False
    assert not res.checks[0].ok
    assert "assert" in res.checks[0].output.lower()


def test_gate_needs_all_steps_green(tmp_path):
    wt = _wt(tmp_path, "def test_ok():\n    assert True\n")
    res = Gate([
        {"name": "tests", "cmd": PYTEST},
        {"name": "lint", "cmd": f"{sys.executable} -c \"import sys; sys.exit(1)\""},
    ]).run(wt)
    assert res.passed is False
    assert len(res.failures()) == 1 and res.failures()[0].name == "lint"


def test_gate_handles_unrunnable_command(tmp_path):
    wt = _wt(tmp_path, "def test_ok():\n    assert True\n")
    res = Gate([{"name": "tests", "cmd": "this_binary_does_not_exist_xyz --q"}]).run(wt)
    assert res.passed is False
    assert "could not run" in res.checks[0].output


def test_gate_class_holds_its_commands(tmp_path):
    wt = _wt(tmp_path, "def test_ok():\n    assert True\n")
    gate = Gate([{"name": "tests", "cmd": PYTEST}])
    assert gate.run(wt).passed is True
    wt2 = _wt(tmp_path / "b", "def test_bad():\n    assert False\n")
    assert gate.run(wt2).passed is False         # same Gate, reused across worktrees
