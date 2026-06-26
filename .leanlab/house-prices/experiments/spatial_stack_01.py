"""CV-stacked ensemble (HGB + ExtraTrees + spatial-KNN) over geo features, ridge meta-learner."""


def build_estimator():
    import numpy as np
    from sklearn.base import BaseEstimator, TransformerMixin
    from sklearn.ensemble import (
        HistGradientBoostingRegressor,
        ExtraTreesRegressor,
        StackingRegressor,
    )
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.linear_model import RidgeCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    # California-housing columns:
    # 0 MedInc, 1 HouseAge, 2 AveRooms, 3 AveBedrms, 4 Population,
    # 5 AveOccup, 6 Latitude, 7 Longitude
    class GeoFeatures(BaseEstimator, TransformerMixin):
        def fit(self, X, y=None):
            return self

        def transform(self, X):
            X = np.asarray(X, dtype=float)
            MedInc, AveRooms, AveBedrms = X[:, 0], X[:, 2], X[:, 3]
            Population, AveOccup, Lat, Lon = X[:, 4], X[:, 5], X[:, 6], X[:, 7]
            eps = 1e-6
            bedrm_ratio = AveBedrms / (AveRooms + eps)
            rooms_per_person = AveRooms / (AveOccup + eps)
            pop_per_house = Population / (AveOccup + eps)
            d_la = np.sqrt((Lat - 34.05) ** 2 + (Lon + 118.24) ** 2)
            d_sf = np.sqrt((Lat - 37.77) ** 2 + (Lon + 122.42) ** 2)
            coast = np.minimum(d_la, d_sf)
            inc_x_coast = MedInc / (coast + eps)
            extra = np.column_stack(
                [bedrm_ratio, rooms_per_person, pop_per_house,
                 d_la, d_sf, coast, inc_x_coast]
            )
            return np.column_stack([X, extra])

    # spatial KNN: only location matters, so scale + KNN on lat/lon-heavy space
    knn = Pipeline([
        ("scale", StandardScaler()),
        ("knn", KNeighborsRegressor(n_neighbors=12, weights="distance")),
    ])

    hgb = HistGradientBoostingRegressor(
        loss="absolute_error",
        max_iter=600,
        learning_rate=0.05,
        max_leaf_nodes=31,
        min_samples_leaf=25,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=30,
        random_state=42,
    )

    et = ExtraTreesRegressor(
        n_estimators=400,
        min_samples_leaf=3,
        max_features=0.6,
        n_jobs=-1,
        random_state=42,
    )

    stack = StackingRegressor(
        estimators=[("hgb", hgb), ("et", et), ("knn", knn)],
        final_estimator=RidgeCV(alphas=(0.01, 0.1, 1.0, 10.0)),
        cv=5,
        passthrough=False,
        n_jobs=-1,
    )

    return Pipeline([("feats", GeoFeatures()), ("stack", stack)])
