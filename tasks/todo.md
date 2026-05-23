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

# Sherdog Repair + Database Analysis Workbench

## Plan

- [x] Fix Sherdog event parsing so result tables are authoritative and duplicate main-event parsing does not leak into warehouse/PIT rows.
- [x] Add defensive Sherdog participant dedupe and quarantine invalid two-corner fight shapes before canonical warehouse build.
- [x] Add `repair-sherdog-major`, retry missing cached Sherdog fighter bios, and preserve typed empty quarantine tables.
- [x] Harden validation with participant-shape, matchup-uniqueness, PIT same-day exclusion, schema checks, and derived analysis views.
- [x] Rework the local UI into Overview, Events, Fights, Fighters, Identity, Quality, Quarantine, Tables, and Commands drilldown flows.
- [x] Rebuild the local warehouse from cache, rerun PIT features and audit, and verify the repaired API/UI surfaces.

## Review / Results

- `uv run ruff check .` passed.
- `uv run pytest` passed: 23 tests.
- `cd apps/web && npm run build` passed.
- `uv run python -m mma_eff_lab repair-sherdog-major` passed.
- Repair retried `1` missing Sherdog fighter page and downloaded it successfully.
- Repaired warehouse counts:
  - `events`: `1954`
  - `fights`: `17447`
  - `fight_participants`: `34894`
  - `pit_matchup_features`: `17447`
  - `parse_quarantine`: `2`
- Post-repair audit checks have `0` hard failures and `2` warnings:
  - unresolved Sherdog identities
  - `2` quarantined invalid-participant-shape fights
- The original duplicate-matchup defects no longer show anomalies:
  - `sherdog:67133:11`
  - `sherdog:76363:12`

# Identity Resolution Pipeline V1

## Plan

- [x] Fix UFCStats fighter-name parsing so identity matching does not retain `Record: ...` suffixes.
- [x] Add deterministic exact-name+DOB and cleaned-name+DOB Sherdog→UFCStats linking inside `build-warehouse`, with no name-only auto-links.
- [x] Expose identity provenance and review status in warehouse/audit outputs and the read-only Identity UI.
- [x] Add parser, warehouse, audit, and API coverage for cleaned links, ambiguous matches, and non-linking name-only cases.
- [x] Rebuild the local warehouse from cached HTML only, rerun PIT/audit, and verify real deterministic link counts.

## Review / Results

- `uv run ruff check src tests` passed.
- `uv run pytest` passed: `28` tests.
- `cd apps/web && npm run build` passed.
- Cache-only rebuild completed:
  - `uv run python -m mma_eff_lab parse-ufcstats`
  - `uv run python -m mma_eff_lab parse-sherdog`
  - `uv run python -m mma_eff_lab build-warehouse`
  - `uv run python -m mma_eff_lab build-features`
  - `uv run python -m mma_eff_lab validate-warehouse`
- Post-rebuild canonical counts:
  - `events`: `1954`
  - `fights`: `17447`
  - `fight_participants`: `34894`
  - `fighters`: `8423`
  - `pit_matchup_features`: `17447`
- Deterministic Sherdog→UFCStats identity links now exist:
  - `exact_name_dob`: `209`
  - `cleaned_name_dob`: `646`
  - unresolved Sherdog rows: `5730`
- Current audit warnings remain limited to:
  - unresolved Sherdog identities
  - `2` quarantined invalid-participant-shape fights

# Manual Identity Review and Fix Workflow V1

## Plan

- [x] Add persisted local manual identity overrides with pair-level approve/reject semantics.
- [x] Apply manual overrides during `build-warehouse` ahead of deterministic exact/cleaned DOB-gated linking.
- [x] Add writable local API endpoints for identity review, candidate lookup, decision save/clear, and background apply.
- [x] Rework the Identity tab into a manual review tool with candidate drilldown, approve/reject/clear actions, and live rebuild logs.
- [x] Expand audit coverage and verification for manual override counts, `linked_manual` review status, and conflict detection.

## Review / Results

- `uv run ruff check src tests` passed.
- `uv run pytest` passed: `33` tests.
- `cd apps/web && npm run build` passed.
- Live warehouse refreshed with `uv run python -m mma_eff_lab apply-identity-overrides`.
- Live API restarted on the new code at `http://127.0.0.1:8000`.
- Live UI verified at `http://127.0.0.1:5173/`:
  - Identity review panel renders manual note/search/actions.
  - Commands tab exposes `apply-identity-overrides`.
- Live warehouse now includes:
  - `fighter_identity_manual_overrides`: `0`
  - `analysis_identity_review`: `6585`
  - `audit_summary`: `40`

# Accepted Unresolved Identity State

## Plan

- [x] Add a manual `accepted_unresolved` decision so a reviewed Sherdog fighter can be marked as "no candidates" without forcing a UFC link.
- [x] Surface `No candidates` and `Clear no candidates` actions in the Identity detail panel and expose the new state in Identity filters/audit views.
- [x] Make the dev UI use a local `/api` proxy and align read-only DuckDB access so the live browser can load review rows and candidate details reliably.
- [x] Add coverage for accepted-unresolved persistence, audit warning behavior, and the read-only candidate endpoint connection path.

## Review / Results

- `uv run ruff check src tests` passed.
- `uv run pytest tests/test_api.py tests/test_audit.py tests/test_warehouse_and_pit.py` passed: `23` tests.
- `cd apps/web && npm run build` passed.
- Live services restarted:
  - API: `http://127.0.0.1:8000`
  - UI: `http://127.0.0.1:5173`
- Browser verification passed after reload:
  - Identity review table loads through the local `/api` proxy.
  - Candidate detail for `source_fighter_id=406849` loads without fetch errors.
  - `No candidates` action is visible in the Identity review panel.
  - End-to-end accept/clear verification passed for `source_fighter_id=406849`, and the live warehouse was restored to `fighter_identity_manual_overrides = 0`.
