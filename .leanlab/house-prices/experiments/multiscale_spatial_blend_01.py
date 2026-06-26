"""Blend of CatBoost + LightGBM fed leakage-free OOF spatial priors at MANY scales (k=5..150)."""


def build_estimator():
    import numpy as np
    from sklearn.base import BaseEstimator, RegressorMixin
    from sklearn.model_selection import KFold
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from catboost import CatBoostRegressor
    from lightgbm import LGBMRegressor

    # Columns: 0 MedInc 1 HouseAge 2 AveRooms 3 AveBedrms
    #          4 Population 5 AveOccup 6 Latitude 7 Longitude
    def engineer(X):
        X = np.asarray(X, dtype=float)
        MedInc, AveRooms, AveBedrms = X[:, 0], X[:, 2], X[:, 3]
        Population, AveOccup, Lat, Lon = X[:, 4], X[:, 5], X[:, 6], X[:, 7]
        eps = 1e-6
        bedrm_ratio = AveBedrms / (AveRooms + eps)
        rooms_per_person = AveRooms / (AveOccup + eps)
        pop_per_house = Population / (AveOccup + eps)
        inc_per_room = MedInc / (AveRooms + eps)
        d_la = np.sqrt((Lat - 34.05) ** 2 + (Lon + 118.24) ** 2)
        d_sf = np.sqrt((Lat - 37.77) ** 2 + (Lon + 122.42) ** 2)
        d_sd = np.sqrt((Lat - 32.72) ** 2 + (Lon + 117.16) ** 2)
        coast = np.minimum.reduce([d_la, d_sf, d_sd])
        rot45 = (Lat + Lon) / np.sqrt(2.0)
        rot135 = (Lat - Lon) / np.sqrt(2.0)
        extra = np.column_stack([
            bedrm_ratio, rooms_per_person, pop_per_house, inc_per_room,
            d_la, d_sf, d_sd, coast, rot45, rot135,
        ])
        return np.column_stack([X, extra])

    def knn_pipe(k):
        return Pipeline([
            ("sc", StandardScaler()),
            ("knn", KNeighborsRegressor(n_neighbors=k, weights="distance")),
        ])

    class MultiScaleSpatialBlend(BaseEstimator, RegressorMixin):
        """Many spatial KNN priors (different k) as features, then blend two boosters."""

        def __init__(self, ks=(5, 15, 40, 80, 150), n_splits=5):
            self.ks = ks
            self.n_splits = n_splits

        def fit(self, X, y):
            X = np.asarray(X, dtype=float)
            y = np.asarray(y, dtype=float)
            coords = X[:, 6:8]

            # leakage-free out-of-fold priors, one column per scale k
            oof = np.zeros((len(y), len(self.ks)))
            kf = KFold(n_splits=self.n_splits, shuffle=True, random_state=42)
            for tr, va in kf.split(coords):
                for j, k in enumerate(self.ks):
                    m = knn_pipe(k).fit(coords[tr], y[tr])
                    oof[va, j] = m.predict(coords[va])

            # final KNNs on ALL train, applied to test rows at predict time
            self.knn_full_ = [knn_pipe(k).fit(coords, y) for k in self.ks]

            Xp = np.column_stack([engineer(X), oof])
            self.cat_ = CatBoostRegressor(
                loss_function="RMSE", iterations=2000, learning_rate=0.03,
                depth=8, l2_leaf_reg=3.0, random_seed=42, verbose=False,
            ).fit(Xp, y)
            self.lgb_ = LGBMRegressor(
                n_estimators=1500, learning_rate=0.03, num_leaves=63,
                subsample=0.8, colsample_bytree=0.8, reg_lambda=2.0,
                random_state=42, verbose=-1,
            ).fit(Xp, y)
            return self

        def predict(self, X):
            X = np.asarray(X, dtype=float)
            priors = np.column_stack([m.predict(X[:, 6:8]) for m in self.knn_full_])
            Xp = np.column_stack([engineer(X), priors])
            return 0.5 * self.cat_.predict(Xp) + 0.5 * self.lgb_.predict(Xp)

    return MultiScaleSpatialBlend()
