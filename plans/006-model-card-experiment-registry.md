# Plan 006: Add Model Cards And Experiment Registry

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- src/mma_eff_lab/models src/mma_eff_lab/__main__.py tests data/models docs`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/001-calibrated-walkforward-evaluation.md`, `plans/005-artifact-data-version-policy.md`
- **Category**: docs / dx / direction
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

The repo has useful metrics and metadata, but they are scattered across model directories and benchmark reports. A portfolio reviewer should be able to answer: what model is served, what data trained it, what commit produced it, what metrics justify it, and what limitations apply. A model card and lightweight experiment registry make the work auditable.

## Current State

Existing artifact sources:

- `data/models/calibrated_ufc_catboost_v1/metadata.json` contains model version, model type, calibration, feature columns, dataset metadata, and split rows.
- `data/models/calibrated_ufc_catboost_v1/metrics.json` contains raw and isotonic UFCStats test metrics.
- `data/models/fight_outcome_benchmarks.json` contains benchmark specs and walk-forward summaries.
- No single model-card artifact ties those together with code commit, dataset hash, intended use, limitations, and source caveats.

Relevant metadata writer:

```python
# src/mma_eff_lab/models/calibrated.py:96-115
metadata = {
    "model_version": CALIBRATED_CATBOOST_VERSION,
    "created_at_utc": datetime.now(UTC).isoformat(),
    "model_type": "catboost",
    "calibration": "isotonic",
    "calibration_source": "ufcstats",
    "feature_columns": FEATURE_COLUMNS,
    "target_column": TARGET_COLUMN,
    "probability_contract": "fighter_b_win_probability = 1 - fighter_a_win_probability",
    "dataset": dataset.metadata,
    "split": {...},
}
metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `uv run pytest tests/test_models.py tests/test_model_calibration.py` | exit 0 |
| Full tests | `uv run pytest` | exit 0 |
| CLI help | `uv run python -m mma_eff_lab --help` | exit 0 |

## Scope

**In scope**:

- new model-card/registry code under `src/mma_eff_lab/models/`
- `src/mma_eff_lab/__main__.py`
- tests under `tests/`
- optional docs pointer in `docs/repository-guide.md`

**Out of scope**:

- Changing model training objective.
- Moving generated artifacts; that belongs to plan 005.
- Frontend display of model cards.
- Betting/odds documentation.

## Git Workflow

- Branch: `advisor/006-model-card-experiment-registry`.
- Commit message example: `Add model card registry`.
- Do not push unless instructed.

## Steps

### Step 1: Define The Model Card Schema

Create a small schema as a Python dictionary or dataclass. It must include:

- `model_version`;
- `created_at_utc`;
- `code_commit`;
- `dataset_date_min` and `dataset_date_max`;
- row counts and excluded draw/no-contest counts;
- feature column count and feature set name;
- source coverage caveats;
- probability contract;
- training, validation, test windows;
- metrics summary from calibrated holdout and calibrated walk-forward if present;
- intended use: historical/future fight win-probability research;
- not intended use: betting automation, medical/athlete safety decisions, claims of certainty.

Keep the first version JSON-first. A Markdown rendering is useful but secondary.

**Verify**: unit test schema contains all required top-level keys.

### Step 2: Add A Registry Writer

Add a command or helper that reads existing metadata/metrics and writes:

- `data/models/model_cards/<model_version>.json`;
- optionally `data/models/model_cards/<model_version>.md`;
- `data/models/experiments.json` listing available model cards.

If plan 005 has moved generated reports out of Git, these outputs should remain generated and ignored.

**Verify**: command runs against existing local artifacts without retraining.

### Step 3: Capture Code Commit Safely

Use `git rev-parse --short HEAD` through a small helper, but handle non-Git environments by writing `unknown`. Do not fail model-card generation just because Git metadata is unavailable.

**Verify**: unit test monkeypatches the helper and confirms the value appears in output.

### Step 4: Wire CLI

Add `write-model-card` or `write-model-cards` to `src/mma_eff_lab/__main__.py`. Keep flags minimal:

- `--model-version`, default `calibrated_ufc_catboost_v1`;
- `--output-dir`, optional.

**Verify**: `uv run python -m mma_eff_lab write-model-card --help` exits 0.

## Test Plan

- Unit test required schema keys.
- Unit test missing optional benchmark report produces a warning field instead of crashing.
- CLI help smoke test.
- Full test suite.

## Done Criteria

- [ ] `uv run pytest tests/test_models.py tests/test_model_calibration.py` exits 0.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run python -m mma_eff_lab write-model-card --help` exits 0.
- [ ] Generated model card includes commit, dataset window, metrics, intended use, and limitations.
- [ ] No model retraining or data refresh is required.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- The artifact policy from plan 005 forbids writing model cards under `data/models`.
- Required metadata files are absent and cannot be regenerated without training.
- The registry would need to parse binary model files directly.

## Maintenance Notes

Every new served model should get a model card before it becomes the default. Reviewers should check that limitations are honest and that metrics point to temporal or walk-forward evaluations, not random splits.
