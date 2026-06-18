# Plan 008: Replace Pickle Calibrator Serialization

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- src/mma_eff_lab/models/calibrated.py src/mma_eff_lab/models/predict.py tests data/models`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/002-serving-artifact-quality-gate.md` preferred
- **Category**: security / tech-debt
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

The calibrated serving artifact stores the isotonic calibrator with pickle. That is acceptable for a local experiment, but unsafe as a general artifact format because loading pickle can execute arbitrary code if the file is untrusted. A portfolio repo should avoid that footgun when the calibrator can be represented as plain numeric thresholds.

## Current State

Relevant excerpt:

```python
# src/mma_eff_lab/models/calibrated.py:1-5
import json
import pickle
```

```python
# src/mma_eff_lab/models/calibrated.py:87-95
output = output_dir or settings.data_dir / "models" / CALIBRATED_CATBOOST_VERSION
model_path = output / "model.cbm"
calibrator_path = output / "isotonic_calibrator.pkl"
...
with calibrator_path.open("wb") as handle:
    pickle.dump(calibrator, handle)
```

```python
# src/mma_eff_lab/models/calibrated.py:125-133
model = CatBoostClassifier()
model.load_model(model_dir / "model.cbm")
with (model_dir / "isotonic_calibrator.pkl").open("rb") as handle:
    calibrator = pickle.load(handle)
```

Scikit-learn `IsotonicRegression` exposes fitted threshold arrays such as `X_thresholds_` and `y_thresholds_`, which can be serialized as JSON and evaluated with interpolation.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `uv run pytest tests/test_model_calibration.py tests/test_models.py` | exit 0 |
| Full tests | `uv run pytest` | exit 0 |
| Calibrated training smoke | `uv run python -m mma_eff_lab train-calibrated-ufc-catboost` | exit 0 |

## Scope

**In scope**:

- `src/mma_eff_lab/models/calibrated.py`
- `src/mma_eff_lab/models/calibration.py` only if interpolation helper belongs there.
- tests under `tests/`

**Out of scope**:

- Changing CatBoost model serialization.
- Changing calibration method from isotonic to another method.
- Retuning model hyperparameters.
- Any broad artifact policy; that belongs to plan 005.

## Git Workflow

- Branch: `advisor/008-safe-calibrator-serialization`.
- Commit message example: `Serialize isotonic calibrator without pickle`.
- Do not push unless instructed.

## Steps

### Step 1: Add JSON Calibrator Representation

Create helper functions for isotonic calibrators:

- `serialize_isotonic_calibrator(calibrator) -> dict`;
- `load_isotonic_calibrator_payload(payload) -> callable object or lightweight dataclass`.

The payload must include:

- `kind`: `isotonic`;
- `x_thresholds`;
- `y_thresholds`;
- clipping policy for values outside the fitted range.

Use linear interpolation matching scikit-learn isotonic predictions. Clamp final output to `[0.0, 1.0]`.

**Verify**: unit test compares helper predictions with scikit-learn isotonic predictions on representative probabilities.

### Step 2: Write JSON Instead Of Pickle

Change training output from `isotonic_calibrator.pkl` to `isotonic_calibrator.json`. Update metadata paths accordingly.

Keep a short backwards-compatible loader only if existing local artifacts need to remain loadable. If backwards compatibility is added, it must warn or clearly mark pickle as legacy and never prefer pickle when JSON exists.

**Verify**: targeted tests pass.

### Step 3: Remove Pickle Import From Normal Path

Remove `import pickle` if no legacy fallback remains. If a legacy fallback remains, isolate it in a clearly named private function and document that it is only for old local artifacts.

**Verify**: `rg -n "pickle" src/mma_eff_lab/models` shows no usage, or only the explicit legacy fallback.

### Step 4: Update Quality Gate Expectations If Plan 002 Landed

If `serving_model_artifact` checks for `isotonic_calibrator.pkl`, update it to expect JSON. If both legacy and JSON are supported, the quality gate should prefer JSON and warn on pickle-only artifacts.

**Verify**: `uv run python -m mma_eff_lab validate-model-quality` exits 0 if local artifacts are compatible.

## Test Plan

- Unit test JSON serializer payload shape.
- Unit test JSON-loaded calibrator matches original isotonic predictions within tight tolerance.
- Unit test prediction code uses JSON calibrator.
- Full test suite.

## Done Criteria

- [ ] `uv run pytest tests/test_model_calibration.py tests/test_models.py` exits 0.
- [ ] `uv run pytest` exits 0.
- [ ] `rg -n "pickle" src/mma_eff_lab/models` returns no normal-path usage.
- [ ] Newly trained calibrated artifacts write `isotonic_calibrator.json`.
- [ ] Predictions before/after serialization match within tolerance.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- Scikit-learn isotonic internals differ from expected threshold attributes.
- Prediction parity cannot be achieved within floating-point tolerance.
- Existing serving artifacts must remain loadable but no safe migration path is acceptable to the operator.

## Maintenance Notes

Avoid adding new pickle artifacts in future model code. If a model library only supports binary formats, keep them separated from arbitrary Python object serialization and record the artifact trust boundary in the model card.
