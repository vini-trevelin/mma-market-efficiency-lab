# Plan 004: Vectorize Card Prediction Serving

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- src/mma_eff_lab/models/predict.py src/mma_eff_lab/features/pit.py tests`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/002-serving-artifact-quality-gate.md`, `plans/003-swapped-input-invariance.md`
- **Category**: perf / architecture
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

`predict-card` currently predicts each fight independently. Each row resolves fighters, rebuilds future matchup context from the full warehouse, and reloads the model. That is acceptable for a smoke test but weak for a portfolio demo where a whole event card should be fast, deterministic, and diagnosable.

## Current State

Card prediction loop:

```python
# src/mma_eff_lab/models/predict.py:90-111
predictions = [
    predict_fight(
        str(row["fighter_a"]),
        str(row["fighter_b"]),
        pd.to_datetime(row["event_date"]).date(),
        model_version,
        settings,
    )
    for row in card.to_dict("records")
]
```

Future feature builder:

```python
# src/mma_eff_lab/features/pit.py:127-145
with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
    base = conn.execute(_base_query()).fetchdf()
...
base = _add_pre_fight_ratings(base)
ratings, last_fight_dates = _rating_snapshot(base, event_date)
```

This means a 10-fight card can repeat the same base query, rating reconstruction, and model loading 10 times.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `uv run pytest tests/test_models.py` | exit 0 |
| Full tests | `uv run pytest` | exit 0 |
| CLI help | `uv run python -m mma_eff_lab predict-card --help` | exit 0 |

## Scope

**In scope**:

- `src/mma_eff_lab/models/predict.py`
- `src/mma_eff_lab/features/pit.py`
- tests under `tests/`

**Out of scope**:

- Model retraining.
- Warehouse schema changes.
- Frontend/API optimization.
- External data refresh.

## Git Workflow

- Branch: `advisor/004-vectorized-card-serving`.
- Commit message example: `Vectorize card prediction serving`.
- Do not push unless instructed.

## Steps

### Step 1: Add A Batch Future Feature Builder

Add a function in `features/pit.py` that accepts a list of `(fighter_a_id, fighter_b_id, event_date)` rows and returns one feature dict per row. It must:

- query the base warehouse table once;
- compute pre-fight ratings once per unique event date or once globally and snapshot per date;
- query fighter metadata for all unique fighters in one query;
- preserve the same feature names and values as `build_future_matchup_features` for a single row.

Keep the existing single-row function as a wrapper around the batch function if that keeps behavior aligned.

**Verify**: add a test comparing one-row batch output to current single-row output on fixture data.

### Step 2: Load The Model Once Per Card

Refactor `predict_card` so it:

- reads and validates the CSV once;
- resolves all fighter names/IDs once;
- builds all feature rows in one batch;
- loads the model bundle once;
- scores all rows in one model call where possible.

Do not change the output CSV columns unless needed for diagnostics.

**Verify**: existing prediction tests pass.

### Step 3: Add A Performance Regression Smoke Test

Add a small unit test with monkeypatched builders/loaders counting calls. It should assert that for a multi-row card:

- model load count is `1`;
- base feature build count is `1` batch call, not N single calls.

Avoid wall-clock assertions in unit tests; call counts are more stable.

**Verify**: `uv run pytest tests/test_models.py -k card` -> passes.

## Test Plan

- One-row batch output equals single-row output.
- Multi-row card uses one batch feature build and one model load.
- Probability contract tests from plan 003 still pass.
- Full test suite passes.

## Done Criteria

- [ ] `uv run pytest tests/test_models.py` exits 0.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run python -m mma_eff_lab predict-card --help` exits 0.
- [ ] Multi-row card prediction no longer calls `predict_fight` once per row.
- [ ] Output CSV remains backwards-compatible.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- Batch feature generation cannot match single-row feature values.
- A correct implementation requires warehouse schema changes.
- The model API cannot score a dataframe without changing probability semantics.

## Maintenance Notes

Future model versions should expose a batch scoring path first. Reviewers should compare one-row and batch outputs carefully to avoid subtle point-in-time differences.
