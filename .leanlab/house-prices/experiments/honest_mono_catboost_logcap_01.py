"""Honest self-excluded spatial KNN prior + density, fed to a log-target seed-bagged CatBoost with a monotone MedInc->price constraint, predictions clipped to the price cap."""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.model_selection import KFold
from sklearn.neighbors import NearestNeighbors

LAT, LON = 6, 7  # column indices in the raw california-housing array


def _engineer(X):
    """Geo + ratio features, no target leakage. MedInc stays at column 0."""
    X = np.asarray(X, dtype=float)
    lat, lon = X[:, LAT], X[:, LON]
    medinc, averooms, avebedrms = X[:, 0], X[:, 2], X[:, 3]
    population, aveoccup = X[:, 4], X[:, 5]
    eps = 1e-6
    # rotated coordinate frames capture diagonal coastlines trees split poorly
    rot = []
    for ang in (30.0, 45.0, 60.0):
        a = np.deg2rad(ang)
        rot.append(lat * np.cos(a) + lon * np.sin(a))
        rot.append(-lat * np.sin(a) + lon * np.cos(a))
    extra = np.column_stack([
        avebedrms / (averooms + eps),     # bedroom fraction
        averooms / (aveoccup + eps),      # rooms per occupant
        population / (aveoccup + eps),    # houses per district
        medinc * lat,                     # income x location
        *rot,
    ])
    return np.column_stack([X, extra])


def _prior_density(nn, y_train, coords, exclude_self):
    """Self-excluded distance-weighted target prior + local density (dist to k-th nbr)."""
    dist, idx = nn.kneighbors(coords)
    if exclude_self:
        dist, idx = dist[:, 1:], idx[:, 1:]   # drop the query point itself
    else:
        dist, idx = dist[:, :-1], idx[:, :-1]  # match shape (k neighbors)
    w = 1.0 / np.maximum(dist, 1e-6)
    prior = np.sum(w * y_train[idx], axis=1) / np.sum(w, axis=1)
    density = dist[:, -1]  # distance to farthest kept neighbor ~ how rural
    return prior, density


class HonestMonoCatBoost(BaseEstimator, RegressorMixin):
    """CatBoost on log(price) with an HONEST spatial prior (same distribution at
    fit and predict) and a monotone constraint forcing MedInc to push price up."""

    def __init__(self, k=20, n_seeds=3):
        self.k = k
        self.n_seeds = n_seeds

    def fit(self, X, y):
        from catboost import CatBoostRegressor

        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.y_min_, self.y_max_ = float(y.min()), float(y.max())
        yl = np.log1p(y)
        self.y_train_ = y

        coords = X[:, [LAT, LON]]

        # ---- leakage-free OOF spatial prior to TRAIN the booster on ----
        oof_prior = np.zeros(len(y))
        oof_density = np.zeros(len(y))
        kf = KFold(n_splits=5, shuffle=True, random_state=0)
        for tr, va in kf.split(coords):
            nn = NearestNeighbors(n_neighbors=self.k + 1).fit(coords[tr])
            p, d = _prior_density(nn, y[tr], coords[va], exclude_self=False)
            oof_prior[va], oof_density[va] = p, d
        # full-data KNN for predict; self-excluded -> SAME distribution as OOF
        self.nn_full_ = NearestNeighbors(n_neighbors=self.k + 1).fit(coords)

        base = _engineer(X)
        Xtr = np.column_stack([base, oof_prior, oof_density])

        # monotone: MedInc (column 0) must not decrease the prediction
        mono = [0] * Xtr.shape[1]
        mono[0] = 1

        self.boosters_ = []
        for s in range(self.n_seeds):
            m = CatBoostRegressor(
                loss_function="RMSE",
                iterations=2000,
                learning_rate=0.03,
                depth=8,
                l2_leaf_reg=3.0,
                monotone_constraints=mono,
                random_seed=s,
                verbose=False,
            )
            m.fit(Xtr, yl)
            self.boosters_.append(m)
        return self

    def predict(self, X):
        X = np.asarray(X, dtype=float)
        coords = X[:, [LAT, LON]]
        prior, density = _prior_density(
            self.nn_full_, self.y_train_, coords, exclude_self=True)
        Xb = np.column_stack([_engineer(X), prior, density])
        pl = np.mean([m.predict(Xb) for m in self.boosters_], axis=0)
        return np.clip(np.expm1(pl), self.y_min_, self.y_max_)


def build_estimator():
    return HonestMonoCatBoost(k=20, n_seeds=3)
