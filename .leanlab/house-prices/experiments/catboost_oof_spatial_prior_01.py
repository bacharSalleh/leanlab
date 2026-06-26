"""CatBoost fed a leakage-free out-of-fold spatial-KNN target prior as an extra feature."""


def build_estimator():
    import numpy as np
    from sklearn.base import BaseEstimator, RegressorMixin, clone
    from sklearn.model_selection import KFold
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.preprocessing import StandardScaler
    from catboost import CatBoostRegressor

    # Columns: 0 MedInc, 1 HouseAge, 2 AveRooms, 3 AveBedrms,
    #          4 Population, 5 AveOccup, 6 Latitude, 7 Longitude
    def engineer(X):
        X = np.asarray(X, dtype=float)
        MedInc, AveRooms, AveBedrms = X[:, 0], X[:, 2], X[:, 3]
        Population, AveOccup, Lat, Lon = X[:, 4], X[:, 5], X[:, 6], X[:, 7]
        eps = 1e-6
        bedrm_ratio = AveBedrms / (AveRooms + eps)
        rooms_per_person = AveRooms / (AveOccup + eps)
        pop_per_house = Population / (AveOccup + eps)
        d_la = np.sqrt((Lat - 34.05) ** 2 + (Lon + 118.24) ** 2)
        d_sf = np.sqrt((Lat - 37.77) ** 2 + (Lon + 122.42) ** 2)
        d_sd = np.sqrt((Lat - 32.72) ** 2 + (Lon + 117.16) ** 2)
        coast = np.minimum.reduce([d_la, d_sf, d_sd])
        rot45 = (Lat + Lon) / np.sqrt(2.0)
        rot135 = (Lat - Lon) / np.sqrt(2.0)
        extra = np.column_stack([
            bedrm_ratio, rooms_per_person, pop_per_house,
            d_la, d_sf, d_sd, coast, rot45, rot135,
        ])
        return np.column_stack([X, extra])

    class SpatialPriorCatBoost(BaseEstimator, RegressorMixin):
        """Adds an OOF geographic KNN prediction of y as a feature, then boosts."""

        def __init__(self, n_neighbors=12, n_splits=5):
            self.n_neighbors = n_neighbors
            self.n_splits = n_splits

        def _knn(self):
            return Pipeline_knn(self.n_neighbors)

        def fit(self, X, y):
            X = np.asarray(X, dtype=float)
            y = np.asarray(y, dtype=float)
            coords = X[:, 6:8]

            # leakage-free out-of-fold spatial prior for the training rows
            oof = np.zeros(len(y))
            kf = KFold(n_splits=self.n_splits, shuffle=True, random_state=42)
            for tr, va in kf.split(coords):
                knn = self._knn().fit(coords[tr], y[tr])
                oof[va] = knn.predict(coords[va])

            # final KNN on ALL train data, used at predict time on test rows
            self.knn_full_ = self._knn().fit(coords, y)

            feats = engineer(X)
            Xp = np.column_stack([feats, oof])
            self.model_ = CatBoostRegressor(
                loss_function="RMSE",
                iterations=2000,
                learning_rate=0.03,
                depth=8,
                l2_leaf_reg=3.0,
                random_seed=42,
                verbose=False,
            ).fit(Xp, y)
            return self

        def predict(self, X):
            X = np.asarray(X, dtype=float)
            prior = self.knn_full_.predict(X[:, 6:8])
            Xp = np.column_stack([engineer(X), prior])
            return self.model_.predict(Xp)

    def Pipeline_knn(k):
        from sklearn.pipeline import Pipeline
        return Pipeline([
            ("sc", StandardScaler()),
            ("knn", KNeighborsRegressor(n_neighbors=k, weights="distance")),
        ])

    return SpatialPriorCatBoost(n_neighbors=12, n_splits=5)
