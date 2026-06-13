# MMA Market Efficiency Lab

Local-first MMA historical data and feature pipeline backed by cached UFCStats
and Sherdog HTML plus a DuckDB warehouse.

## Core Update Flow

Refresh raw source cache:

```bash
uv run python -m mma_eff_lab download-ufcstats
uv run python -m mma_eff_lab download-sherdog --promotion-set major
```

After a warehouse exists, expand UFC-to-Sherdog identity coverage by searching
Sherdog Fight Finder for UFC fighters that still lack a linked Sherdog profile:

```bash
uv run python -m mma_eff_lab download-sherdog-ufc-profiles
uv run python -m mma_eff_lab parse-sherdog
uv run python -m mma_eff_lab build-warehouse
```

Rebuild parsed outputs, warehouse, features, and audit:

```bash
uv run python -m mma_eff_lab parse-ufcstats
uv run python -m mma_eff_lab parse-sherdog
uv run python -m mma_eff_lab build-warehouse
uv run python -m mma_eff_lab build-features
uv run python -m mma_eff_lab validate-warehouse
```

Build the leak-resistant binary model dataset and train the XGBoost V1 model:

```bash
uv run python -m mma_eff_lab build-model-dataset
uv run python -m mma_eff_lab train-xgboost-model
uv run python -m mma_eff_lab train-calibrated-ufc-catboost
```

Run the fight-outcome model benchmark suite:

```bash
uv run python -m mma_eff_lab benchmark-fight-models
uv run python -m mma_eff_lab evaluate-model-calibration --source ufcstats
uv run python -m mma_eff_lab validate-model-quality
```

Predict a future fight or card from current warehouse history:

```bash
uv run python -m mma_eff_lab predict-fight \
  --fighter-a "Fighter A" \
  --fighter-b "Fighter B" \
  --event-date YYYY-MM-DD \
  --model-version calibrated_ufc_catboost_v1

uv run python -m mma_eff_lab predict-card \
  --input data/upcoming/card.csv \
  --output data/predictions/card_predictions.csv \
  --model-version calibrated_ufc_catboost_v1
```

On macOS, XGBoost requires OpenMP at runtime:

```bash
brew install libomp
```

One-command local identity reapply after review changes:

```bash
uv run python -m mma_eff_lab apply-identity-overrides
```

## What Each Step Does

- `download-ufcstats`: updates raw UFCStats event, fight, and fighter HTML cache.
- `download-sherdog --promotion-set major`: updates raw Sherdog major-promotion
  event and fighter HTML cache.
- `download-sherdog-ufc-profiles`: searches Sherdog Fight Finder for UFCStats
  fighters without a linked Sherdog profile, downloads only unique exact-name
  profile matches, and skips ambiguous names for manual review.
- `parse-ufcstats`: converts cached UFCStats HTML into parsed parquet tables.
- `parse-sherdog`: converts cached Sherdog HTML into parsed parquet tables.
- `build-warehouse`: builds canonical warehouse tables in `data/warehouse/mma.duckdb`.
- `build-features`: rebuilds point-in-time fighter and matchup features.
- `build-model-dataset`: writes a binary, deterministic-orientation fight outcome
  dataset for model training.
- `train-xgboost-model`: trains the XGBoost fight outcome model and writes model,
  metadata, and metrics artifacts under `data/models/`.
- `train-calibrated-ufc-catboost`: trains the UFC-serving CatBoost model, fits
  isotonic calibration from validation probabilities, and writes artifacts under
  `data/models/calibrated_ufc_catboost_v1/`.
- `benchmark-fight-models`: compares baseline XGBoost, XGBoost with rating
  features, and CatBoost with rating features using temporal split and
  walk-forward evaluation.
- `evaluate-model-calibration`: writes UFC/source-filtered raw, Platt, and
  isotonic calibration metrics plus reliability plots.
- `validate-model-quality`: writes leakage, temporal-split, source-gap, label
  balance, and missingness checks for model/data quality.
- `predict-fight`: predicts one future matchup from current warehouse history.
- `predict-card`: predicts each row in a card CSV with columns
  `event_date,fighter_a,fighter_b`.
- `validate-warehouse`: rebuilds derived audit and analysis tables.
- `apply-identity-overrides`: reruns warehouse, features, and audit with current
  manual identity review decisions.

## Current Source Notes

- UFCStats direct requests currently use a built-in proof-of-work workaround in
  the downloader to pass the site browser-check page and continue with normal
  `requests` fetches.
- Sherdog major-promotion pages currently refresh successfully through normal
  `requests` from this environment.
- Raw HTML cache lives under `data/raw/`.
- Parsed parquet outputs and the DuckDB warehouse live under `data/warehouse/`.
