# Plan 005: Define Generated Artifact And Data Version Policy

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- .gitignore docs/repository-guide.md data plans`

## Status

- **Priority**: P0
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: dx / docs / tech-debt
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

The repo currently tracks generated model artifacts, prediction CSVs, plots, and binary files under `data/`. That conflicts with the local-generated-data story and makes reviews noisy. A quant-dev portfolio should clearly separate reproducible source code and small reference reports from generated artifacts that can be rebuilt or versioned externally.

## Current State

Current `.gitignore` ignores some generated data but not all:

```gitignore
# .gitignore
data/raw/
data/warehouse/
data/reports/
data/logs/
```

Tracked generated artifacts currently include:

```text
data/models/calibrated_ufc_catboost_v1/isotonic_calibrator.pkl
data/models/calibrated_ufc_catboost_v1/model.cbm
data/models/calibration/*.png
data/models/fight_outcome_benchmarks.json
data/predictions/ufc_freedom_250_predictions.csv
data/predictions/ufc_freedom_250_polymarket_comparison.csv
data/upcoming/ufc_freedom_250_card.csv
```

Repository docs define a local refresh flow in `docs/repository-guide.md`, including:

```text
# docs/repository-guide.md:120-138
uv run python -m mma_eff_lab download-ufcstats
...
uv run python -m mma_eff_lab validate-model-quality
uv run python -m mma_eff_lab validate-warehouse
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Inspect tracked data | `git ls-files data` | prints current tracked artifacts |
| Check ignore rules | `git check-ignore -v <path>` | exits 0 for ignored generated paths |
| Full tests | `uv run pytest` | exit 0 |

## Scope

**In scope**:

- `.gitignore`
- `docs/repository-guide.md`
- optional small artifact manifest under `data/` or `docs/` if needed
- removing generated tracked files from Git index if the operator explicitly approves that during execution

**Out of scope**:

- Deleting local files from disk unless explicitly requested.
- Rebuilding model artifacts.
- Introducing DVC/Git LFS unless the operator explicitly chooses that heavier path.
- Changing model code.

## Git Workflow

- Branch: `advisor/005-artifact-data-version-policy`.
- Commit message example: `Document generated artifact policy`.
- Do not push unless instructed.

## Steps

### Step 1: Choose The Minimal Policy

Use this default unless the operator overrides it:

- Git tracks source code, tests, docs, plans, tiny hand-written fixtures, and stable metadata examples.
- Git does not track generated model binaries, calibrators, prediction CSVs, generated plots, raw HTML, DuckDB files, or local reports.
- If a generated metric report is important for portfolio documentation, keep a small curated copy under `docs/` or a future `reports/` path, not live `data/models/`.

Write this policy in `docs/repository-guide.md` near the data/source rules.

**Verify**: `rg -n "artifact|generated|data/" docs/repository-guide.md .gitignore` shows the new policy.

### Step 2: Update Ignore Rules

Update `.gitignore` so generated paths are ignored consistently:

- `data/models/`
- `data/predictions/`
- `data/upcoming/`

Keep existing ignores for raw, warehouse, reports, and logs.

**Verify**: `git check-ignore -v data/models/example/model.cbm data/predictions/example.csv data/upcoming/example.csv` exits 0 and shows `.gitignore` rules.

### Step 3: Decide How To Handle Already Tracked Generated Files

If the operator has approved index cleanup, remove tracked generated artifacts from the index with `git rm --cached` while leaving local files on disk. If approval is not explicit, stop after documenting the policy and list the files that need cleanup.

Recommended cleanup list comes from:

```bash
git ls-files data
```

Do not delete the local artifact files unless explicitly requested.

**Verify**: after approved cleanup, `git ls-files data` should be empty or contain only intentionally curated examples.

### Step 4: Add Reproduction Instructions

Update `docs/repository-guide.md` with a concise instruction that generated artifacts are recreated by:

```bash
uv run python -m mma_eff_lab build-model-dataset
uv run python -m mma_eff_lab train-xgboost-model
uv run python -m mma_eff_lab train-calibrated-ufc-catboost
uv run python -m mma_eff_lab benchmark-fight-models
uv run python -m mma_eff_lab evaluate-model-calibration --source ufcstats
uv run python -m mma_eff_lab validate-model-quality
```

Do not run these commands in this plan unless the operator asks for regeneration.

## Test Plan

- Ignore-rule checks for representative generated paths.
- Documentation search to confirm policy is discoverable.
- Full tests only if source code changed; otherwise not required but allowed.

## Done Criteria

- [ ] `.gitignore` ignores generated model, prediction, and upcoming-card artifacts.
- [ ] `docs/repository-guide.md` states what is tracked vs generated.
- [ ] Already tracked generated files are either removed from the index with approval or explicitly listed as pending cleanup.
- [ ] No local generated files are deleted without explicit approval.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- The operator wants DVC/Git LFS instead of simple ignore rules.
- Tracked artifacts are required by tests and no fixture replacement exists.
- Cleaning the Git index would remove files outside `data/models`, `data/predictions`, or `data/upcoming`.

## Maintenance Notes

This policy should be revisited before publishing the repo publicly. Reviewers should reject commits that add generated binary artifacts unless the artifact policy explicitly allows them.
