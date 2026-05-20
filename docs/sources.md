# Data Sources

## Canonical UFC Source

UFCStats is the canonical source for UFC events, fights, fighter bios, and detailed
fight stats. The downloader starts from completed events and caches raw HTML before
any parsing.

Source: http://ufcstats.com/statistics/events/completed?page=all

Note: local requests to UFCStats HTTPS currently refuse connections in this environment,
while HTTP returns `200 OK`. The downloader therefore uses HTTP and normalizes UFCStats
links to that host.

## Supplemental Non-UFC Source

Sherdog is a supplemental source for major non-UFC event/fight/result history. It is
not used for UFC detailed stats and does not seed from fighter fight-history pages.

Major promotion seed set:

- Bellator MMA: https://www.sherdog.com/organizations/Bellator-MMA-1960
- Professional Fighters League: https://www.sherdog.com/organizations/Professional-Fighters-League-12241
- World Series of Fighting: https://www.sherdog.com/organizations/World-Series-of-Fighting-5449
- ONE Championship: https://www.sherdog.com/organizations/ONE-Championship-3877
- Pride Fighting Championships: https://www.sherdog.com/organizations/Pride-Fighting-Championships-3
- Strikeforce: https://www.sherdog.com/organizations/Strikeforce-716
- Rizin Fighting Federation: https://www.sherdog.com/organizations/Rizin-Fighting-Federation-10333
- Dream: https://www.sherdog.com/organizations/Dream-1357
- Invicta Fighting Championships: https://www.sherdog.com/organizations/Invicta-Fighting-Championships-4469

Rules:

- Raw HTML is cached under `data/raw/sherdog`.
- Missing-only download is the default; `--force` is CLI-only.
- Organization event pages seed event pages; event pages seed fighter bio pages.
- Fighter profile fight-history tables are not parsed as event seeds.
- ONE Championship rows with clear non-MMA discipline tokens are quarantined.
- Identity links are conservative: normalized full name plus exact DOB only.

## Deferred Sources

- UFC.com: useful supplemental athlete/stat definitions, but not v0 canonical.
- Tapology: deferred. Treat as a separate source strategy later, with fresh
  terms/robots review before any scraping.
- Kaggle UFC/MMA datasets: reference/sanity checks only. Not ingested in v0.

## Odds

Odds are explicitly out of scope for v0. No odds tables, importers, paid APIs, scraping,
betting strategy, or market-efficiency analysis are implemented in this MVP.
