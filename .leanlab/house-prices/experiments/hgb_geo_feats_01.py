"""HistGradientBoosting on engineered geo/ratio features (rooms-per-house, income*location)."""


def build_estimator():
    import numpy as np
    from sklearn.base import BaseEstimator, TransformerMixin
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.pipeline import Pipeline

    # California-housing columns (in order):
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
            bedrm_ratio = AveBedrms / (AveRooms + eps)       # share of bedrooms
            rooms_per_person = AveRooms / (AveOccup + eps)    # crowding
            pop_per_house = Population / (AveOccup + eps)     # households
            # distance to two big coastal job centers (LA, SF)
            d_la = np.sqrt((Lat - 34.05) ** 2 + (Lon + 118.24) ** 2)
            d_sf = np.sqrt((Lat - 37.77) ** 2 + (Lon + 122.42) ** 2)
            coast = np.minimum(d_la, d_sf)
            inc_x_coast = MedInc / (coast + eps)             # rich near coast
            extra = np.column_stack(
                [bedrm_ratio, rooms_per_person, pop_per_house,
                 d_la, d_sf, coast, inc_x_coast]
            )
            return np.column_stack([X, extra])

    return Pipeline([
        ("feats", GeoFeatures()),
        ("model", HistGradientBoostingRegressor(
            loss="absolute_error",   # robust to the capped/outlier target
            max_iter=600,
            learning_rate=0.05,
            max_leaf_nodes=31,
            min_samples_leaf=25,
            l2_regularization=1.0,
            max_bins=255,
            early_stopping=True,
            validation_fraction=0.1,
            n_iter_no_change=30,
            random_state=42,
        )),
    ])
