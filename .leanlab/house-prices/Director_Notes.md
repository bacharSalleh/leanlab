# Director Notes

> Rewritten by the Director. Objective: **minimize test RMSE** on California
> housing, without a fake-low train RMSE inflating the overfit_gap.

## State of research

Five experiments. Score path: 0.460 → 0.447 → 0.432 → **0.403** (best).

| file | rmse | gap | secs | verdict |
|------|------|-----|------|---------|
| catboost_oof_spatial_prior_01 | **0.40291** | 0.195 | 4.6 | best rmse, but gap is partly an artifact |
| multiscale_spatial_blend_01 | 0.40632 | 0.205 | 14.9 | worse + 3x slower — dead end |
| lgbm_spatial_clusters_01 | 0.43184 | 0.058 | 4.9 | honest gap, clean, good base to build on |
| spatial_stack_01 | 0.44673 | 0.081 | 9.0 | stacking gave little |
| hgb_geo_feats_01 | 0.45993 | 0.058 | 1.9 | solid baseline |

**What is winning:** gradient boosting (CatBoost/LightGBM) + geographic features
(lat/lon, rotated coords, KMeans cluster distances, a KNN target prior).

**What is plateauing/dead:**
- Stacking and multi-scale prior blends did **not** beat a single clean CatBoost.
  Stop piling on more spatial-prior columns — k=5..150 KNN on the same coords are
  collinear and add nothing.
- The 0.403 "win" is suspect. The KNN prior is fit out-of-fold on TRAIN but at
  predict time uses a full-data KNN with `weights="distance"`. A train point is
  its own nearest neighbor → the prior returns ~y itself → train RMSE is fake-low,
  gap 0.195 is inflated, AND the booster trains on a noisier prior than it is
  scored on (a real distribution mismatch that can hurt TEST rmse, not just gap).

## The one bug to fix first (likely a free win)

Make the spatial prior have the **same distribution at fit and predict**.
At predict on a point that exists in the KNN's training set, **exclude self**
(query k+1 neighbors, drop the exact match) — or always use OOF-style priors both
times. Concretely: in `predict`, use `KNeighborsRegressor(n_neighbors=k+1)` and
drop the zero-distance neighbor, or refit the KNN leaving out the query rows. This
gives an honest gap and may *lower* test RMSE because the booster stops
over-trusting an over-sharp prior. Prove it with 3 seeds.

## Directions to try next (concrete)

1. **Honest spatial prior + retune CatBoost.** Take the 0.403 model, fix the
   self-neighbor leak (above), then retune `depth`, `l2_leaf_reg`, `learning_rate`,
   and KNN `k` under **spatial CV** (KFold on KMeans clusters, not random rows —
   random folds leak geography). Target: beat 0.403 at gap < 0.10.

2. **Log-target + handle the cap.** The target is capped at 5.0 (~$500k); many rows
   sit exactly at 5.0 (right-censored). Two moves to test:
   (a) fit on `log1p(y)` via `TransformedTargetRegressor` — prices are skewed;
   (b) clip predictions to [y.min, 5.0]. Either could shave RMSE on the tails.

3. **A genuinely different base model to blend.** The lab is a GBM monoculture.
   Add one non-tree learner and blend with honest OOF weights:
   - a small **MLP** (`MLPRegressor` or a tiny torch net) on scaled + rotated
     coords + features, or
   - **KRR / GP-style** local model on coords. Blend = ridge meta on OOF preds.
   A non-tree model captures smooth spatial gradients trees approximate in steps.

4. **Better geography, less hand-tuning.** Replace the 3 hand-typed city anchors
   with data-driven ones (cluster centroids you already learn) and add a local
   **density** feature (distance to the k-th nearest neighbor = how urban). Show it
   survives a seed change.

5. **Optuna tuning under spatial CV.** Wrap LightGBM (the clean 0.058-gap model) in
   an Optuna search over leaves/min_child/regularization/`n_estimators` with early
   stopping, scored by spatial-CV RMSE. The clean base may overtake CatBoost once
   tuned.

## What to avoid (proven weak here)

- **More spatial-prior columns / multi-scale KNN blends** — collinear, slower,
  scored worse. Do not submit another "add one more prior" file.
- **Plain stacking for its own sake** — spatial_stack underperformed a single
  clean model. Only blend if the base learners are genuinely different (idea 3).
- **Random-fold CV for anything spatial** — it leaks geography and flatters scores.
- **Single seed = 42 only.** Any new best must report ≥3 seeds and its spread.
