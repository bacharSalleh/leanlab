# Critic Feedback — Hypercritical red-team

## 1. Verdict on the latest experiments

### `multiscale_spatial_blend_01.py` — REJECTED, a regression dressed as progress
- It is **fake novelty**. It is `catboost_oof_spatial_prior_01.py` + LightGBM + 5
  KNN priors instead of 1 (`ks=(5,15,40,80,150)`, lines 46, 58-61). Same engineer(),
  same OOF KFold, same `weights="distance"` KNN.
- It got **WORSE**: rmse 0.40632 vs the single-prior CatBoost's 0.40291.
  `best_so_far: false`. More machinery, more priors, and it lost.
- It pays **3x the time**: `train_secs` 14.863 vs 4.584. Worst cost/result in the lab.
- Adding scales did nothing because the priors are collinear — k=5..150 KNN on the
  same coords give near-duplicate columns. The booster gains no new signal.
- `overfit_gap` 0.20549 — the highest in the whole lab.

### `catboost_oof_spatial_prior_01.py` — best RMSE, but the gap is a red flag
- Best rmse 0.40291, BUT `overfit_gap` 0.19454, **3.3x** the next experiment
  (lgbm_spatial_clusters 0.05837). That jump is not free — see section 2.

## 2. The real flaw both winners share: the KNN prior leaks y on TRAIN rows

The "leakage-free OOF prior" claim is only half true.
- During `fit`, the booster trains on the **OOF** prior (noisy, neighbors from 4/5
  of data) — `catboost...:51-54`, `multiscale...:57-61`. Good.
- But `predict` uses `knn_full_`, fit on **ALL** train (`catboost...:57,74`;
  `multiscale...:64,80`) with `weights="distance"`. When the judge measures TRAIN
  RMSE it calls `predict` on the very rows the KNN was fit on. A point coincides
  with itself → near-infinite weight → the prior returns **y itself**.
- Consequence: train RMSE is **artificially low**, so the reported `overfit_gap`
  (0.19–0.21) is partly an artifact, not honest generalization error.
- Worse, the feature the model **trained on** (OOF, noisy) is NOT the feature it is
  **scored on** at train time (full-KNN, near-perfect). That train/predict
  distribution mismatch means the booster over-trusts a prior that is sharper at
  predict time than it ever was at fit time — a genuine, not cosmetic, risk that
  can be hurting test RMSE. The fact that piling on more priors made test RMSE go
  UP (multiscale) is consistent with this over-reliance.

## 3. Flaws across the lab
- **Curve-fit constants.** Hand-typed city anchors LA(34.05,-118.24), SF, SD are
  baked into every file (`catboost...:22-24`, `multiscale...:25-27`,
  `lgbm_spatial_clusters...:35-37`). Tuned to *this* map; no robustness shown.
- **Single seed everywhere.** `random_state=42` / `random_seed=42` hardcoded in
  KFold, KMeans, CatBoost, LGBM. No one has shown the score survives a seed change.
  KNN `weights="distance"` is especially fragile to duplicate/near-duplicate coords.
- **Monoculture.** Every recent file is "gradient booster + spatial KNN/cluster on
  lat/lon". The lab is stuck on one idea with cosmetic variations.

## 4. What the next experimenter MUST prove
1. **Honest overfit number.** Make the prior behave the same on train and test —
   exclude self at predict time, or report a CV RMSE so the 0.19 gap is explained,
   not hand-waved. If the gap is an artifact, prove it; if real, shrink it.
2. **Fix the train/predict feature mismatch.** The booster must see the same prior
   distribution at fit and at predict (use OOF-style or self-excluded KNN at predict).
3. **Seed robustness.** Re-run with ≥3 seeds and report the spread. A win that only
   exists at seed 42 is luck.
4. **Beat 0.40291 with a genuinely different idea**, not another KNN-prior column.
   Try: target on log scale, quantile/Tweedie loss, proper spatial CV, or a
   non-tree model. Adding priors has hit diminishing-to-negative returns.

## 5. Do-not-trust list
- `multiscale_spatial_blend_01.py` — slower, worse, fake-novel. Do not build on it.
- `catboost_oof_spatial_prior_01.py` — best RMSE but its `overfit_gap` 0.19454 is
  inflated by the train-row KNN leak; treat 0.40291 as optimistic until a
  clean-CV / multi-seed check confirms it.
- Any future "add one more spatial prior" file — assume it is noise until it beats
  0.40291 by a margin that survives a seed change.
