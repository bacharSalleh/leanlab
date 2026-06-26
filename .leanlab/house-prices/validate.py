"""The validator for the house-prices lab. The EXPERIMENTER runs this — not the judge.

It checks your experiment follows the contract and can train without crashing,
on a TINY slice of data. It does NOT report any score — that is the loop's job
(it runs evaluation.py later). Prints only VALID or INVALID: <reason>.

Run:
    uv run python validate.py --experiment experiments/<your_file>.py
"""

from __future__ import annotations

import argparse
import sys

from sklearn.datasets import fetch_california_housing

from evaluation import load_experiment


def smoke_check(estimator):
    """Fit/predict on a tiny slice. Return (ok, message). No scoring."""
    data = fetch_california_housing()
    X, y = data.data[:500], data.target[:500]
    try:
        estimator.fit(X, y)
        preds = estimator.predict(X[:10])
    except Exception as exc:  # noqa: BLE001 - any crash = invalid
        return False, f"fit/predict crashed: {type(exc).__name__}: {exc}"
    if len(preds) != 10:
        return False, f"predict returned {len(preds)} values for 10 rows."
    return True, "built, fit, and predicted with no errors."


def main():
    p = argparse.ArgumentParser(description="Validate an experiment file. Prints VALID/INVALID.")
    p.add_argument("--experiment", required=True, help="path to an experiment .py file")
    args = p.parse_args()

    try:
        estimator = load_experiment(args.experiment)
    except Exception as exc:  # noqa: BLE001
        print(f"INVALID: {type(exc).__name__}: {exc}")
        sys.exit(1)

    ok, message = smoke_check(estimator)
    print(("VALID: " if ok else "INVALID: ") + message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
