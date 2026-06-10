# Repository Guide

## Purpose

MMA Market Efficiency Lab is a local-first data and modeling workspace for MMA
historical data. The current codebase builds a DuckDB warehouse from cached
UFCStats and Sherdog HTML, creates point-in-time fighter and matchup features,
and exposes a local FastAPI + Vite review workbench.

The near-term work pattern is quant engineering, not product exploration:
preserve correctness, expose assumptions, keep changes small, and verify with
tests and warehouse checks.

## Documentation Map

- `AGENTS.md`: root entrypoint for agent behavior. It points here and defines
  the minimum context that must be read before non-trivial work.
- `docs/repository-guide.md`: this guide. It describes workflow, project shape,
  commands, verification expectations, and modeling guardrails.
- `docs/sources.md`: source-of-truth notes for UFCStats, Sherdog, deferred
  sources, and odds scope. Read it before changing download, parse, source-link,
  or ingestion behavior.
- `tasks/todo.md`: active project log. New work should get a short plan,
  checkable progress items, and a review/results section.
- `README.md`: short operator-facing summary and the primary update command flow.

## Current Project Shape

- Python package: `src/mma_eff_lab`
- API: `src/mma_eff_lab/api/app.py`
- CLI entrypoint: `src/mma_eff_lab/__main__.py`
- Warehouse build: `src/mma_eff_lab/warehouse/build.py`
- Point-in-time features: `src/mma_eff_lab/features/pit.py`
- Audit/validation: `src/mma_eff_lab/audit/warehouse.py`
- Parsers: `src/mma_eff_lab/parse`
- Downloaders: `src/mma_eff_lab/download`
- React workbench: `apps/web`
- Tests: `tests`
- Local generated data: `data`, ignored by git

## Workflow

For non-trivial work:

1. Read the root instructions and repository docs.
2. Inspect relevant config, source, tests, and data assumptions.
3. Write a concise plan in `tasks/todo.md`.
4. Execute only the approved scope.
5. Run focused tests and any required warehouse/API/UI verification.
6. Record results in `tasks/todo.md`.

Simple inspection tasks may be handled directly, but still report facts,
assumptions, and any discovered risks clearly.

## Task Log Pattern

Use one heading per task in `tasks/todo.md`.

Each task should contain:

- `## Plan` with checkable items.
- `## Review / Results` with commands run, pass/fail status, and important
  data counts or known residual risks.

Keep the task log factual. Do not mark work complete until verification exists.

## Local Commands

Python checks:

```bash
uv run ruff check src tests
uv run pytest
```

Frontend checks:

```bash
cd apps/web
npm run build
```

API server:

```bash
uv run uvicorn mma_eff_lab.api.app:app --host 127.0.0.1 --port 8000
```

Frontend dev server:

```bash
cd apps/web
npm run dev -- --host 127.0.0.1 --port 5173
```

Common data commands:

```bash
uv run python -m mma_eff_lab parse-ufcstats
uv run python -m mma_eff_lab parse-sherdog
uv run python -m mma_eff_lab build-warehouse
uv run python -m mma_eff_lab build-features
uv run python -m mma_eff_lab validate-warehouse
uv run python -m mma_eff_lab apply-identity-overrides
```

Downloader commands can hit external sites and should be run intentionally:

```bash
uv run python -m mma_eff_lab download-ufcstats
uv run python -m mma_eff_lab download-sherdog --promotion-set major
```

## Update Playbook

Normal refresh from live sources:

```bash
uv run python -m mma_eff_lab download-ufcstats
uv run python -m mma_eff_lab download-sherdog --promotion-set major
uv run python -m mma_eff_lab parse-ufcstats
uv run python -m mma_eff_lab parse-sherdog
uv run python -m mma_eff_lab build-warehouse
uv run python -m mma_eff_lab build-features
uv run python -m mma_eff_lab validate-warehouse
```

Use this order intentionally:

1. Downloaders update raw HTML cache only.
2. Parse steps regenerate parquet staging tables from raw cache.
3. `build-warehouse` rewrites canonical DuckDB tables.
4. `build-features` rewrites PIT feature tables from the canonical warehouse.
5. `validate-warehouse` rewrites audit and analysis tables.

If manual identity decisions changed, use:

```bash
uv run python -m mma_eff_lab apply-identity-overrides
```

That command runs warehouse rebuild, feature rebuild, and audit rebuild in one pass.

## Script Responsibilities

- `src/mma_eff_lab/download/ufcstats.py`: request-based UFCStats cache refresh,
  including the current browser-check proof-of-work workaround.
- `src/mma_eff_lab/download/sherdog.py`: Sherdog organization, event, and fighter
  cache refresh for the configured promotion sets.
- `src/mma_eff_lab/parse/ufcstats.py`: parse cached UFCStats HTML into event,
  fight, participant, fighter, and stat rows.
- `src/mma_eff_lab/parse/sherdog.py`: parse cached Sherdog HTML into source-aware
  event, fight, participant, fighter, and quarantine rows.
- `src/mma_eff_lab/warehouse/build.py`: convert parsed parquet inputs into
  canonical warehouse tables and identity-link tables.
- `src/mma_eff_lab/features/pit.py`: rebuild point-in-time fighter and matchup features.
- `src/mma_eff_lab/audit/warehouse.py`: rebuild audit summary, checks, coverage,
  missingness, identity, and PIT analysis tables.

## Data and Source Rules

UFCStats is canonical for UFC events, fights, fighter bios, and detailed stats.
Sherdog is supplemental for major non-UFC event and result history.

Raw HTML is cached before parsing. Missing-only download is the default. Do not
replace cached data or force downloads unless the task requires it.

Current access notes:

- UFCStats may serve a JavaScript browser-check page to plain requests. The
  downloader now solves that proof-of-work challenge within the request session
  and retries the original URL.
- Sherdog access behavior can vary with network path and IP reputation. When it
  works, normal `requests` refresh the cache directly. When it does not, the
  failure usually appears as blocked organization or event pages rather than a
  parser error.

Identity linking is intentionally conservative:

- Source self-links are allowed.
- Sherdog to UFCStats automatic links require DOB-gated deterministic evidence.
- Name-only automatic links are not allowed.
- Manual overrides are local review state and must be auditable.

Odds are out of scope for the current MVP.

## Quant Engineering Guardrails

Always check for:

- Look-ahead bias.
- Same-date/current-fight leakage.
- Index and join alignment.
- Timestamp, calendar, and timezone assumptions.
- Units, signs, scales, and directionality.
- Deterministic outputs where expected.
- Sufficient audit tables, logs, assertions, or errors to diagnose failures.

For model work, start from a clear target definition, feature availability time,
train/test split policy, leakage checks, and baseline metrics before adding
complexity.

## Verification Standard

Tests are mandatory for behavior changes. Prefer focused test runs during
iteration and broader runs before completion.

For backend or warehouse work, verify:

- relevant unit tests
- row counts or audit checks when warehouse behavior changes
- API health/table responses when API behavior changes

For frontend work, verify:

- `npm run build`
- live browser/API flow when the behavior is user-facing
- loading, empty, error, and state transition behavior where relevant

If verification cannot be run, record why and what risk remains.
