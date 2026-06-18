# Plan 001: Add Calibrated Walk-Forward Evaluation

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- src/mma_eff_lab/models tests data/models`
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding; on mismatch, stop and report.

## Status

- **Priority**: P0
- **Effort**: L
- **Risk**: MED
- **Depends on**: none
- **Category**: tests / correctness / direction
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

The repo's output is a win probability, not just a class label. Current benchmarks include temporal and walk-forward evaluation for raw model specs, while the served calibrated UFC CatBoost model has only one held-out UFCStats test report. A quant-dev portfolio needs proof that calibration holds through time, across folds, and by source. This plan creates that proof without changing the modeling objective.

## Current State

- `src/mma_eff_lab/models/benchmark.py` compares raw baseline XGBoost, rating XGBoost, and rating CatBoost using temporal and walk-forward splits.
- `src/mma_eff_lab/models/calibrated.py` trains a calibrated UFC CatBoost serving artifact using one train/validation/test split.
- `data/models/calibrated_ufc_catboost_v1/metrics.json` reports only one UFCStats held-out window:
  - raw log loss `0.6428390532641346`;
  - isotonic log loss `0.6408594431514402`;
  - isotonic Brier `0.22469703881415945`;
  - isotonic AUC `0.6826010327022376`.

Relevant excerpt:

```python
# src/mma_eff_lab/models/calibrated.py:45-75
calibration_model = _catboost_model()
calibration_model.fit(... split.train ..., eval_set=(... split.validation ...))
validation_probabilities = _probabilities(calibration_model, split.validation, spec.feature_columns)
calibrator = _fit_calibrators(validation_probabilities, split.validation[TARGET_COLUMN].astype(int)).isotonic

final_train = pd.concat([split.train, split.validation], ignore_index=True)
final_model = _catboost_model()
final_model.fit(_feature_matrix(final_train, FEATURE_COLUMNS), final_train[TARGET_COLUMN].astype(int))

ufc_test = split.test[split.test["source"] == "ufcstats"].reset_index(drop=True)
raw_test_probabilities = _probabilities(final_model, ufc_test, FEATURE_COLUMNS)
calibrated_test_probabilities = _isotonic_predict(calibrator, raw_test_probabilities)
```

Repository conventions to match:

- Model artifacts are written under `settings.data_dir / "models" / <name>`.
- Metrics are JSON with deterministic keys and primitive numeric values.
- Tests use small synthetic frames where possible, following `tests/test_model_calibration.py` and `tests/test_models.py`.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `uv run pytest tests/test_model_calibration.py tests/test_models.py` | exit 0 |
| Full tests | `uv run pytest` | exit 0 |
| Benchmark smoke | `uv run python -m mma_eff_lab benchmark-fight-models` | exit 0 and writes `data/models/fight_outcome_benchmarks.json` |

## Scope

**In scope**:

- `src/mma_eff_lab/models/benchmark.py`
- `src/mma_eff_lab/models/calibration.py`
- `src/mma_eff_lab/models/calibrated.py`
- `src/mma_eff_lab/__main__.py`
- tests under `tests/`

**Out of scope**:

- Data refresh, scraping, warehouse rebuilds, or raw cache mutation.
- Changing model target semantics.
- Betting/odds comparison.
- Frontend changes.

## Git Workflow

- Branch: `advisor/001-calibrated-walkforward-evaluation`.
- Commit message style should match repo history, e.g. `Add calibrated walk-forward evaluation`.
- Do not push unless the operator instructs it.

## Steps

### Step 1: Add A Reusable Expected Calibration Error Helper

Add an ECE helper in `src/mma_eff_lab/models/calibration.py`, near `_calibration_curve`, that accepts binary targets, probabilities, and bin count. It should return a float weighted by bin size. Empty bins should contribute zero. Keep behavior deterministic and use the same binning policy as `_calibration_curve`.

**Verify**: add tests in `tests/test_model_calibration.py` for perfect calibration and visibly miscalibrated probabilities, then run `uv run pytest tests/test_model_calibration.py` -> all pass.

### Step 2: Add Calibrated Fold Evaluation

Extend `benchmark.py` or add a small sibling module under `src/mma_eff_lab/models/` that evaluates folds as:

1. train model on older fold train window;
2. fit calibrator on a later validation slice inside that fold;
3. evaluate raw and calibrated probabilities on the fold test slice;
4. report overall and source-specific metrics.

Use the existing `_catboost_model`, `_feature_matrix`, `_probabilities`, `_probability_metrics`, and `_fit_calibrators` helpers instead of duplicating model code. The output must include at least:

- rows;
- accuracy;
- log_loss;
- brier_score;
- auc;
- expected_calibration_error;
- source-level metrics for `ufcstats` and `sherdog` when present;
- fold date boundaries.

**Verify**: add a unit test using a tiny synthetic dataset and a fake probability source if full CatBoost would make the test slow. Run `uv run pytest tests/test_model_calibration.py tests/test_models.py` -> all pass.

### Step 3: Expose A CLI Command

Add a command such as `evaluate-calibrated-walkforward` in `src/mma_eff_lab/__main__.py`. It should write a JSON report under `data/models/calibrated_walkforward/` by default. Support `--output-dir` and `--bins`; avoid adding many flags.

**Verify**: `uv run python -m mma_eff_lab evaluate-calibrated-walkforward --help` -> exits 0 and shows the new command.

### Step 4: Add Report Shape To Documentation Or Metadata Only If Necessary

If the report is not self-explanatory, add a short metadata section in the JSON itself. Do not edit broader docs in this plan unless the CLI would otherwise be undiscoverable.

**Verify**: run the command on the local dataset if available: `uv run python -m mma_eff_lab evaluate-calibrated-walkforward` -> exits 0 and writes JSON.

## Test Plan

- Unit test ECE behavior.
- Unit test fold output shape: fold count, raw/calibrated metric keys, source split keys.
- Smoke test the CLI help path.
- Run full `uv run pytest` before marking done.

## Done Criteria

- [ ] `uv run pytest tests/test_model_calibration.py tests/test_models.py` exits 0.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run python -m mma_eff_lab evaluate-calibrated-walkforward --help` exits 0.
- [ ] If local model data exists, `uv run python -m mma_eff_lab evaluate-calibrated-walkforward` exits 0 and writes a JSON report.
- [ ] The report includes raw and calibrated fold metrics, ECE, and source-specific metrics.
- [ ] No files outside the in-scope list are modified except generated ignored report output.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- Existing fold builders cannot support a validation slice without changing dataset semantics.
- CatBoost training makes the test suite unacceptably slow and no fake-model seam exists.
- The needed output requires refreshing external data.
- Any in-scope file has drifted materially from the excerpts above.

## Maintenance Notes

This report becomes the metric source for quality gating, model cards, and feature ablation. Keep its schema stable after plan 002 depends on it. Reviewers should scrutinize timestamp ordering and ensure no fold calibrator sees its own test window.
