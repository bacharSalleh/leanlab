"""The judge for the house-prices lab. FROZEN — an experiment must never edit it.

What it does in easy words:
  - Loads the California-housing dataset (built into scikit-learn, no download).
  - Loads ONE experiment file from experiments/.
  - The experiment must define `build_estimator()` returning a scikit-learn-style
    model (it has .fit(X, y) and .predict(X)).
  - Fits it on a fixed TRAIN split, then measures error on a held-out TEST split
    the experiment never saw.
  - Prints ONE line of JSON metrics. The loop reads that line — nothing else.

The objective (see lab.json) is to MINIMIZE `rmse` on the test split.

Contract every experiment file must follow:
    def build_estimator():
        from sklearn.linear_model import LinearRegression
        return LinearRegression()      # any object with fit(X, y) / predict(X)

Run:
    uv run python evaluation.py --experiment experiments/sample.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time

import numpy as np
from sklearn.datasets import fetch_california_housing
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

RANDOM_STATE = 42  # frozen split so every experiment is judged on the same data


def load_experiment(path):
    """Load an experiment file and return its build_estimator() result."""
    spec = importlib.util.spec_from_file_location("experiment_module", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load experiment file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "build_estimator"):
        raise ValueError(f"{path}: contract broken — must define build_estimator().")
    estimator = module.build_estimator()
    if not (hasattr(estimator, "fit") and hasattr(estimator, "predict")):
        raise ValueError(f"{path}: build_estimator() must return a fit/predict model.")
    return estimator


def evaluate(estimator):
    """Fit on train, score on test. Returns a metrics dict."""
    data = fetch_california_housing()
    X_train, X_test, y_train, y_test = train_test_split(
        data.data, data.target, test_size=0.25, random_state=RANDOM_STATE
    )

    t0 = time.time()
    estimator.fit(X_train, y_train)
    train_secs = time.time() - t0

    pred_test = estimator.predict(X_test)
    pred_train = estimator.predict(X_train)

    rmse = float(np.sqrt(mean_squared_error(y_test, pred_test)))
    train_rmse = float(np.sqrt(mean_squared_error(y_train, pred_train)))
    return {
        "rmse": round(rmse, 5),
        "mae": round(float(mean_absolute_error(y_test, pred_test)), 5),
        "r2": round(float(r2_score(y_test, pred_test)), 5),
        "overfit_gap": round(rmse - train_rmse, 5),  # test minus train RMSE
        "train_secs": round(train_secs, 3),
    }


def main():
    p = argparse.ArgumentParser(description="Score a house-price experiment. Prints JSON metrics.")
    p.add_argument("--experiment", required=True, help="path to an experiment .py file")
    args = p.parse_args()

    try:
        estimator = load_experiment(args.experiment)
        metrics = evaluate(estimator)
    except Exception as exc:  # noqa: BLE001 - report any failure clearly
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)

    print(json.dumps(metrics))  # the ONE line the loop parses


if __name__ == "__main__":
    main()
