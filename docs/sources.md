# Data Sources

## MVP Source

UFCStats is the canonical v0 source. The downloader starts from completed events and
caches raw HTML before any parsing.

Source: http://ufcstats.com/statistics/events/completed?page=all

Note: local requests to UFCStats HTTPS currently refuse connections in this environment,
while HTTP returns `200 OK`. The downloader therefore uses HTTP and normalizes UFCStats
links to that host.

## Deferred Sources

- UFC.com: useful supplemental athlete/stat definitions, but not v0 canonical.
- Tapology and Sherdog: deferred. Treat as separate source strategy later, with fresh
  terms/robots review before any scraping.
- Kaggle UFC/MMA datasets: reference/sanity checks only. Not ingested in v0.

## Odds

Odds are explicitly out of scope for v0. No odds tables, importers, paid APIs, scraping,
betting strategy, or market-efficiency analysis are implemented in this MVP.
