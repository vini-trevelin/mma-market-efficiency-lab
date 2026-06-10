# Task Log

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
