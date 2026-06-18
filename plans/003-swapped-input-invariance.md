# Plan 003: Enforce Swapped-Input Probability Invariance

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the STOP conditions occurs, stop and report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 7378ca3..HEAD -- src/mma_eff_lab/models src/mma_eff_lab/features tests docs/model-research.md tasks/todo.md`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/002-serving-artifact-quality-gate.md` preferred
- **Category**: correctness / tests
- **Planned at**: commit `7378ca3`, 2026-06-13

## Why This Matters

The public probability contract says `P(fighter_b wins) = 1 - P(fighter_a wins)`. That contract is true inside one prediction response, but tree models do not guarantee that separately calling `(A, B)` and `(B, A)` gives complementary probabilities. A portfolio-grade probability API must either enforce canonical orientation at serving time or prove the reverse call is close enough.

## Current State

Research doc excerpt:

```text
# docs/model-research.md:137-145
For swapped inputs, the ideal behavior is:
f(features_b_minus_a) = -f(features_a_minus_b)
Linear logistic regression on pure delta features has this anti-symmetry naturally.
Tree/ensemble models do not guarantee it automatically, so they need swapped-row
training and an explicit swapped-input invariance test.
```

Task note excerpt:

```text
# tasks/todo.md:298-301
Probability contract:
- produce one ordered-pair scalar P(fighter_a wins);
- set P(fighter_b wins) = 1 - P(fighter_a wins);
- enforce or test swapped-input invariance before trusting probabilities.
```

Current test only checks one response sums to one:

```python
# tests/test_models.py:149-157
prediction = predict_fight_probability(_ConstantModel(), features, model_version="test")
assert prediction.fighter_a_win_probability == 0.65
assert prediction.fighter_b_win_probability == 0.35
assert prediction.fighter_a_win_probability + prediction.fighter_b_win_probability == 1.0
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `uv run pytest tests/test_models.py` | exit 0 |
| Full tests | `uv run pytest` | exit 0 |
| Prediction smoke | `uv run python -m mma_eff_lab predict-fight --help` | exit 0 |

## Scope

**In scope**:

- `src/mma_eff_lab/models/predict.py`
- `src/mma_eff_lab/models/dataset.py` only if feature orientation helpers need reuse.
- `tests/test_models.py`

**Out of scope**:

- Retraining model artifacts.
- Changing the model target.
- Adding odds or betting logic.
- Broad documentation rewrites.

## Git Workflow

- Branch: `advisor/003-swapped-input-invariance`.
- Commit message example: `Enforce swapped input probability contract`.
- Do not push unless instructed.

## Steps

### Step 1: Define The Serving Policy In Code

Implement a single serving policy:

- Resolve both fighter IDs.
- Build prediction features in the user-requested order for response names.
- Ensure the returned two probabilities always sum to one.
- Add an internal helper that can evaluate a reverse-order row for diagnostics without changing the public response shape.

Do not expose two independently computed probabilities as the API contract. The response should still use one scalar and its complement.

**Verify**: `uv run pytest tests/test_models.py` -> existing probability contract test still passes.

### Step 2: Add A Swapped Diagnostic Test

Add a deterministic fake model whose probability changes when delta signs are flipped. Use it to prove the serving helper either:

- canonicalizes orientation and maps probability back to the requested order; or
- flags reverse-call non-complementarity in diagnostics.

The test must assert a numerical tolerance, for example `abs(p_ab + p_ba - 1.0) <= 1e-6` for the enforced serving path.

**Verify**: `uv run pytest tests/test_models.py -k swapped` -> new test passes.

### Step 3: Add Optional Runtime Diagnostic Metadata

If easy and low-risk, include `swapped_probability_gap` in feature coverage diagnostics when both orientations are evaluated. If evaluating both orientations is expensive, skip runtime diagnostics and keep this as a test-only check.

**Verify**: targeted tests still pass.

## Test Plan

- Test single-call probabilities still sum to one.
- Test swapped pair complement behavior.
- Test diagnostic gap when a fake asymmetric model is used.
- Run full test suite.

## Done Criteria

- [ ] `uv run pytest tests/test_models.py` exits 0.
- [ ] `uv run pytest` exits 0.
- [ ] A swapped-input invariant test exists and fails against naive independent reverse predictions.
- [ ] Public prediction response still returns exactly one `fighter_a_win_probability` and one complement.
- [ ] No model artifact retraining was performed.
- [ ] `plans/README.md` status row updated.

## STOP Conditions

Stop and report if:

- Enforcing canonical orientation would require changing user-visible fighter labels.
- The live model feature builder cannot produce reverse features without expensive warehouse rebuilds.
- Any fix would require changing the dataset label semantics.

## Maintenance Notes

If future training emits both orientations as training rows, keep this serving test anyway. It protects the API contract from model-family changes.
