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
