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
```

Run the fight-outcome model benchmark suite:

```bash
uv run python -m mma_eff_lab benchmark-fight-models
uv run python -m mma_eff_lab validate-model-quality
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
- `benchmark-fight-models`: compares baseline XGBoost, XGBoost with rating
  features, and CatBoost with rating features using temporal split and
  walk-forward evaluation.
- `validate-model-quality`: writes leakage, temporal-split, source-gap, label
  balance, and missingness checks for model/data quality.
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
