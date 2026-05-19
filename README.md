# MMA Market Efficiency Lab

Local-first UFC/MMA data foundation. MVP scope is data only: raw UFCStats caching,
warehouse tables, point-in-time fighter features, static inspection reports, and a
minimal local UI.

No modeling, betting strategy, bankroll simulation, backtesting, or odds ingestion in v0.

## Requirements

- `uv 0.11+`
- Python `3.12` managed by `uv`
- Node `24.14.1`
- npm `11.11.0`

## Python Setup

```bash
uv sync --extra dev
```

## Pipeline

```bash
uv run python -m mma_eff_lab download-ufcstats
uv run python -m mma_eff_lab parse-ufcstats
uv run python -m mma_eff_lab build-warehouse
uv run python -m mma_eff_lab build-features
uv run python -m mma_eff_lab make-reports
```

`download-ufcstats` is missing-only by default. Use `--force` only from the CLI when you
intentionally want to overwrite cached raw HTML.

## API

```bash
uv run uvicorn mma_eff_lab.api.app:app --reload
```

The API is local-first and exposes read-only table access plus allowlisted pipeline commands.

## UI

```bash
cd apps/web
npm ci
npm run dev
```

The UI shows health, warehouse tables, and safe command controls. It does not edit data.

## Verification

```bash
uv run ruff check .
uv run pytest
cd apps/web && npm ci && npm run build
```
