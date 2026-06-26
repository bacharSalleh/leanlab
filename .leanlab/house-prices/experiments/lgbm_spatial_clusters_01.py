"""LightGBM on geo features enriched with KMeans spatial-cluster distances and rotated coords."""


def build_estimator():
    import numpy as np
    from sklearn.base import BaseEstimator, TransformerMixin
    from sklearn.cluster import KMeans
    from sklearn.pipeline import Pipeline
    from lightgbm import LGBMRegressor

    # Columns: 0 MedInc, 1 HouseAge, 2 AveRooms, 3 AveBedrms,
    #          4 Population, 5 AveOccup, 6 Latitude, 7 Longitude
    class SpatialGeoFeatures(BaseEstimator, TransformerMixin):
        def __init__(self, n_clusters=20):
            self.n_clusters = n_clusters

        def fit(self, X, y=None):
            X = np.asarray(X, dtype=float)
            coords = X[:, 6:8]
            self.km_ = KMeans(n_clusters=self.n_clusters, n_init=10,
                              random_state=42).fit(coords)
            return self

        def transform(self, X):
            X = np.asarray(X, dtype=float)
            MedInc, AveRooms, AveBedrms = X[:, 0], X[:, 2], X[:, 3]
            Population, AveOccup, Lat, Lon = X[:, 4], X[:, 5], X[:, 6], X[:, 7]
            eps = 1e-6

            bedrm_ratio = AveBedrms / (AveRooms + eps)
            rooms_per_person = AveRooms / (AveOccup + eps)
            pop_per_house = Population / (AveOccup + eps)

            # distance to the big-city anchors
            d_la = np.sqrt((Lat - 34.05) ** 2 + (Lon + 118.24) ** 2)
            d_sf = np.sqrt((Lat - 37.77) ** 2 + (Lon + 122.42) ** 2)
            coast = np.minimum(d_la, d_sf)
            inc_x_coast = MedInc / (coast + eps)

            # rotated coordinates capture the diagonal CA coastline
            rot45 = (Lat + Lon) / np.sqrt(2.0)
            rot135 = (Lat - Lon) / np.sqrt(2.0)

            # distance to each learned spatial cluster centroid
            coords = X[:, 6:8]
            cdist = self.km_.transform(coords)

            extra = np.column_stack([
                bedrm_ratio, rooms_per_person, pop_per_house,
                d_la, d_sf, coast, inc_x_coast, rot45, rot135,
            ])
            return np.column_stack([X, extra, cdist])

    lgbm = LGBMRegressor(
        objective="regression_l1",
        n_estimators=1200,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=-1,
        min_child_samples=25,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        reg_alpha=0.1,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )

    return Pipeline([("feats", SpatialGeoFeatures(n_clusters=20)), ("lgbm", lgbm)])
