# Task — predict California house prices

## The goal

Build a model that predicts the **median house value** for California districts as
accurately as possible. You are judged by **RMSE on a held-out test set** — and
**lower is better**.

## The data

The scikit-learn **California-housing** dataset (built in, no download). Features
are district-level numbers (median income, house age, average rooms, location,
etc.); the target is the median house value (in $100,000s).

## The experiment contract

Every experiment is ONE file in `experiments/` that defines `build_estimator()`:

```python
def build_estimator():
    # return any object with scikit-learn's .fit(X, y) and .predict(X)
    from sklearn.ensemble import GradientBoostingRegressor
    return GradientBoostingRegressor(n_estimators=300, max_depth=3)
```

- The judge fits your estimator on a fixed TRAIN split and measures error on a
  TEST split your code never sees.
- You may wrap preprocessing in a `sklearn.pipeline.Pipeline` and return that.
- Put a one-line docstring at the top describing the idea.

## How you are judged

The loop runs the frozen `evaluation.py`, which prints these metrics:

| metric | meaning | goal |
|--------|---------|------|
| `rmse` | root mean squared error on test | **minimize (the objective)** |
| `mae` | mean absolute error on test | lower better |
| `r2` | variance explained on test | higher better |
| `overfit_gap` | test RMSE − train RMSE | smaller = less overfit |
| `train_secs` | time to fit | lower better |

Aim for **low test RMSE without a big overfit gap** — a model that memorizes
train but generalizes poorly is not a win.

## How to validate before you finish

```bash
uv run python validate.py --experiment experiments/<your_file>.py
```

It must print `VALID`. It tells you nothing about RMSE — that is on purpose.
