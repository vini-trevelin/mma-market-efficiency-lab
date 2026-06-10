# Task History

This file archives completed milestone notes that previously lived in
`tasks/todo.md`.

## Completed Milestones

### MMA Market Efficiency Lab MVP

- Scaffolded the Python package, `uv` config, docs, gitignore, and local data
  directory policy.
- Implemented UFCStats downloading with raw HTML cache and manifest.
- Implemented cached HTML parsers and DuckDB warehouse build.
- Implemented point-in-time fighter and matchup features with same-date
  exclusion.
- Implemented static reports and a local FastAPI command/table API.
- Implemented a minimal Vite React UI with pinned dependencies.
- Added parser, downloader, warehouse, PIT, and API tests.

Verification recorded at the time:

- `uv run ruff check .` passed.
- `uv run pytest` passed: 9 tests.
- `cd apps/web && npm ci && npm run build` passed.
- Browser smoke passed for Health, Tables, and Commands tabs.

### Sherdog Non-UFC Event Data MVP

- Added Sherdog major-promotion downloading with raw cache, manifest, retries,
  and missing-only default behavior.
- Added Sherdog parsers for organization pages, event cards, optional fighter
  bios, and ONE quarantine behavior.
- Made warehouse tables source-aware with staging tables, identity links, and
  parse quarantine.
- Updated PIT features to use canonical fighter identities plus supplemental
  Sherdog history without same-date leakage.
- Exposed Sherdog commands, tables, and source filters in the API and UI.

Verification recorded at the time:

- `uv run ruff check .` passed.
- `uv run pytest` passed: 15 tests.
- `cd apps/web && npm run build` passed.
- Limited Sherdog smoke passed with `download-sherdog --limit-events 1 --sleep-seconds 0`.

### Database Audit UI

- Added `validate-warehouse` to write derived audit tables without mutating core
  warehouse tables.
- Added audit API endpoints for summary, checks, coverage, identity, and
  quarantine review.
- Expanded the UI into audit and drilldown tabs.
- Improved table pagination and URL-preserved filtering.

Verification recorded at the time:

- `uv run ruff check .` passed.
- `uv run pytest` passed: 19 tests.
- `cd apps/web && npm run build` passed.

### Sherdog Repair and Database Analysis Workbench

- Fixed Sherdog event parsing so authoritative result tables drive warehouse and
  PIT rows.
- Added defensive participant dedupe and quarantine for invalid fight shapes.
- Added `repair-sherdog-major` and preserved typed empty quarantine tables.
- Hardened validation with participant-shape, uniqueness, PIT same-day
  exclusion, schema checks, and derived analysis views.
- Reworked the UI into Overview, Events, Fights, Fighters, Identity, Quality,
  Quarantine, Tables, and Commands drilldown flows.

Verification recorded at the time:

- `uv run ruff check .` passed.
- `uv run pytest` passed: 23 tests.
- `cd apps/web && npm run build` passed.
- `uv run python -m mma_eff_lab repair-sherdog-major` passed.
- Repaired warehouse counts reached:
  - `events`: `1954`
  - `fights`: `17447`
  - `fight_participants`: `34894`
  - `pit_matchup_features`: `17447`
  - `parse_quarantine`: `2`

### Identity Resolution Pipeline V1

- Fixed UFCStats fighter-name parsing so `Record: ...` suffixes do not pollute
  identity matching.
- Added deterministic Sherdog to UFCStats linking by exact-name+DOB and
  cleaned-name+DOB, with no automatic name-only linking.
- Exposed identity provenance and review status in warehouse, audit, and UI
  outputs.
- Added parser, warehouse, audit, and API coverage for cleaned links, ambiguous
  matches, and non-linking name-only cases.

Verification recorded at the time:

- `uv run ruff check src tests` passed.
- `uv run pytest` passed: 28 tests.
- `cd apps/web && npm run build` passed.
- Cache-only rebuild completed through parse, warehouse, features, and audit.
- Post-rebuild counts reached:
  - `events`: `1954`
  - `fights`: `17447`
  - `fight_participants`: `34894`
  - `fighters`: `8423`
  - `pit_matchup_features`: `17447`

### Manual Identity Review and Fix Workflow V1

- Added persisted manual identity overrides with pair-level approve/reject
  semantics.
- Applied manual overrides ahead of deterministic automatic linking in
  `build-warehouse`.
- Added writable API endpoints for identity review, candidate lookup, decision
  save and clear, and background apply.
- Reworked the Identity tab into a manual review tool with candidate drilldown
  and live rebuild logs.

Verification recorded at the time:

- `uv run ruff check src tests` passed.
- `uv run pytest` passed: 33 tests.
- `cd apps/web && npm run build` passed.
- Live warehouse refreshed with `uv run python -m mma_eff_lab apply-identity-overrides`.

### Accepted Unresolved Identity State

- Added manual `accepted_unresolved` so a reviewed Sherdog fighter can be marked
  as having no valid UFC candidate without forcing a link.
- Surfaced `No candidates` and `Clear no candidates` actions in the Identity
  review panel and corresponding filters/audit views.
- Made the dev UI use a local `/api` proxy and aligned read-only DuckDB access
  for candidate detail loading.

Verification recorded at the time:

- `uv run ruff check src tests` passed.
- `uv run pytest tests/test_api.py tests/test_audit.py tests/test_warehouse_and_pit.py`
  passed: 23 tests.
- `cd apps/web && npm run build` passed.

### Repository Workflow Docs and Local Dev Restart

- Added root `AGENTS.md` pointing to repository docs.
- Added `docs/repository-guide.md`.
- Cleared a conflicting Vite process and restarted the local API/UI for this
  repo.

Verification recorded at the time:

- `curl http://127.0.0.1:8000/health` passed with `ok: true`.
- `curl http://127.0.0.1:5173/` returned the repo's Vite app shell.
