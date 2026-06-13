# Task Log

# UFC-Focused Probability Improvements

## Plan

- [x] Add richer point-in-time features for UFC probability modeling.
- [x] Add UFC/source-filtered calibration evaluation with reliability plots.
- [x] Add future `predict-fight` and `predict-card` commands.
- [x] Re-run full model/data quality verification after the expanded feature surface.
- [x] Use live sources to identify the UFC White House card and Polymarket markets.

## Review / Results

- Added point-in-time feature families:
  - time-decayed Elo;
  - Glicko-like rating deviation proxy;
  - opponent-quality Elo features;
  - normalized per-minute and per-15-minute fight stat rates.
- Rebuilt model dataset:
  - training rows: `17,541`;
  - excluded draw/no-contest rows: `297`;
  - feature columns: `36`.
- Expanded raw XGBoost temporal test metrics:
  - overall accuracy `62.68%`, log loss `0.6471`, AUC `0.6671`;
  - UFCStats accuracy `62.94%`, log loss `0.6464`, AUC `0.6754`.
- Expanded benchmark, UFCStats temporal test:
  - baseline XGBoost AUC `0.6801`;
  - XGBoost expanded features AUC `0.6754`;
  - CatBoost expanded features AUC `0.6850`.
- UFCStats calibration report:
  - XGBoost raw log loss `0.6464`, Platt `0.6469`, isotonic `0.6476`;
  - CatBoost raw log loss `0.6430`, Platt `0.6424`, isotonic `0.6404`;
  - reliability plots written under `data/models/calibration/`.
- Added calibrated UFC CatBoost serving artifact:
  - command: `uv run python -m mma_eff_lab train-calibrated-ufc-catboost`;
  - model artifacts under `data/models/calibrated_ufc_catboost_v1/`;
  - UFCStats test raw log loss `0.6428`, Brier `0.2257`, AUC `0.6848`;
  - UFCStats test isotonic log loss `0.6409`, Brier `0.2247`, AUC `0.6826`;
  - UFCStats test accuracy `63.85%`.
- Added prediction commands:
  - `predict-fight`;
  - `predict-card`.
- Prediction smoke checks:
  - ambiguous exact names are rejected with candidate IDs;
  - `Edgar Chairez` vs `ufcstats:294aa73dbf37d281` produced valid probabilities;
  - one-row `predict-card` CSV produced valid probabilities.
- UFC Freedom 250 / UFC White House card checked from live sources:
  - event date: `2026-06-14`;
  - seven fights;
  - card CSV written to `data/upcoming/ufc_freedom_250_card.csv`.
- UFC Freedom 250 predictions written to
  `data/predictions/ufc_freedom_250_predictions.csv`.
- Final card predictions now use `calibrated_ufc_catboost_v1`, not raw XGBoost.
- Explanation plots written:
  - `data/predictions/ufc_freedom_250_probabilities.png`;
  - `data/predictions/ufc_freedom_250_polymarket_edges.png`.
- Polymarket UFC games page checked for live June 14 markets and visible prices.
  Comparison artifact written to
  `data/predictions/ufc_freedom_250_polymarket_comparison.csv`.
- Current largest model-vs-market no-vig differences:
  - Steve Garcia over Diego Lopes: `+12.93pp`;
  - Kyle Daukaus over Bo Nickal: `+12.02pp`;
  - Derrick Lewis over Josh Hokit: `+11.43pp`;
  - Justin Gaethje over Ilia Topuria: `+10.74pp`.
- Verification after expanded features:
  - `uv run pytest` passed (`59` tests);
  - `uv run ruff check src tests` passed;
  - `uv run python -m mma_eff_lab validate-model-quality` passed with `8` pass,
    `1` warning, `0` fail;
  - `uv run python -m mma_eff_lab validate-warehouse` passed with known warnings.

# Rating Features for Fight Outcome Model

## Plan

- [x] Add point-in-time dynamic rating and recent-form features to PIT fighter features.
- [x] Ensure same-date fights do not influence each other through ratings.
- [x] Let the existing deterministic model dataset include the new delta features.
- [x] Add focused tests for rating feature chronology and model feature propagation.
- [x] Rebuild features/model artifacts and compare metrics against the current baseline.
- [x] Add and run the three-model benchmark requested by the user.
- [x] Add and run model/data quality checks for leakage, chronology, and source bias risk.

## Review / Results

- Added point-in-time Elo-style features:
  - `pre_fight_elo`;
  - `elo_expected_win_prob`;
  - `elo_uncertainty`;
  - `recent_3_win_rate`;
  - `recent_5_win_rate`.
- Same-date fights are rated from the pre-date rating state, so earlier fights on
  the same event date do not leak into later same-date fights.
- Rebuilt features:
  - `pit_fighter_features`: `35,676`;
  - `pit_matchup_features`: `17,838`.
- Rebuilt model dataset:
  - training rows: `17,541`;
  - excluded draw/no-contest rows: `297`;
  - feature columns: `24`.
- XGBoost default temporal split after rating features:
  - validation log loss: `0.6500`; validation AUC: `0.6615`; validation accuracy: `62.84%`;
  - test log loss: `0.6447`; test AUC: `0.6737`; test accuracy: `63.16%`;
  - UFCStats test AUC: `0.6898`;
  - Sherdog test AUC: `0.6543`.
- Expanding-window walk-forward backtest, 8 folds / `8,608` out-of-sample rows:
  - without rating features: accuracy `62.08%`, log loss `0.6534`, AUC `0.6573`;
  - with rating features: accuracy `62.71%`, log loss `0.6497`, AUC `0.6640`.
- Added `benchmark-fight-models` command and wrote benchmark results to
  `data/models/fight_outcome_benchmarks.json`.
- Added `validate-model-quality` command and wrote quality results to
  `data/models/model_quality_report.json`.
- Three-model benchmark, temporal test split:
  - baseline XGBoost: accuracy `63.55%`, log loss `0.6512`, AUC `0.6632`;
  - XGBoost + rating features: accuracy `63.16%`, log loss `0.6447`, AUC `0.6737`;
  - CatBoost + rating features: accuracy `63.29%`, log loss `0.6478`, AUC `0.6694`.
- Three-model benchmark, expanding-window walk-forward:
  - baseline XGBoost: accuracy `62.08%`, log loss `0.6534`, AUC `0.6573`;
  - XGBoost + rating features: accuracy `62.71%`, log loss `0.6497`, AUC `0.6640`;
  - CatBoost + rating features: accuracy `62.08%`, log loss `0.6513`, AUC `0.6601`.
- Model-quality audit:
  - `8` pass, `1` warning, `0` fail;
  - no forbidden red/blue/corner/winner/outcome/source/promotion training features;
  - deterministic fighter orientation has `0` violations;
  - temporal split has no date overlap;
  - walk-forward folds are expanding and chronological;
  - PIT prior counts have `0` current/same-date leakage mismatches;
  - source performance gap check passed for the primary XGBoost + rating model;
  - remaining warning is high missingness in detailed striking/grappling deltas.
- Top XGBoost gain features after retrain:
  - `delta_elo_expected_win_prob`;
  - `delta_pre_fight_elo`;
  - `delta_prior_wins`;
  - `delta_age_years`;
  - `delta_reach_in`.
- Verification:
  - `uv run pytest tests/test_warehouse_and_pit.py::test_pit_features_exclude_current_and_same_date_fights tests/test_models.py` passed.
  - `uv run ruff check src/mma_eff_lab/features/pit.py tests/test_warehouse_and_pit.py tests/test_models.py` passed.
  - `uv run pytest` passed (`52` tests).
  - `uv run ruff check src tests` passed.
  - `uv run python -m mma_eff_lab validate-warehouse` passed with known warnings only:
    quarantined rows and unresolved Sherdog identities.
  - `uv run python -m mma_eff_lab benchmark-fight-models` passed.
  - `uv run python -m mma_eff_lab validate-model-quality` passed with `0` failures.

# Unified Fighter Linkage and DWCS Coverage

## Plan

- [x] Inspect current UFCStats/Sherdog identity link coverage and unresolved counts.
- [x] Verify where Dana White's Contender Series data exists and why it is absent.
- [x] Add DWCS as an important Sherdog promotion seed.
- [x] Add conservative DOB-tolerant automatic identity links for source date discrepancies.
- [x] Add Sherdog Fight Finder profile search for UFC fighters missing Sherdog links.
- [x] Rebuild parse/warehouse/features/audit and compare linkage/data coverage.
- [x] Run XGBoost training after improved data is validated.

## Review / Results

- Current pre-change identity coverage:
  - UFCStats fighters: `2,694`.
  - Sherdog fighters: `6,600`.
  - Sherdog linked to UFC canonical fighters: `856`.
  - Sherdog unresolved/Sherdog-only: `5,744`.
  - UFC fighters with linked Sherdog profile: `856 / 2,694`.
  - UFC fighters with Sherdog fights in warehouse: `831 / 2,694`.
- DWCS source finding:
  - UFCStats completed events cache has no Contender Series / DWCS events.
  - Sherdog has organization `Dana-Whites-Contender-Series-12411`.
  - Sherdog reports that promotion has held `89` events and about `440` matches.
- Implemented DWCS as part of the Sherdog `major` promotion seed list.
- Implemented conservative automatic identity links for unique exact/cleaned names
  with compatible DOB discrepancies:
  - near date offset;
  - month/day swap.
- Implemented Sherdog UFC profile search:
  - command: `uv run python -m mma_eff_lab download-sherdog-ufc-profiles`.
  - searches UFCStats fighters without a linked Sherdog profile;
  - tries initial variants like `TJ` -> `T.J.`;
  - downloads only unique exact-name Fight Finder results;
  - skips ambiguous names instead of guessing.
- Profile search sweep results:
  - UFC unlinked fighters searched: `1,557`.
  - Sherdog search requests: `1,578`.
  - unique exact profile matches: `1,212`.
  - new Sherdog fighter profiles downloaded: `1,176`.
  - already cached profile matches: `36`.
  - no exact match: `170`.
  - ambiguous exact match skipped: `175`.
  - search/download failures: `0`.
- Final identity coverage:
  - UFCStats fighters: `2,694`.
  - Sherdog fighters: `8,255`.
  - Sherdog linked to UFC canonical fighters: `2,192`.
  - Sherdog unresolved/Sherdog-only: `6,063`.
  - UFC fighters with linked Sherdog profile: `2,192 / 2,694`.
  - UFC fighters still without linked Sherdog profile: `502 / 2,694`.
  - UFC fighters with Sherdog fights in warehouse: `1,123 / 2,694`.
- Link-method additions:
  - `cleaned_name_dob`: `1,534`.
  - `cleaned_name_dob_near`: `27`.
  - `cleaned_name_dob_month_day_swap`: `26`.
  - `cleaned_name_dob_same_year_close`: `25`.
  - `exact_name_dob`: `555`.
  - `exact_name_dob_near`: `11`.
  - `exact_name_dob_month_day_swap`: `11`.
  - `exact_name_dob_same_year_close`: `3`.
- DWCS coverage after rebuild:
  - `89` Sherdog DWCS events.
  - `351` DWCS fights.
  - event date range: `2017-07-11` to `2025-10-14`.
- Rebuild outputs:
  - `events`: `2,050`.
  - `fights`: `17,838`.
  - `fight_participants`: `35,676`.
  - `fighters`: `8,757`.
  - `pit_matchup_features`: `17,838`.
  - latest UFCStats event date: `2026-06-06`.
  - latest Sherdog event date: `2026-06-06`.
- XGBoost training after rebuild:
  - command: `uv run python -m mma_eff_lab train-xgboost-model`.
  - wall-clock time: `1.69s`.
  - validation log loss: `0.6535`; validation Brier: `0.2308`; validation AUC: `0.6543`.
  - test log loss: `0.6512`; test Brier: `0.2297`; test AUC: `0.6632`.
  - test source split: Sherdog AUC `0.6425`, UFCStats AUC `0.6801`.
- Audit after final rebuild:
  - `179` checks pass.
  - `2` warnings remain: `2` quarantined rows, unresolved Sherdog-only identities.

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
  - input rows: `17,838`;
  - binary training rows: `17,541`;
  - excluded draw/no-contest rows: `297`;
  - label balance: `8,303` fighter A wins, `9,238` fighter B wins.
- Verification:
  - `uv run pytest tests/test_models.py` passed (`5` tests).
  - `uv run ruff check src tests` passed.
  - `uv run pytest` passed (`42` tests).
- Environment note:
  - Local `libomp` is available.
  - Full training command completes successfully.

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
  - `pit_matchup_features`: `17,838` fights.
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
