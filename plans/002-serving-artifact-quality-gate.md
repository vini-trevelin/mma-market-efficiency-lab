# Plan 002: Validate The Serving Model Artifact

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- src/mma_eff_lab/models/quality.py src/mma_eff_lab/models/predict.py src/mma_eff_lab/models/calibrated.py tests data/models`

## Status

- **Priority**: P0
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/001-calibrated-walkforward-evaluation.md`
- **Category**: correctness / tests
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

`predict-fight` and `predict-card` default to `calibrated_ufc_catboost_v1`, but the current quality report still treats `xgboost_rating_features` as the primary model. That means the report can look healthy while the actual served model is missing, stale, schema-incompatible, or poorly calibrated. This plan aligns the quality gate with the serving path.

## Current State

Relevant excerpt:

```python
# src/mma_eff_lab/models/quality.py:199-230
primary = next(
    (
        item
        for item in benchmark.get("benchmarks", [])
        if item.get("name") == "xgboost_rating_features"
    ),
    None,
)
...
"primary_model": "xgboost_rating_features",
```

Serving path excerpt:

```python
# src/mma_eff_lab/models/predict.py:132-141
if model_version == CALIBRATED_CATBOOST_VERSION:
    bundle = load_calibrated_catboost(settings.data_dir / "models" / model_version)
    row = {feature: features.get(feature) for feature in FEATURE_COLUMNS}
    frame = pd.DataFrame([row], columns=FEATURE_COLUMNS)
    raw_probability = float(bundle.model.predict_proba(feature_matrix(frame))[:, 1][0])
    probability = float(bundle.calibrator.predict([raw_probability])[0])
    probability = min(max(probability, 0.0), 1.0)
```

Repository conventions:

- Quality checks return dictionaries with `name`, `status`, and `details`.
- Status values are currently `pass`, `warn`, or `fail`.
- Reports are written under `data/models/model_quality_report.json`.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `uv run pytest tests/test_models.py tests/test_model_calibration.py` | exit 0 |
| Full tests | `uv run pytest` | exit 0 |
| Quality gate | `uv run python -m mma_eff_lab validate-model-quality` | exit 0 and writes report |

## Scope

**In scope**:

- `src/mma_eff_lab/models/quality.py`
- `src/mma_eff_lab/models/calibrated.py`
- `src/mma_eff_lab/models/predict.py` only if a helper is needed for artifact loading checks.
- tests under `tests/`

**Out of scope**:

- Retraining the model.
- Changing prediction probabilities.
- Changing benchmark model training.
- Frontend/API changes.

## Git Workflow

- Branch: `advisor/002-serving-artifact-quality-gate`.
- Commit message example: `Validate calibrated serving model artifact`.
- Do not push unless instructed.

## Steps

### Step 1: Add Serving Artifact Presence And Load Checks

In `quality.py`, add a check that verifies the default serving model directory exists and contains:

- `model.cbm`;
- calibrator artifact;
- `metadata.json`;
- `metrics.json`.

If CatBoost is unavailable, return `warn` with a clear dependency reason rather than crashing. If files are missing, return `fail`.

**Verify**: unit test with a temporary model directory missing each required file -> status `fail`.

### Step 2: Validate Feature Schema Against Current Code

Read serving metadata and compare `metadata["feature_columns"]` with `FEATURE_COLUMNS`. Exact order should match because serving constructs frames with that order. Mismatch should be `fail`.

**Verify**: unit test temporary metadata with one missing feature and one reordered feature -> `fail`.

### Step 3: Validate Serving Metrics

Use the calibrated walk-forward report from plan 001 if present. If absent, fall back to `data/models/calibrated_ufc_catboost_v1/metrics.json` and report a `warn` that walk-forward calibrated metrics are missing.

Minimum checks:

- calibrated log loss exists;
- calibrated Brier score exists;
- row count is nonzero;
- metric values are finite;
- calibrated probability metrics are not catastrophically worse than raw metrics by a hard-coded conservative threshold, for example log loss degradation greater than `0.03` should be `warn`.

Do not fail just because accuracy is modest; accuracy is secondary here.

**Verify**: unit test metric dictionaries for pass/warn/fail cases.

### Step 4: Update Report Details

The quality report should include a new check name such as `serving_model_artifact`. Details should include:

- `model_version`;
- file paths checked;
- feature column count;
- metric source used;
- warnings if walk-forward report is missing.

**Verify**: `uv run python -m mma_eff_lab validate-model-quality` -> report includes the new check.

## Test Plan

- Unit tests for missing files, bad metadata schema, invalid metrics, and successful check.
- Existing model tests should still pass.
- Run full test suite.

## Done Criteria

- [ ] `uv run pytest tests/test_models.py tests/test_model_calibration.py` exits 0.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run python -m mma_eff_lab validate-model-quality` exits 0.
- [ ] Report includes `serving_model_artifact` or equivalent serving-model check.
- [ ] The check names `calibrated_ufc_catboost_v1` as the served model.
- [ ] No model retraining or data refresh was performed.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- The serving model version is no longer `calibrated_ufc_catboost_v1`.
- Plan 001 changed the calibrated metric report schema and it is not obvious how to consume it.
- Loading the model requires a native dependency unavailable in the execution environment and no warn-only path can be implemented cleanly.

## Maintenance Notes

When a future model becomes the default serving model, this quality gate must follow it. Reviewers should check that quality validation does not silently validate a non-serving benchmark.
