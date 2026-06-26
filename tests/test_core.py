"""Tests for the generic loop core (objective ranking + memory)."""

from leanlab.core import loop


def _cfg(direction):
    return {"objective": {"metric": "rmse", "direction": direction},
            "results_file": "results.jsonl", "experiments_dir": "experiments"}


def test_best_value_min_and_max():
    rows = [{"rmse": 0.7}, {"rmse": 0.5}, {"rmse": 0.9}]
    assert loop.best_value(rows, _cfg("min")) == 0.5
    assert loop.best_value(rows, _cfg("max")) == 0.9


def test_best_value_ignores_non_numeric():
    rows = [{"rmse": None}, {"rmse": 0.4}, {"notes": "x"}]
    assert loop.best_value(rows, _cfg("min")) == 0.4


def test_is_better_respects_direction():
    assert loop.is_better(0.3, 0.5, "min") is True
    assert loop.is_better(0.6, 0.5, "min") is False
    assert loop.is_better(0.6, 0.5, "max") is True
    assert loop.is_better(0.1, None, "min") is True  # first result is always best


def test_memory_sorts_by_objective():
    rows = [
        {"experiment_file": "experiments/a.py", "rmse": 0.8, "notes": "a"},
        {"experiment_file": "experiments/b.py", "rmse": 0.4, "notes": "b"},
    ]
    mem = loop.build_memory(rows, _cfg("min"))
    # the better (lower rmse) experiment must appear first
    assert mem.index("b.py") < mem.index("a.py")


def test_memory_empty():
    assert "no experiments scored yet" in loop.build_memory([], _cfg("min"))
