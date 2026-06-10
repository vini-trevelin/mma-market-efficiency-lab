# Data Sources

## Canonical UFC Source

UFCStats is the canonical source for UFC events, fights, fighter bios, and detailed
fight stats. The downloader starts from completed events and caches raw HTML before
any parsing.

Source: http://ufcstats.com/statistics/events/completed?page=all

Note: local requests to UFCStats HTTPS currently refuse connections in this environment,
while HTTP returns `200 OK`. The downloader therefore uses HTTP and normalizes UFCStats
links to that host.

Current request behavior note: UFCStats may return a JavaScript browser-check page
instead of real HTML to plain clients. The downloader contains a request-side
proof-of-work workaround that posts to `/__c`, preserves the returned session
cookie, and retries the original page fetch.

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

Operational note: Sherdog access can change with VPN/IP path. When request access
works, the normal downloader can sweep organization, event, and fighter pages.
When it fails, the block tends to happen at live organization or event detail
requests rather than in the parser.

## Deferred Sources

- UFC.com: useful supplemental athlete/stat definitions, but not v0 canonical.
- Tapology: deferred. Treat as a separate source strategy later, with fresh
  terms/robots review before any scraping.
- Kaggle UFC/MMA datasets: reference/sanity checks only. Not ingested in v0.

## Odds

Odds are explicitly out of scope for v0. No odds tables, importers, paid APIs, scraping,
betting strategy, or market-efficiency analysis are implemented in this MVP.
