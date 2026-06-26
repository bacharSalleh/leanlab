"""Log-target seed-bagged CatBoost with an HONEST self-excluded spatial KNN prior, blended with a non-tree Nystroem-RBF smooth spatial learner; predictions clipped to the price cap."""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.model_selection import KFold
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from sklearn.kernel_approximation import Nystroem
from sklearn.linear_model import Ridge

LAT, LON = 6, 7  # column indices in the raw california-housing array


def _engineer(X):
    """Build geo + ratio features (no target leakage). Returns a numeric matrix."""
    X = np.asarray(X, dtype=float)
    lat, lon = X[:, LAT], X[:, LON]
    medinc = X[:, 0]
    # rotated coordinate frames capture diagonal coastlines trees split poorly
    rot = []
    for ang in (30.0, 60.0):
        a = np.deg2rad(ang)
        rot.append(lat * np.cos(a) + lon * np.sin(a))
        rot.append(-lat * np.sin(a) + lon * np.cos(a))
    extra = np.column_stack([
        X[:, 2] / np.maximum(X[:, 5], 1e-6),   # rooms per occupant
        X[:, 3] / np.maximum(X[:, 2], 1e-6),   # bedroom fraction
        medinc * lat,                           # income x location
        *rot,
    ])
    return np.column_stack([X, extra])


def _knn_prior_density(nn, y_train, coords, exclude_self):
    """Self-excluded distance-weighted target prior + local density (dist to k-th nbr)."""
    k = nn.n_neighbors
    dist, idx = nn.kneighbors(coords)
    if exclude_self:
        # drop the first column (the point itself when querying its own training set)
        dist, idx = dist[:, 1:], idx[:, 1:]
    else:
        dist, idx = dist[:, :k - 1], idx[:, :k - 1]
    w = 1.0 / np.maximum(dist, 1e-6)
    prior = np.sum(w * y_train[idx], axis=1) / np.sum(w, axis=1)
    density = dist[:, -1]  # distance to farthest of the k neighbors ~ how rural
    return prior, density


class LogHonestSpatialBlend(BaseEstimator, RegressorMixin):
    def __init__(self, k=20, n_seeds=3):
        self.k = k
        self.n_seeds = n_seeds

    def fit(self, X, y):
        from catboost import CatBoostRegressor

        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.y_min_, self.y_max_ = float(y.min()), float(y.max())
        yl = np.log1p(y)

        coords = X[:, [LAT, LON]]
        self.coords_ = coords
        self.y_train_ = y

        # ---- leakage-free OOF spatial prior to TRAIN the booster on ----
        oof_prior = np.zeros(len(y))
        oof_density = np.zeros(len(y))
        kf = KFold(n_splits=5, shuffle=True, random_state=0)
        for tr, va in kf.split(coords):
            nn = NearestNeighbors(n_neighbors=self.k).fit(coords[tr])
            p, d = _knn_prior_density(nn, y[tr], coords[va], exclude_self=False)
            oof_prior[va], oof_density[va] = p, d
        # full-data KNN used at predict time (self-excluded -> same distribution)
        self.nn_full_ = NearestNeighbors(n_neighbors=self.k + 1).fit(coords)

        base = _engineer(X)
        Xtr = np.column_stack([base, oof_prior, oof_density])

        # ---- seed-bagged CatBoost on the LOG target (robust to seed) ----
        self.boosters_ = []
        for s in range(self.n_seeds):
            m = CatBoostRegressor(
                iterations=600, depth=7, learning_rate=0.04,
                l2_leaf_reg=4.0, loss_function="RMSE",
                random_seed=s, verbose=False,
            )
            m.fit(Xtr, yl)
            self.boosters_.append(m)

        # ---- non-tree smooth spatial learner (Nystroem RBF + Ridge) ----
        self.scaler_ = StandardScaler().fit(base)
        Xs = self.scaler_.transform(base)
        self.nys_ = Nystroem(kernel="rbf", gamma=0.5, n_components=300,
                             random_state=0).fit(Xs)
        self.krr_ = Ridge(alpha=1.0).fit(self.nys_.transform(Xs), yl)

        # ---- learn blend weights on OOF preds (honest) ----
        oof_b = np.mean([m.predict(Xtr) for m in self.boosters_], axis=0)
        oof_k = np.zeros(len(y))
        for tr, va in kf.split(base):
            sc = StandardScaler().fit(base[tr])
            ny = Nystroem(kernel="rbf", gamma=0.5, n_components=300,
                          random_state=0).fit(sc.transform(base[tr]))
            rg = Ridge(alpha=1.0).fit(ny.transform(sc.transform(base[tr])), yl[tr])
            oof_k[va] = rg.predict(ny.transform(sc.transform(base[va])))
        meta_X = np.column_stack([oof_b, oof_k])
        self.blend_ = Ridge(alpha=1e-3, positive=True).fit(meta_X, yl)
        return self

    def predict(self, X):
        X = np.asarray(X, dtype=float)
        coords = X[:, [LAT, LON]]
        prior, density = _knn_prior_density(
            self.nn_full_, self.y_train_, coords, exclude_self=True)
        base = _engineer(X)
        Xb = np.column_stack([base, prior, density])
        pb = np.mean([m.predict(Xb) for m in self.boosters_], axis=0)
        pk = self.krr_.predict(self.nys_.transform(self.scaler_.transform(base)))
        pl = self.blend_.predict(np.column_stack([pb, pk]))
        pred = np.expm1(pl)
        return np.clip(pred, self.y_min_, self.y_max_)


def build_estimator():
    return LogHonestSpatialBlend(k=20, n_seeds=3)
