# MMA Market Efficiency Lab MVP

## Plan

- [x] Scaffold Python package, uv config, docs, gitignore, and local data dirs policy.
- [x] Implement UFCStats downloader with raw HTML cache and manifest.
- [x] Implement cached HTML parsers and DuckDB warehouse build.
- [x] Implement point-in-time fighter and matchup features with same-date exclusion.
- [x] Implement static reports and local FastAPI command/table API.
- [x] Implement minimal Vite React/shadcn-style UI with pinned npm dependencies.
- [x] Add parser, downloader, warehouse, PIT, and API tests.
- [x] Run verification and record results.

## Review / Results

- `uv run ruff check .` passed.
- `uv run pytest` passed: 9 tests.
- `cd apps/web && npm ci && npm run build` passed with 0 npm vulnerabilities.
- Browser smoke passed at `http://127.0.0.1:5173/`: Health, Tables, Commands tabs render.

# Sherdog Non-UFC Event Data MVP

## Plan

- [x] Add Sherdog major-promotion downloader with raw cache, manifest, retries, and missing-only default.
- [x] Add Sherdog parsers for org pages, event cards, optional fighter bios, and ONE quarantine.
- [x] Make warehouse tables source-aware with staging tables, identity links, and parse quarantine.
- [x] Update PIT features to use canonical fighter identities and supplemental Sherdog history without leaking same-date/current fights.
- [x] Expose Sherdog commands/tables/source filters in the local API and shadcn UI.
- [x] Add focused parser, downloader, warehouse, PIT, API, and UI verification coverage.

## Review / Results

- `uv run ruff check .` passed.
- `uv run pytest` passed: 15 tests.
- `cd apps/web && npm run build` passed.
- Limited Sherdog smoke passed with `download-sherdog --limit-events 1 --sleep-seconds 0`.
- Local API/UI restarted at `http://127.0.0.1:8000` and `http://127.0.0.1:5173`.
- API source filter smoke passed for `source_events?source=sherdog&promotion=Bellator`.

# Database Audit UI

## Plan

- [x] Add `validate-warehouse` command that writes derived audit tables without mutating core warehouse tables.
- [x] Add audit API endpoints for summary, checks, coverage, identity, and quarantine review.
- [x] Expand the UI into read-only Overview, Coverage, Quality, Identity, Quarantine, Tables, and Commands tabs.
- [x] Improve generic table pagination/filtering and preserve useful filters in URL query params.
- [x] Add validation/API tests and keep frontend build verification green.

## Review / Results

- `uv run ruff check .` passed.
- `uv run pytest` passed: 19 tests.
- `cd apps/web && npm run build` passed.
- Did not run `validate-warehouse` against the active local warehouse because the full Sherdog scrape is still running.
