# Task Log

Detailed completed milestone history lives in
[`docs/task-history.md`](../docs/task-history.md).

# Live Data Refresh and Main Commit

## Plan

- [x] Review repo workflow docs and current warehouse recency.
- [x] Clean up the active task log and move old completed work out of `tasks/todo.md`.
- [x] Attempt live UFCStats and Sherdog refreshes and record any source-side blockers.
- [x] Rebuild parsed tables, warehouse, features, and audit outputs from the refreshed cache.
- [x] Verify that the warehouse moved forward cleanly and record any residual warnings or failures.
- [ ] Commit the current documentation/task cleanup and successful refresh work to `main`.

## Review / Results

- Current warehouse recency before refresh:
  - `events.max(event_date) = 2026-05-16`
  - `source_events.max(event_date)` for `ufcstats` = `2026-05-16`
  - `source_events.max(event_date)` for `sherdog` = `2026-05-15`
- `tasks/todo.md` was reduced to an active log so new work is easier to read.
- Live-source refresh findings:
  - `download-ufcstats` does not refresh the root events index unless `force` is enabled, so a broad missing-only run walks the full cache instead of only new events.
  - A direct live `http://ufcstats.com/statistics/events/completed?page=all` request returned `200` but produced no parseable events in this environment.
  - `download-sherdog` discovered newer events, but the newest uncached event pages returned `403` on download.
- Cache rebuild and verification completed:
  - `uv run python -m mma_eff_lab parse-ufcstats` passed.
  - `uv run python -m mma_eff_lab parse-sherdog` passed.
  - `uv run python -m mma_eff_lab build-warehouse` passed.
  - `uv run python -m mma_eff_lab build-features` passed.
  - `uv run python -m mma_eff_lab validate-warehouse` passed.
  - `curl http://127.0.0.1:8000/health` passed.
- Warehouse moved forward after rebuild:
  - `source_events`: `1954 -> 1955`
  - latest `ufcstats` event date: `2026-05-16 -> 2026-05-30`
  - latest `sherdog` event date remained `2026-05-15`
  - latest event now present: `UFC Fight Night: Song vs. Figueiredo` on `2026-05-30`
- Current non-pass audit state after rebuild:
  - `fail`: `fighter_identity_manual_overrides.schema_types_match`
  - `warn`: unresolved Sherdog identities (`5729`)
  - `warn`: quarantined rows (`2`)
