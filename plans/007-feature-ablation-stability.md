# Plan 007: Add Feature Ablation And Stability Reports

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- src/mma_eff_lab/models tests data/models`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/001-calibrated-walkforward-evaluation.md`
- **Category**: direction / tests
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

The current richer feature set improves some probability metrics, but gains are modest and not uniformly better by every headline metric. A serious quant workflow needs to show which feature groups help, which are unstable, and whether improvements survive time-based validation. This plan adds ablation reporting before adding more model complexity.

## Current State

Current benchmark summary from `data/models/fight_outcome_benchmarks.json`:

```text
baseline_xgboost temporal test: accuracy 0.6355, log_loss 0.6512, Brier 0.2297, AUC 0.6632
xgboost_rating_features temporal test: accuracy 0.6268, log_loss 0.6471, Brier 0.2279, AUC 0.6671
catboost_rating_features temporal test: accuracy 0.6299, log_loss 0.6459, Brier 0.2272, AUC 0.6724

xgboost_rating_features walk-forward: log_loss 0.6497, AUC 0.6632
catboost_rating_features walk-forward: log_loss 0.6499, AUC 0.6622
```

Feature groups are currently implicit in `FEATURE_COLUMNS`, including:

- prior record/count features;
- biometric features;
- historical rate stats;
- Elo/rating features;
- opponent-quality features;
- recent-form features.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `uv run pytest tests/test_models.py` | exit 0 |
| Full tests | `uv run pytest` | exit 0 |
| Benchmark smoke | `uv run python -m mma_eff_lab benchmark-fight-models` | exit 0 |

## Scope

**In scope**:

- `src/mma_eff_lab/models/benchmark.py`
- `src/mma_eff_lab/models/dataset.py` only if feature group constants belong there.
- tests under `tests/`

**Out of scope**:

- Adding new raw features.
- Hyperparameter search.
- Betting/odds comparison.
- Changing default served model.

## Git Workflow

- Branch: `advisor/007-feature-ablation-stability`.
- Commit message example: `Add feature ablation benchmarks`.
- Do not push unless instructed.

## Steps

### Step 1: Define Named Feature Groups

Add explicit feature-group constants using existing `FEATURE_COLUMNS`. Suggested groups:

- `record`: prior fights, wins, losses, draws, no-contests, win method counts;
- `activity_bio`: days since last fight, age, height, reach;
- `ufcstats_rates`: significant strikes, takedowns, submissions, control, per-minute/per-15 rates;
- `rating`: pre-fight Elo, time-decayed Elo, expected win probability, uncertainty/RD;
- `opponent_quality`: average/recent/best/worst opponent rating features;
- `recent_form`: recent 3 and recent 5 win rates.

Every feature in `FEATURE_COLUMNS` must belong to exactly one group.

**Verify**: unit test asserts group union equals `FEATURE_COLUMNS` and no duplicates exist.

### Step 2: Add Ablation Specs

Extend benchmark specs to include:

- baseline existing feature set;
- rating-only;
- no-rating;
- no-UFCStats-rate;
- record + activity only;
- all features.

Keep the number of specs small enough that local runtime remains reasonable. Do not add broad hyperparameter search.

**Verify**: unit test benchmark spec names and feature counts.

### Step 3: Add Stability Summary

For each ablation spec, report:

- temporal test metrics;
- walk-forward summary metrics;
- per-fold log loss and Brier;
- source-specific metrics where available;
- delta versus baseline for log loss and Brier.

Rank by walk-forward log loss primarily, Brier secondarily.

**Verify**: report JSON includes `ablation_summary` or equivalent with sorted specs.

### Step 4: Add Optional Human-Readable Summary

If simple, write a Markdown summary next to the JSON. It should state which feature groups helped and which degraded. Keep it factual; do not oversell accuracy.

**Verify**: generated Markdown contains each ablation spec name.

## Test Plan

- Test feature group coverage and no duplicates.
- Test ablation spec construction.
- Test summary ranking uses log loss before accuracy.
- Run full tests.

## Done Criteria

- [ ] `uv run pytest tests/test_models.py` exits 0.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run python -m mma_eff_lab benchmark-fight-models` exits 0.
- [ ] Benchmark report includes named ablation specs and deltas.
- [ ] Every feature belongs to exactly one feature group.
- [ ] No new model family or hyperparameter search was introduced.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- Benchmark runtime becomes impractically long.
- Feature columns changed so much that grouping cannot be done confidently.
- Ablation requires changing dataset generation semantics.

## Maintenance Notes

Use this report before adding new features. Reviewers should reject feature additions that do not improve walk-forward log loss/Brier or at least explain why they remain useful.
