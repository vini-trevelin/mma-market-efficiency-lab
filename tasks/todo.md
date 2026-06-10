# Task Log

# XGBoost Fight Outcome Model V1

## Plan

- [x] Add model dependencies for real XGBoost training and metrics.
- [x] Implement deterministic leak-resistant model dataset builder.
- [x] Implement XGBoost training, temporal split metrics, and artifact writing.
- [x] Implement prediction helper with complement probability contract.
- [x] Add focused tests for dataset labels, leakage guardrails, temporal split, and probability contract.
- [x] Run relevant tests and record verification.

## Review / Results

- Added real `xgboost` and `scikit-learn` dependencies.
- Added model commands:
  - `build-model-dataset`
  - `train-xgboost-model`
- Added model modules:
  - deterministic binary dataset builder from `pit_matchup_features`;
  - XGBoost trainer using `binary:logistic`;
  - temporal date-based train/validation/test split;
  - metrics for log loss, Brier score, AUC, accuracy, and source-stratified test metrics;
  - prediction helper returning `P(fighter_a wins)` and `P(fighter_b wins) = 1 - P(fighter_a wins)`.
- Live dataset smoke:
  - input rows: `17,487`;
  - binary training rows: `17,196`;
  - excluded draw/no-contest rows: `291`;
  - label balance: `8,238` fighter A wins, `8,958` fighter B wins.
- Verification:
  - `uv run pytest tests/test_models.py` passed (`5` tests).
  - `uv run ruff check src tests` passed.
  - `uv run pytest` passed (`42` tests).
- Environment note:
  - XGBoost import is installed but local macOS runtime is missing `libomp.dylib`.
  - Actual training command exits with a clear message to run `brew install libomp`.

# Fight Outcome Model Research V1

## Plan

- [x] Confirm the research branch name is `research-fight-model`.
- [x] Inspect current PIT feature tables and label/corner behavior.
- [x] Review external MMA outcome-prediction and paired-comparison sources.
- [x] Write a research note with recommended modeling path, evaluation rules, and risks.
- [x] Record immediate implementation questions before modeling work starts.
- [x] Clarify probability-complement contract and SOTA model candidates.

## Review / Results

- Branch is `research-fight-model`.
- Current modeling table size:
  - `pit_matchup_features`: `17,487` fights.
  - Latest source event date is `2026-06-06` for both UFCStats and Sherdog.
- Current PIT feature coverage:
  - Sherdog fighter rows: `17,548`; prior-history coverage `65.5%`; age/height `88.3%`; reach `14.8%`; detailed stat history `9.7%`.
  - UFCStats fighter rows: `17,426`; prior-history coverage `86.9%`; age `99.2%`; height `99.9%`; reach `92.4%`; detailed stat history `84.2%`.
- Critical label/corner risk:
  - Sherdog red corner win rate is `98.45%`, because the source/parser side is effectively winner-first.
  - UFCStats red corner win rate is `63.03%`, consistent with known red-corner bias and/or assignment effects.
  - First model dataset must randomize or symmetrize fighter order and must not treat `red` as a causal feature.
- Research note created in `docs/model-research.md`.
- Recommended first build:
  - create a model dataset builder from `pit_matchup_features` plus labels;
  - exclude draw/no-contest rows for MVP binary prediction;
  - emit side-swapped or randomized rows;
  - start with regularized logistic regression and rating baselines;
  - compare against calibrated gradient boosting only after leakage checks pass.
- Probability contract:
  - produce one ordered-pair scalar `P(fighter_a wins)`;
  - set `P(fighter_b wins) = 1 - P(fighter_a wins)`;
  - enforce or test swapped-input invariance before trusting probabilities.
- SOTA scan:
  - strongest MMA-specific published direction is Bayesian skill estimation plus
    Markov-chain fight simulation;
  - strongest practical MVP path is dynamic Bradley-Terry/Elo-style rating
    features plus calibrated logistic regression;
  - tabular ensembles/XGBoost/style clusters are candidates after the leak-free
    baseline is measured.

# Live Data Refresh and Main Commit

## Plan

- [x] Review repo workflow docs and current warehouse recency.
- [x] Clean up the active task log and move old completed work out of `tasks/todo.md`.
- [x] Attempt live UFCStats and Sherdog refreshes and record any source-side blockers.
- [x] Rebuild parsed tables, warehouse, features, and audit outputs from the refreshed cache.
- [x] Verify that the warehouse moved forward cleanly and record any residual warnings or failures.
- [x] Commit the current documentation/task cleanup and successful refresh work to `main`.

## Review / Results

- Current warehouse recency before refresh:
  - `events.max(event_date) = 2026-05-16`
  - `source_events.max(event_date)` for `ufcstats` = `2026-05-16`
  - `source_events.max(event_date)` for `sherdog` = `2026-05-15`
- `tasks/todo.md` stayed as the single active log, and `docs/task-history.md` was removed.
- Live-source refresh findings:
  - `download-ufcstats` does not refresh the root events index unless `force` is enabled, so a broad missing-only run walks the full cache instead of only new events.
  - A direct live `http://ufcstats.com/statistics/events/completed?page=all` request returned `200` but served a browser-check page to plain HTTP clients in this environment.
  - `download-sherdog` discovered newer events, but the newest uncached event pages returned `403` on download.
- Browser-assisted UFC refresh completed:
  - The live UFCStats page shows `UFC Fight Night: Muhammad vs. Bonfim` on `2026-06-06`, event id `ba17afef01ed78b6`.
  - The June 6 UFC event page, its `12` fight detail pages, and its `24` fighter pages were written into the local UFCStats raw cache.
- Sherdog sweep status:
  - Cached Sherdog organization pages currently expose newer completed events than the warehouse:
    - `Rizin Fighting Federation`: `2026-06-06` (`111986`, `Rizin FF - Landmark Vol. 14`)
    - `Professional Fighters League`: `2026-05-23` (`111953`, `PFL Brussels: Habirora vs. Henderson`)
    - `One Championship`: `2026-05-22` (`112347`, `One Friday Fights 155`)
  - Those event detail pages are still blocked behind Cloudflare/browser verification, so they could not be added to the warehouse from this environment.
- Rebuild and verification completed:
  - `uv run python -m mma_eff_lab parse-ufcstats` passed.
  - `uv run python -m mma_eff_lab build-warehouse` passed.
  - `uv run python -m mma_eff_lab build-features` passed.
  - `uv run python -m mma_eff_lab validate-warehouse` passed.
  - `curl http://127.0.0.1:8000/health` passed.
- Warehouse moved forward after rebuild:
  - `source_events`: `1954 -> 1956`
  - `source_fights`: `17447 -> 17459`
  - `source_fight_participants`: `34894 -> 34918`
  - `source_fighters`: `9278 -> 9279`
  - latest `ufcstats` event date: `2026-05-16 -> 2026-06-06`
  - latest `sherdog` event date remained `2026-05-15`
  - latest canonical event now present: `UFC Fight Night: Muhammad vs. Bonfim` on `2026-06-06`
- Current non-pass audit state after rebuild:
  - `fail`: `fighter_identity_manual_overrides.schema_types_match`
  - `warn`: unresolved Sherdog identities (`5729`)
  - `warn`: quarantined rows (`2`)
